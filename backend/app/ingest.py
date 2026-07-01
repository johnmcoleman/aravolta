r"""The ingestion pipeline: a bounded in-process buffer + a batch-writer task.

Flow:  endpoint --put_nowait--> _queue --> _batch_writer --COPY--> Timescale
                                                         \-> latest --> Dragonfly
"""
import asyncio
import logging
from datetime import datetime, timezone

from . import cache, db
from .config import settings
from .models import MetricIn

log = logging.getLogger("ingest")

# The buffer. Bounded so a slow DB causes backpressure (we shed load) rather
# than unbounded memory growth.
_queue: asyncio.Queue[tuple] = asyncio.Queue(maxsize=settings.queue_max)
_worker: asyncio.Task | None = None


class QueueFull(Exception):
    """Raised when the buffer is saturated — surfaced to the client as 503."""


def enqueue(m: MetricIn) -> None:
    """Hot path. O(1), never awaits the DB. Called by POST /api/metrics."""
    ts = m.timestamp or datetime.now(timezone.utc)
    try:
        # Tuple in COPY column order: (device_id, ts, power, temperature).
        _queue.put_nowait((m.device_id, ts, m.power, m.temperature))
    except asyncio.QueueFull:
        raise QueueFull()


async def _collect_batch() -> list[tuple]:
    """Block until the first row arrives, then gather more until we hit
    batch_max_size OR batch_max_interval_ms — whichever comes first."""
    batch = [await _queue.get()]                      # wait (idle) for the first row
    deadline = asyncio.get_event_loop().time() + settings.batch_max_interval_ms / 1000
    while len(batch) < settings.batch_max_size:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            batch.append(await asyncio.wait_for(_queue.get(), timeout=remaining))
        except asyncio.TimeoutError:
            break
    return batch


async def _flush(batch: list[tuple]) -> None:
    """Persist one batch: bulk COPY into metrics, upsert new devices, refresh cache."""
    async with db.pool().acquire() as conn:
        # 1) The bulk write. COPY is the fastest path into Postgres — one network
        #    round-trip and one transaction for the whole batch.
        await conn.copy_records_to_table(
            "metrics", records=batch,
            columns=["device_id", "ts", "power", "temperature"],
        )
        # 2) Register any devices we haven't seen. Done once per batch (on the
        #    distinct ids), not per row — keeps the hot path cheap.
        device_ids = {row[0] for row in batch}
        await conn.executemany(
            "INSERT INTO devices (device_id) VALUES ($1) ON CONFLICT DO NOTHING",
            [(d,) for d in device_ids],
        )

    # 3) Write-through cache: store each device's LATEST reading in the batch so
    #    /live and fleet summaries read from Dragonfly, never Postgres. We reduce
    #    to the newest-per-device within the batch first (fewer cache calls), then
    #    the CAS guards against out-of-order writes across batches/workers.
    latest: dict[str, tuple] = {}
    for device_id, ts, power, temp in batch:
        if device_id not in latest or ts > latest[device_id][1]:
            latest[device_id] = (device_id, ts, power, temp)
    for device_id, ts, power, temp in latest.values():
        await cache.set_latest_if_newer(device_id, power, temp, ts.isoformat(), ts.timestamp())


async def _batch_writer() -> None:
    """The background loop. One per process; drains the buffer forever."""
    while True:
        batch = await _collect_batch()
        try:
            await _flush(batch)
        except Exception:
            # Never let one bad batch kill the writer; log and continue.
            log.exception("batch flush failed (%d rows dropped)", len(batch))


def start() -> None:
    global _worker
    _worker = asyncio.create_task(_batch_writer())


async def stop() -> None:
    """On shutdown, drain whatever is still buffered, then cancel the loop."""
    if _worker is None:
        return
    while not _queue.empty():
        await _flush(await _collect_batch())
    _worker.cancel()


def depth() -> int:
    """Current buffer depth — handy for /health and the README's backpressure story."""
    return _queue.qsize()

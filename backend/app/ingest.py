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
# Set on shutdown. The writer is the queue's ONLY consumer, so it drains whatever
# is buffered and then exits once this is set — no second consumer racing it.
_stopping = asyncio.Event()


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
    """Wait for the first row (with a short timeout so the writer stays responsive
    to shutdown), then gather more until we hit batch_max_size OR
    batch_max_interval_ms — whichever comes first. Returns [] if nothing arrived."""
    try:
        first = await asyncio.wait_for(_queue.get(), timeout=0.5)
    except asyncio.TimeoutError:
        return []                                     # idle tick: lets the loop re-check _stopping
    batch = [first]
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


async def _write_db(batch: list[tuple]) -> None:
    """Persist one batch to Postgres atomically: the COPY and the device upsert
    commit together (or roll back together), so a failed flush leaves nothing
    half-written and is safe to retry without duplicating rows."""
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            # 1) The bulk write. COPY is the fastest path into Postgres — one
            #    network round-trip for the whole batch.
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


async def _update_cache(batch: list[tuple]) -> None:
    """Write-through cache: store each device's LATEST reading in the batch so
    /live and fleet summaries read from Dragonfly, never Postgres. We reduce to
    the newest-per-device within the batch first (fewer cache calls), then the CAS
    guards against out-of-order writes across batches/workers."""
    latest: dict[str, tuple] = {}
    for device_id, ts, power, temp in batch:
        if device_id not in latest or ts > latest[device_id][1]:
            latest[device_id] = (device_id, ts, power, temp)
    for device_id, ts, power, temp in latest.values():
        await cache.set_latest_if_newer(device_id, power, temp, ts.isoformat(), ts.timestamp())


async def _flush(batch: list[tuple]) -> None:
    """Persist one batch: durable DB write first, then refresh the cache."""
    await _write_db(batch)
    await _update_cache(batch)


async def _batch_writer() -> None:
    """The background loop. One per process; drains the buffer until shutdown.

    The DB write is retried with exponential backoff so a transient Postgres blip
    doesn't lose readings — while we retry, the queue backs up and the ingest
    endpoint sheds load (503) instead. Only a DB outage lasting past all retries
    drops a batch (the documented durability gap; Kafka would close it). The cache
    update is best-effort: the data is already durable and the cache self-heals on
    the next reading, so a cache blip must not fail the batch."""
    while not (_stopping.is_set() and _queue.empty()):
        batch = await _collect_batch()
        if not batch:
            continue
        delay = 0.1
        for attempt in range(1, settings.flush_max_retries + 1):
            try:
                await _write_db(batch)
                break
            except Exception:
                if attempt == settings.flush_max_retries:
                    log.exception("batch write failed after %d attempts (%d rows dropped)",
                                  attempt, len(batch))
                    batch = None
                    break
                log.warning("batch write failed (attempt %d/%d), retrying in %.1fs",
                            attempt, settings.flush_max_retries, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 2.0)
        if batch is None:
            continue
        try:
            await _update_cache(batch)
        except Exception:
            # Data is already persisted; the cache self-heals on the next reading.
            log.exception("cache update failed (DB persisted; cache will self-heal)")


def start() -> None:
    global _worker
    _stopping.clear()
    _worker = asyncio.create_task(_batch_writer())


async def stop() -> None:
    """On shutdown, signal the writer and wait for it. The writer is the queue's
    only consumer, so it drains everything still buffered and exits on its own —
    no second drain loop racing it for rows (which could otherwise hang forever)."""
    global _worker
    if _worker is None:
        return
    _stopping.set()
    await _worker
    _worker = None


def depth() -> int:
    """Current buffer depth — handy for /health and the README's backpressure story."""
    return _queue.qsize()

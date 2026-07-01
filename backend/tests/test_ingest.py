"""Batching logic + backpressure (unit) and flush/CAS (integration)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import cache, db, ingest
from app.config import settings
from app.models import MetricIn


def _row(device_id="d", power=1.0, temp=2.0):
    return (device_id, datetime.now(timezone.utc), power, temp)


# --- unit: batching + backpressure (no infra) -----------------------------

async def test_collect_batch_stops_at_size_limit(monkeypatch):
    q = asyncio.Queue()
    monkeypatch.setattr(ingest, "_queue", q)
    monkeypatch.setattr(settings, "batch_max_size", 3)
    for i in range(5):
        q.put_nowait(_row(f"d{i}"))
    batch = await ingest._collect_batch()
    assert len(batch) == 3  # capped at size, leftover stays in the queue
    assert q.qsize() == 2


async def test_collect_batch_stops_at_time_limit(monkeypatch):
    q = asyncio.Queue()
    monkeypatch.setattr(ingest, "_queue", q)
    monkeypatch.setattr(settings, "batch_max_size", 100)
    monkeypatch.setattr(settings, "batch_max_interval_ms", 50)
    q.put_nowait(_row())                       # only one row available
    batch = await ingest._collect_batch()      # returns after the interval, not blocking forever
    assert len(batch) == 1


async def test_enqueue_raises_when_buffer_full(monkeypatch):
    monkeypatch.setattr(ingest, "_queue", asyncio.Queue(maxsize=1))
    m = MetricIn(deviceId="d", power=1, temperature=2)
    ingest.enqueue(m)                          # fills the single slot
    with pytest.raises(ingest.QueueFull):
        ingest.enqueue(m)                      # backpressure


# --- integration: flush + CAS (real Timescale + Dragonfly) ----------------

async def test_flush_persists_registers_and_caches(infra):
    ts = datetime.now(timezone.utc)
    await ingest._flush([("rack-x", ts, 500.0, 70.0)])

    row = await db.pool().fetchrow(
        "SELECT power, temperature FROM metrics WHERE device_id='rack-x'")
    assert row["power"] == 500.0 and row["temperature"] == 70.0
    assert await db.pool().fetchval("SELECT 1 FROM devices WHERE device_id='rack-x'") == 1

    latest = await cache.get_latest("rack-x")
    assert latest["power"] == 500.0


async def test_cas_does_not_clobber_with_older_reading(infra):
    new = datetime.now(timezone.utc)
    old = new - timedelta(seconds=120)
    await cache.set_latest_if_newer("d", 600.0, 70.0, new.isoformat(), new.timestamp())
    await cache.set_latest_if_newer("d", 1.0, 1.0, old.isoformat(), old.timestamp())
    latest = await cache.get_latest("d")
    assert latest["power"] == 600.0  # the stale write was rejected

"""Postgres/TimescaleDB access: a shared asyncpg connection pool + the migration."""
import asyncpg

from .config import settings

# A pool reuses a handful of open connections instead of opening one per request.
# At high request rates, connection setup/teardown would itself become a bottleneck.
_pool: asyncpg.Pool | None = None


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db pool not initialised; call connect() first"
    return _pool


# Idempotent: safe to run on every startup. Each statement is guarded so a second
# run is a no-op (CREATE ... IF NOT EXISTS, if_not_exists => TRUE).
MIGRATION = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,                 -- natural key from the payload
    label       TEXT,
    location    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-device alert limits. Thresholds live in data, not code. NULL means
-- "use the fleet default" (resolved in the app), so this stays backwards-safe.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS power_limit REAL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS temp_limit  REAL;

-- Append-only time-series. No surrogate PK and no FK: both cost an extra write
-- per row on the hot path and buy us nothing here (we never look a row up by id,
-- and device integrity is enforced in the app via upsert-on-first-sight).
CREATE TABLE IF NOT EXISTS metrics (
    device_id   TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,             -- reading time, from the device
    power       REAL        NOT NULL,
    temperature REAL        NOT NULL
);

-- Turn metrics into a hypertable: Timescale auto-partitions it into time-based
-- "chunks" (one per day). Old data drops a whole chunk instantly; "last 60s"
-- queries only scan the newest chunk. This is the core scale lever for storage.
SELECT create_hypertable(
    'metrics', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- The single index that makes both hot reads cheap:
--   "last 60s for device X"     -> range scan
--   "latest reading for device X" -> first row of that scan
CREATE INDEX IF NOT EXISTS idx_metrics_device_ts ON metrics (device_id, ts DESC);
"""


async def run_migration() -> None:
    async with pool().acquire() as conn:
        await conn.execute(MIGRATION)


# --- query helpers ---------------------------------------------------------

async def upsert_device(device_id: str, label: str | None, location: str | None,
                        power_limit: float | None = None,
                        temp_limit: float | None = None) -> None:
    """Control-plane: create or update device metadata + optional per-device limits.
    Passing None for a limit keeps the existing value (COALESCE), so a metadata-only
    update never wipes a configured limit. Telemetry's auto-register uses DO NOTHING."""
    await pool().execute(
        """
        INSERT INTO devices (device_id, label, location, power_limit, temp_limit)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (device_id) DO UPDATE SET
            label       = EXCLUDED.label,
            location    = EXCLUDED.location,
            power_limit = COALESCE($4, devices.power_limit),
            temp_limit  = COALESCE($5, devices.temp_limit)
        """,
        device_id, label, location, power_limit, temp_limit,
    )


async def list_devices() -> list[dict]:
    """All known devices (the canonical roster). Small table; cheap to scan."""
    rows = await pool().fetch(
        "SELECT device_id, label, location, power_limit, temp_limit "
        "FROM devices ORDER BY device_id")
    return [dict(r) for r in rows]


async def metrics_window(device_id: str, seconds: int) -> list[dict]:
    """Readings for one device over the last `seconds`, oldest first.
    Hits only the newest hypertable chunk thanks to the (device_id, ts) index."""
    rows = await pool().fetch(
        """
        SELECT ts, power, temperature
        FROM metrics
        WHERE device_id = $1 AND ts >= now() - make_interval(secs => $2)
        ORDER BY ts
        """,
        device_id, seconds,
    )
    return [
        {"timestamp": r["ts"].isoformat(), "power": r["power"], "temperature": r["temperature"]}
        for r in rows
    ]

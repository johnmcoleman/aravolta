"""Dragonfly (Redis-compatible) client. Holds 'latest reading per device' for the
hot read paths (/live and fleet summaries) so they never touch Postgres."""
import json

import redis.asyncio as redis

from .config import settings

# One field per device in this hash: device_id -> JSON {power, temperature, ts}.
# A hash gives us HGET (one device, for /live) and HGETALL (whole fleet, for
# summaries) cheaply, instead of a key per device.
LATEST_HASH = "device:latest"
# Parallel hash: device_id -> epoch seconds of that reading. Used only for the
# compare-and-set below (kept separate so we don't parse JSON inside Lua).
LATEST_TS_HASH = "device:latest_ts"

# Atomic "write only if newer". Without this, two workers flushing out of order
# could overwrite a newer cached reading with an older one (the clobber bug).
# KEYS = [latest_hash, latest_ts_hash]; ARGV = [device_id, epoch, json_payload].
_CAS_LUA = """
local cur = redis.call('HGET', KEYS[2], ARGV[1])
if (cur == false) or (tonumber(ARGV[2]) > tonumber(cur)) then
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
  redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
  return 1
end
return 0
"""

_client: redis.Redis | None = None
_cas = None  # lazily-registered Lua script handle


async def connect() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.cache_url, decode_responses=True)
        await _client.ping()
    return _client


async def disconnect() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def client() -> redis.Redis:
    assert _client is not None, "cache not initialised; call connect() first"
    return _client


# --- write path (called by the batch writer) ------------------------------

async def set_latest_if_newer(device_id: str, power: float, temperature: float,
                              ts_iso: str, epoch: float) -> None:
    """Atomically update the cached latest reading, but only if `epoch` is newer
    than what's stored. Safe across multiple workers flushing out of order."""
    global _cas
    if _cas is None:
        _cas = client().register_script(_CAS_LUA)
    payload = json.dumps({"power": power, "temperature": temperature, "timestamp": ts_iso})
    await _cas(keys=[LATEST_HASH, LATEST_TS_HASH], args=[device_id, epoch, payload])


# --- read path (called by the query endpoints) ----------------------------

async def get_latest(device_id: str) -> dict | None:
    """Latest reading for one device, or None if it has never reported."""
    raw = await client().hget(LATEST_HASH, device_id)
    return json.loads(raw) if raw else None


async def get_all_latest() -> dict[str, dict]:
    """Latest reading for every device that has reported — for fleet views."""
    raw = await client().hgetall(LATEST_HASH)
    return {device_id: json.loads(v) for device_id, v in raw.items()}

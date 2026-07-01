"""Test fixtures. Point the app at an isolated test DB + cache BEFORE importing it,
so the suite never touches dev data.

Credentials are never hardcoded here: we load the same .env the app uses (real
environment variables still take precedence) and derive isolated test resources
from it — a separate `telemetry_test` database and cache DB index."""
import os

from dotenv import load_dotenv

# Load local .env (does not override vars already set in the real environment),
# then build Settings' env vars before app.config creates its singleton on import.
load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

TEST_DB = "telemetry_test"
_db_base, _ = os.environ["DATABASE_URL"].rsplit("/", 1)      # strip the db name
_cache_base, _ = os.environ["CACHE_URL"].rsplit("/", 1)       # strip the db index
os.environ["DATABASE_URL"] = f"{_db_base}/{TEST_DB}"          # isolated test DB
os.environ["CACHE_URL"] = f"{_cache_base}/1"                  # isolated cache index
ADMIN_DSN = f"{_db_base}/postgres"                            # for CREATE DATABASE

import asyncpg
import httpx
import pytest_asyncio

from app import cache, db, ingest  # noqa: E402
from app.main import app  # noqa: E402


async def _ensure_test_db() -> None:
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", TEST_DB):
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def infra():
    """Connect to the test DB + cache, migrate, and start each test from a clean slate."""
    await _ensure_test_db()
    await db.connect()
    await db.run_migration()
    await cache.connect()
    cache._cas = None  # re-register the Lua script against this test's fresh client
    async with db.pool().acquire() as c:
        await c.execute("TRUNCATE metrics; DELETE FROM devices;")
    await cache.client().flushdb()
    while not ingest._queue.empty():       # drain any leftover buffered rows
        ingest._queue.get_nowait()
    yield
    await cache.disconnect()
    await db.disconnect()


@pytest_asyncio.fixture
async def client(infra):
    """httpx client speaking to the ASGI app in-process (shares the connected pools)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

"""FastAPI app: wires up DB + cache on startup, runs the migration, exposes routes."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response, status

from . import cache, db, ingest
from .config import settings
from .models import DeviceIn, MetricIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open pools, ensure schema exists, start the batch writer.
    await db.connect()
    await db.run_migration()
    await cache.connect()
    ingest.start()
    yield
    # Shutdown: stop ingest first (it flushes via db+cache), then close pools.
    await ingest.stop()
    await cache.disconnect()
    await db.disconnect()


app = FastAPI(title="Aravolta Telemetry API", lifespan=lifespan)


@app.post("/api/metrics", status_code=status.HTTP_202_ACCEPTED)
async def post_metric(m: MetricIn, response: Response) -> dict:
    """Ingest one reading. Enqueues and returns immediately — never blocks on the DB.
    Returns 503 when the buffer is saturated (backpressure / load shedding)."""
    try:
        ingest.enqueue(m)
    except ingest.QueueFull:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "overloaded", "buffer_depth": ingest.depth()}
    return {"status": "accepted"}


def _enrich(device: dict, latest: dict | None, now: datetime) -> dict:
    """Merge a device row with its cached latest reading + computed status/alert.
    Alert limits are per-device (from the devices table), falling back to the
    fleet default when a device has none set."""
    pl, tl = device.get("power_limit"), device.get("temp_limit")
    power_limit = pl if pl is not None else settings.default_power_limit
    temp_limit = tl if tl is not None else settings.default_temp_limit
    online, alert, reasons = False, False, []
    if latest:
        ts = datetime.fromisoformat(latest["timestamp"])
        online = (now - ts).total_seconds() <= settings.online_window_seconds
        if latest["power"] > power_limit:
            alert, _ = True, reasons.append("power")
        if latest["temperature"] > temp_limit:
            alert, _ = True, reasons.append("temperature")
    return {
        "deviceId": device["device_id"],
        "label": device["label"],
        "location": device["location"],
        "powerLimit": power_limit,
        "tempLimit": temp_limit,
        "online": online,
        "alert": alert,
        "alertReasons": reasons,
        "latest": latest,
    }


@app.post("/api/devices", status_code=status.HTTP_201_CREATED)
async def register_device(d: DeviceIn) -> dict:
    """Control-plane: register or update a device's metadata + optional limits."""
    await db.upsert_device(d.device_id, d.label, d.location, d.power_limit, d.temp_limit)
    return {"status": "ok"}


async def _snapshot() -> list[dict]:
    """Full fleet enriched with latest reading + status. Server-side only — the
    O(N) merge cost stays in-datacenter; clients receive just a page or aggregate."""
    devices = await db.list_devices()
    latest_all = await cache.get_all_latest()
    now = datetime.now(timezone.utc)
    return [_enrich(d, latest_all.get(d["device_id"]), now) for d in devices]


def _apply_filters(items: list[dict], q: str | None = None,
                   zone: str | None = None, status: str | None = None) -> list[dict]:
    """Shared filter logic so /api/devices and /api/summary stay in sync."""
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["deviceId"].lower()
                 or ql in (i["label"] or "").lower()
                 or ql in (i["location"] or "").lower()]
    if zone:
        items = [i for i in items if i["location"] == zone]
    if status == "online":
        items = [i for i in items if i["online"]]
    elif status == "offline":
        items = [i for i in items if not i["online"]]
    elif status == "alert":
        items = [i for i in items if i["alert"]]
    return items


# Map the frontend's column fields to a sortable value. A missing latest reading
# sorts to the bottom (treated as -inf / empty string).
_SORT_KEYS = {
    "deviceId": lambda i: i["deviceId"],
    "location": lambda i: i["location"] or "",
    "alert": lambda i: i["alert"],
    "latest.power": lambda i: i["latest"]["power"] if i["latest"] else float("-inf"),
    "latest.temperature": lambda i: i["latest"]["temperature"] if i["latest"] else float("-inf"),
    "latest.timestamp": lambda i: i["latest"]["timestamp"] if i["latest"] else "",
}


@app.get("/api/devices")
async def get_devices(
    limit: int = 25, offset: int = 0,
    q: str | None = None, zone: str | None = None, status: str | None = None,
    sort: str = "deviceId", order: str = "asc",
) -> dict:
    """Paginated + filtered + sorted fleet roster, returned as {total, devices}.
    The client only ever holds one page, so this scales to very large fleets.
    Optional filters: ?q= (search id/label/zone), ?zone=, ?status=online|offline|alert."""
    items = _apply_filters(await _snapshot(), q, zone, status)
    items.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["deviceId"]), reverse=(order == "desc"))
    return {"total": len(items), "devices": items[offset:offset + limit]}


@app.get("/api/summary")
async def get_summary(q: str | None = None, zone: str | None = None) -> dict:
    """Fleet aggregates computed server-side. Scoped by the same q/zone filters as
    the table (NOT status — that's a drill-down within the scope, and scoping the
    'in alert' card by status would make it circular). The zones list stays global
    so the zone dropdown always offers every zone."""
    snapshot = await _snapshot()
    scoped = _apply_filters(snapshot, q=q, zone=zone)
    reporting = [i for i in scoped if i["latest"]]

    def avg(sel):
        return sum(sel(i) for i in reporting) / len(reporting) if reporting else None

    # Per-zone rollup for the heatmap — always over the whole (unscoped) fleet.
    zstats: dict[str, dict] = {}
    for i in snapshot:
        z = i["location"]
        if not z:
            continue
        s = zstats.setdefault(z, {"zone": z, "total": 0, "alerts": 0, "_tsum": 0.0, "_tn": 0})
        s["total"] += 1
        s["alerts"] += 1 if i["alert"] else 0
        if i["latest"]:
            s["_tsum"] += i["latest"]["temperature"]
            s["_tn"] += 1
    zone_stats = [
        {"zone": s["zone"], "total": s["total"], "alerts": s["alerts"],
         "avgTemperature": (s["_tsum"] / s["_tn"]) if s["_tn"] else None}
        for s in (zstats[z] for z in sorted(zstats))
    ]

    online = sum(1 for i in scoped if i["online"])
    return {
        "total": len(scoped),
        "online": online,
        "offline": len(scoped) - online,
        "alerts": sum(1 for i in scoped if i["alert"]),
        "avgPower": avg(lambda i: i["latest"]["power"]),
        "avgTemperature": avg(lambda i: i["latest"]["temperature"]),
        "zones": sorted({i["location"] for i in snapshot if i["location"]}),  # global
        "zoneStats": zone_stats,  # per-hall rollup for the heatmap (global)
    }


@app.get("/api/devices/{device_id}/live")
async def get_live(device_id: str) -> dict:
    """Latest reading for one device, served from cache. This is the polled path."""
    latest = await cache.get_latest(device_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="no readings for device")
    return latest


@app.get("/api/devices/{device_id}/metrics")
async def get_metrics(device_id: str, seconds: int = 60) -> list[dict]:
    """Time-window history for the chart. Defaults to the last 60 seconds."""
    return await db.metrics_window(device_id, seconds)


@app.get("/health")
async def health() -> dict:
    """Liveness probe: confirms both backing services answer."""
    db_ok = await db.pool().fetchval("SELECT 1") == 1
    cache_ok = await cache.client().ping()
    return {"status": "ok", "db": db_ok, "cache": cache_ok}

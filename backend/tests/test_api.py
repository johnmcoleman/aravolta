"""API contract: status codes, search/filter, alerting — over the real ASGI app."""
import asyncio
from datetime import datetime, timedelta, timezone

from app import db, ingest


async def test_post_metric_accepted(client):
    r = await client.post("/api/metrics", json={
        "deviceId": "d", "power": 1, "temperature": 2, "timestamp": "2026-06-30T20:00:00Z"})
    assert r.status_code == 202 and r.json()["status"] == "accepted"


async def test_post_metric_invalid_payload_422(client):
    r = await client.post("/api/metrics", json={"deviceId": "d", "temperature": 2})  # no power
    assert r.status_code == 422


async def test_live_unknown_device_404(client):
    r = await client.get("/api/devices/nope/live")
    assert r.status_code == 404


async def test_devices_list_filter_and_alert(client):
    await db.upsert_device("rack-a1", "Rack A1", "Hall A")
    await db.upsert_device("rack-hot", "Hot Unit", "Hall B")
    now = datetime.now(timezone.utc)
    await ingest._flush([("rack-a1", now, 500.0, 70.0),
                         ("rack-hot", now, 1200.0, 90.0)])

    page = (await client.get("/api/devices")).json()
    assert page["total"] == 2
    hot = next(d for d in page["devices"] if d["deviceId"] == "rack-hot")
    assert hot["alert"] is True and set(hot["alertReasons"]) == {"power", "temperature"}
    assert hot["label"] == "Hot Unit"

    alert = (await client.get("/api/devices", params={"status": "alert"})).json()
    assert [d["deviceId"] for d in alert["devices"]] == ["rack-hot"]

    found = (await client.get("/api/devices", params={"q": "a1"})).json()
    assert [d["deviceId"] for d in found["devices"]] == ["rack-a1"]

    zoned = (await client.get("/api/devices", params={"zone": "Hall B"})).json()
    assert [d["deviceId"] for d in zoned["devices"]] == ["rack-hot"]


async def test_devices_pagination_and_sort(client):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(5):
        await db.upsert_device(f"rack-{i}", f"L{i}", "Hall A")
        rows.append((f"rack-{i}", now, float(i * 100), 60.0))
    await ingest._flush(rows)

    p0 = (await client.get("/api/devices", params={"limit": 2, "offset": 0})).json()
    assert p0["total"] == 5 and len(p0["devices"]) == 2

    top = (await client.get("/api/devices",
           params={"sort": "latest.power", "order": "desc", "limit": 1})).json()
    assert top["devices"][0]["deviceId"] == "rack-4"  # highest power (400)


async def test_summary_aggregates(client):
    now = datetime.now(timezone.utc)
    await db.upsert_device("rack-a1", "A", "Hall A")
    await db.upsert_device("rack-hot", "H", "Hall B")
    await ingest._flush([("rack-a1", now, 400.0, 60.0),
                         ("rack-hot", now, 1200.0, 90.0)])

    s = (await client.get("/api/summary")).json()
    assert s["total"] == 2 and s["online"] == 2 and s["alerts"] == 1
    assert s["avgPower"] == 800.0  # (400 + 1200) / 2
    assert set(s["zones"]) == {"Hall A", "Hall B"}
    zmap = {z["zone"]: z for z in s["zoneStats"]}
    assert zmap["Hall B"]["alerts"] == 1 and zmap["Hall A"]["alerts"] == 0  # per-hall rollup


async def test_summary_scoped_by_zone(client):
    now = datetime.now(timezone.utc)
    await db.upsert_device("r1", "L1", "Hall A")
    await db.upsert_device("r2", "L2", "Hall A")
    await db.upsert_device("r3", "L3", "Hall B")
    await ingest._flush([("r1", now, 100.0, 60.0),
                         ("r2", now, 300.0, 60.0),
                         ("r3", now, 999.0, 60.0)])

    s = (await client.get("/api/summary", params={"zone": "Hall A"})).json()
    assert s["total"] == 2          # only Hall A racks counted
    assert s["avgPower"] == 200.0   # (100 + 300) / 2 — Hall B's r3 excluded
    assert set(s["zones"]) == {"Hall A", "Hall B"}  # zones list stays global


async def test_per_device_limits_override_default(client):
    # A rack with a raised power/temp limit must NOT alert at values that would
    # trip the fleet default (1000 W / 85 °C).
    await client.post("/api/devices", json={
        "deviceId": "gpu", "label": "GPU", "location": "Hall A",
        "powerLimit": 1400, "tempLimit": 95})
    await ingest._flush([("gpu", datetime.now(timezone.utc), 1050.0, 88.0)])

    d = (await client.get("/api/devices", params={"q": "gpu"})).json()["devices"][0]
    assert d["powerLimit"] == 1400 and d["tempLimit"] == 95
    assert d["alert"] is False  # 1050 < 1400 and 88 < 95 -> in spec for THIS rack


async def test_live_and_metrics_window(client):
    now = datetime.now(timezone.utc)
    await ingest._flush([("rack-a1", now - timedelta(seconds=10), 500.0, 70.0),
                         ("rack-a1", now, 510.0, 71.0)])

    live = (await client.get("/api/devices/rack-a1/live")).json()
    assert live["power"] == 510.0  # newest

    pts = (await client.get("/api/devices/rack-a1/metrics", params={"seconds": 60})).json()
    assert len(pts) == 2 and pts[0]["timestamp"] < pts[1]["timestamp"]  # oldest first


async def test_backpressure_returns_503(client, monkeypatch):
    monkeypatch.setattr(ingest, "_queue", asyncio.Queue(maxsize=1))
    ingest._queue.put_nowait(("x", datetime.now(timezone.utc), 1.0, 2.0))  # saturate
    r = await client.post("/api/metrics", json={"deviceId": "d", "power": 1, "temperature": 2})
    assert r.status_code == 503 and r.json()["status"] == "overloaded"

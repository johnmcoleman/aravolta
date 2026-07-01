"""Telemetry simulator for a single data center of ~1,000 racks.

Each rack runs on its own phased clock (not a synchronized burst), so aggregate
ingest load is smooth: ~count/period writes/s. Racks random-walk around a
baseline with occasional sustained alert episodes.

Run the API first, then:  python simulator.py --count 1000 --period 8
"""
import argparse
import asyncio
import random
from datetime import datetime, timezone

import httpx

# Intra-DC topology: racks are grouped by hall (the "location"/zone dimension).
ZONES = ["Hall A", "Hall B", "Hall C", "Hall D", "Hall E", "Hall F"]
ROLES = ["Compute", "GPU", "Storage", "Network", "Inference", "DB"]

# Per-role alert limits (power W, temp °C). Different hardware has different
# power/thermal envelopes — GPUs tolerate more than storage. All limits sit above
# the normal operating band (<=900 W / <=82 °C) so only real spikes alert.
ROLE_LIMITS = {
    "Compute": (1000, 85),
    "GPU": (1300, 92),
    "Storage": (1000, 84),
    "Network": (950, 84),
    "Inference": (1150, 88),
    "DB": (1050, 86),
}


def build_fleet(count: int) -> list[tuple[str, str, str, int, int]]:
    """(device_id, label, zone, power_limit, temp_limit) for `count` racks. Role and
    zone are decorrelated so zone-filter and role-search are independent dimensions."""
    fleet = []
    for i in range(1, count + 1):
        role = ROLES[i % len(ROLES)]
        zone = ZONES[(i // 4) % len(ZONES)]
        plim, tlim = ROLE_LIMITS[role]
        fleet.append((f"rack-{i:04d}", f"{role}-{i:03d}", zone, plim, tlim))
    return fleet


async def seed(client: httpx.AsyncClient, base: str, fleet) -> None:
    # Register metadata concurrently in chunks so 1,000 racks seed in ~a second.
    sem = asyncio.Semaphore(50)

    async def one(dev):
        async with sem:
            await client.post(f"{base}/api/devices", json={
                "deviceId": dev[0], "label": dev[1], "location": dev[2],
                "powerLimit": dev[3], "tempLimit": dev[4]})

    await asyncio.gather(*(one(d) for d in fleet))
    print(f"seeded {len(fleet)} racks")


async def rack_task(client: httpx.AsyncClient, base: str, dev, period: float) -> None:
    """One rack: emit a reading every `period`s, phased by a random initial offset."""
    device_id, plim, tlim = dev[0], dev[3], dev[4]
    power = random.uniform(450, 700)
    temp = random.uniform(60, 72)
    hot = 0  # ticks remaining in an alert episode
    await asyncio.sleep(random.random() * period)  # spread load across the period
    while True:
        power = min(900, max(200, power + random.uniform(-20, 20)))
        temp = min(82, max(55, temp + random.uniform(-0.6, 0.6)))
        p, t = power, temp
        if hot == 0 and random.random() < 0.01:
            hot = random.randint(6, 12)      # start a sustained overheat episode
        if hot > 0:
            hot -= 1
            p = plim * random.uniform(1.05, 1.25)   # exceed THIS rack's own limits
            t = tlim + random.uniform(3, 10)
        try:
            await client.post(f"{base}/api/metrics", json={
                "deviceId": device_id, "power": round(p, 1),
                "temperature": round(t, 1), "timestamp": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass  # a transient 503/backpressure just drops this tick; next one retries
        await asyncio.sleep(period)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--count", type=int, default=1000, help="number of racks")
    ap.add_argument("--period", type=float, default=8.0, help="seconds between each rack's readings")
    args = ap.parse_args()

    fleet = build_fleet(args.count)
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
    async with httpx.AsyncClient(timeout=5.0, limits=limits) as client:
        await seed(client, args.base, fleet)
        rate = args.count / args.period
        print(f"streaming ~{rate:.0f} readings/s ({args.count} racks / {args.period}s) — Ctrl-C to stop")
        await asyncio.gather(*(rack_task(client, args.base, d, args.period) for d in fleet))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")

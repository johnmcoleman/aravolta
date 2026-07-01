"""Ingestion load test. Two modes:

  http : hammer POST /api/metrics at high concurrency; report throughput,
         latency percentiles, and 503 (backpressure) counts.
  db   : bypass HTTP and COPY batches straight into Timescale, to find the
         raw single-node write ceiling independent of the API layer.

Run the API + containers first, and stop the simulator so it doesn't skew numbers.
  python loadtest.py http --concurrency 200 --duration 10
  python loadtest.py db   --duration 10 --batch 1000 --conns 4
"""
import argparse
import asyncio
import time
from datetime import datetime, timezone

import httpx


async def _http_worker(client, base, stop_at, stats, idx):
    while time.monotonic() < stop_at:
        body = {"deviceId": f"load-{idx}", "power": 500, "temperature": 70,
                "timestamp": datetime.now(timezone.utc).isoformat()}
        t0 = time.monotonic()
        try:
            r = await client.post(f"{base}/api/metrics", json=body)
            stats["lat"].append(time.monotonic() - t0)
            stats[r.status_code] = stats.get(r.status_code, 0) + 1
        except Exception:
            stats["exc"] += 1


async def run_http(args):
    stats = {"lat": [], "exc": 0}
    limits = httpx.Limits(max_connections=args.concurrency,
                          max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(limits=limits, timeout=10) as client:
        start = time.monotonic()
        await asyncio.gather(*[
            _http_worker(client, args.base, start + args.duration, stats, i)
            for i in range(args.concurrency)
        ])
        elapsed = time.monotonic() - start

    lat = sorted(stats["lat"])
    pct = lambda p: (lat[min(len(lat) - 1, int(len(lat) * p))] * 1000) if lat else 0
    accepted, shed = stats.get(202, 0), stats.get(503, 0)
    total = accepted + shed + stats["exc"]
    print(f"\nHTTP  concurrency={args.concurrency}  duration={elapsed:.1f}s")
    print(f"  requests:      {total}  ({total / elapsed:,.0f}/s)")
    print(f"  202 accepted:  {accepted}  ({accepted / elapsed:,.0f}/s)")
    print(f"  503 shed:      {shed}")
    print(f"  exceptions:    {stats['exc']}")
    print(f"  latency ms:    p50={pct(.5):.1f}  p95={pct(.95):.1f}  p99={pct(.99):.1f}")


async def _db_worker(stop_at, batch, counter, idx):
    from app import db
    while time.monotonic() < stop_at:
        now = datetime.now(timezone.utc)
        records = [(f"db-{idx}-{j % 50}", now, 500.0, 70.0) for j in range(batch)]
        async with db.pool().acquire() as c:
            await c.copy_records_to_table(
                "metrics", records=records,
                columns=["device_id", "ts", "power", "temperature"])
        counter[0] += batch


async def run_db(args):
    from app import db
    await db.connect()
    counter = [0]
    start = time.monotonic()
    await asyncio.gather(*[
        _db_worker(start + args.duration, args.batch, counter, i)
        for i in range(args.conns)
    ])
    elapsed = time.monotonic() - start
    await db.disconnect()
    print(f"\nDB COPY  conns={args.conns}  batch={args.batch}  duration={elapsed:.1f}s")
    print(f"  rows written:  {counter[0]:,}  ({counter[0] / elapsed:,.0f} rows/s)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    h = sub.add_parser("http")
    h.add_argument("--base", default="http://127.0.0.1:8000")
    h.add_argument("--concurrency", type=int, default=200)
    h.add_argument("--duration", type=float, default=10)
    d = sub.add_parser("db")
    d.add_argument("--duration", type=float, default=10)
    d.add_argument("--batch", type=int, default=1000)
    d.add_argument("--conns", type=int, default=4)
    args = ap.parse_args()
    asyncio.run(run_http(args) if args.mode == "http" else run_db(args))


if __name__ == "__main__":
    main()

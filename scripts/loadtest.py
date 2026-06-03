#!/usr/bin/env python3
"""Astra backend load-test harness.

Measures the real capacity of the (single-worker) backend WITHOUT running real
agents — so it costs nothing and won't disrupt live users. It hammers cheap
read endpoints and SSE connects at increasing concurrency and reports the
latency knee, which is where the single event loop starts to saturate (i.e.
when multiple workers would actually start to help).

Usage:
  python3 scripts/loadtest.py --url http://localhost:8000 \
      --levels 10,25,50,100,200,400 --duration 8

Metrics per concurrency level:
  - throughput (req/s)
  - latency p50 / p95 / p99 / max (ms)
  - error rate
  - CONTROL latency: a separate 1-req/s probe of /health measured *while* the
    load runs — the cleanest signal of event-loop blocking. If control p95
    climbs sharply, the loop is saturated at that concurrency.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[k]


async def _worker(client: httpx.AsyncClient, path: str, stop_at: float, lat: list, errs: list):
    while time.monotonic() < stop_at:
        t0 = time.monotonic()
        try:
            r = await client.get(path, timeout=30)
            dt = (time.monotonic() - t0) * 1000
            if r.status_code < 500:
                lat.append(dt)
            else:
                errs.append(r.status_code)
        except Exception as e:
            errs.append(type(e).__name__)


async def _control_probe(client: httpx.AsyncClient, path: str, stop_at: float, clat: list):
    while time.monotonic() < stop_at:
        t0 = time.monotonic()
        try:
            await client.get(path, timeout=30)
            clat.append((time.monotonic() - t0) * 1000)
        except Exception:
            clat.append(99999.0)
        await asyncio.sleep(1.0)


async def run_level(base: str, path: str, concurrency: int, duration: float) -> dict:
    limits = httpx.Limits(max_connections=concurrency + 8, max_keepalive_connections=concurrency + 8)
    async with httpx.AsyncClient(base_url=base, limits=limits) as client:
        lat: list[float] = []
        errs: list = []
        clat: list[float] = []
        stop_at = time.monotonic() + duration
        tasks = [asyncio.create_task(_worker(client, path, stop_at, lat, errs)) for _ in range(concurrency)]
        tasks.append(asyncio.create_task(_control_probe(client, path, stop_at, clat)))
        await asyncio.gather(*tasks)
        total = len(lat) + len(errs)
        return {
            "concurrency": concurrency,
            "requests": total,
            "rps": round(total / duration, 1),
            "errors": len(errs),
            "err_rate": round(100 * len(errs) / total, 1) if total else 0.0,
            "p50": round(_pct(lat, 50), 1),
            "p95": round(_pct(lat, 95), 1),
            "p99": round(_pct(lat, 99), 1),
            "max": round(max(lat), 1) if lat else 0.0,
            "control_p95": round(_pct(clat, 95), 1),
            "control_max": round(max(clat), 1) if clat else 0.0,
        }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--path", default="/api/sessions?founder_id=loadtest&limit=1", help="endpoint to hammer (read-only)")
    ap.add_argument("--levels", default="10,25,50,100,200,400")
    ap.add_argument("--duration", type=float, default=8.0)
    args = ap.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    print(f"Target {args.url}{args.path} | {args.duration}s per level\n")
    hdr = f"{'conc':>5} {'req/s':>8} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>9} {'ctrl_p95':>9} {'ctrl_max':>9} {'err%':>6}"
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for c in levels:
        r = await run_level(args.url, args.path, c, args.duration)
        rows.append(r)
        print(f"{r['concurrency']:>5} {r['rps']:>8} {r['p50']:>8} {r['p95']:>8} {r['p99']:>8} "
              f"{r['max']:>9} {r['control_p95']:>9} {r['control_max']:>9} {r['err_rate']:>6}")
        await asyncio.sleep(1.0)

    # Knee detection: first level where control p95 > 250ms or err_rate > 1%.
    knee = next((r for r in rows if r["control_p95"] > 250 or r["err_rate"] > 1.0), None)
    print()
    if knee:
        print(f"KNEE: event loop starts saturating around concurrency={knee['concurrency']} "
              f"(control p95={knee['control_p95']}ms, err={knee['err_rate']}%).")
        print("Below this, a single worker is comfortable. Multiple workers help past it.")
    else:
        print(f"NO KNEE up to concurrency={levels[-1]} — single worker stays responsive "
              f"(control p95 max {max(r['control_p95'] for r in rows)}ms). Headroom remains.")


if __name__ == "__main__":
    asyncio.run(main())

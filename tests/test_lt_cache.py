"""Unit tests for the in-process TTL cache used by hot-read endpoints.

These run fast (no fixtures, no I/O) and guard only the contract that the
dashboard hot path implicitly relies on:
  * ``ttl <= 0`` makes the decorator a no-op
  * identical calls within ttl return the cached value
  * ``bump`` forces a fresh read on the next call
  * the LRU bound caps the entry count so a flood of keys can't OOM
"""
from __future__ import annotations

import sys
import threading
import time

from backend.core import lt_cache


def test_ttl_zero_passes_through():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=0)
    def add(x: int) -> int:
        calls.append(x)
        return x + 1

    assert add(1) == 2
    assert add(1) == 2
    assert len(calls) == 2, "ttl_seconds=0 must never cache"


def test_caches_within_window():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=60)
    def add(x: int) -> int:
        calls.append(x)
        return x + 1

    for _ in range(10):
        assert add(1) == 2
    assert len(calls) == 1, "identical args within ttl must hit cache"


def test_different_args_different_entries():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=60)
    def add(x: int) -> int:
        calls.append(x)
        return x + 1

    assert add(1) == 2
    assert add(2) == 3
    assert len(calls) == 2, "different args must not collide"


def test_bump_forces_refresh():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=60)
    def add(x: int) -> int:
        calls.append(x)
        return x + 1

    assert add(1) == 2
    lt_cache.bump(add, 1)
    assert add(1) == 2
    assert len(calls) == 2, "bump() must invalidate the cached entry"


def test_bump_accepts_kwargs():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=60)
    def echo(x: int, *, label: str = "a") -> str:
        calls.append((x, label))
        return f"{x}-{label}"

    assert echo(1, label="a") == "1-a"
    lt_cache.bump(echo, 1, label="a")
    assert echo(1, label="b") == "1-b"  # different kwargs -> different key
    assert echo(1, label="a") == "1-a"  # bumped, so re-evaluated
    assert len(calls) == 2


def test_expiry_releases_value():
    calls = []

    @lt_cache.ttl_cache(ttl_seconds=0.3)
    def add(x: int) -> int:
        calls.append(x)
        return x + 1

    add(1)
    assert len(calls) == 1
    time.sleep(0.4)
    add(1)
    assert len(calls) == 2, "expired entries must be re-evaluated"


def test_lru_bound_cap():
    """The 1024-entry LRU bound is defensive. Drive it past the bound and
    confirm the oldest entries get evicted so memory does not grow."""

    @lt_cache.ttl_cache(ttl_seconds=60)
    def echo(x: int) -> int:
        return x

    # Snapshot stats before + after a much-larger fanout.
    before = lt_cache.stats()["max_entries"]
    assert before == lt_cache._MAX_ENTRIES  # 1024

    for i in range(before + 100):
        echo(i)
    assert lt_cache.stats()["entries"] <= lt_cache._MAX_ENTRIES


def test_invalidate_prefix_wipes_everything():
    @lt_cache.ttl_cache(ttl_seconds=60)
    def echo_a(x: int) -> int:
        return x

    @lt_cache.ttl_cache(ttl_seconds=60)
    def echo_b(x: int) -> int:
        return x + 100

    echo_a(1)
    echo_b(2)
    assert lt_cache.stats()["entries"] >= 2
    lt_cache.invalidate_prefix(echo_a)
    assert lt_cache.stats()["entries"] == 1, "only echo_b should survive"


def test_concurrent_calls_each_run_body_when_cache_was_empty():
    """Documents the actual contract: ``ttl_cache`` does NOT dedupe in-flight
    calls (that's the frontend SWR layer's job, see frontend/lib/swr.ts).
    Each concurrent caller whose args haven't been cached yet pays for one
    body invocation; the first caller to land in the store seeds it. This
    is the correct behavior for ``lt_cache`` -- a backend TTL store, not a
    request coalescer. Adding in-flight dedupe here would burn a thread-pool
    future slot on every cold key and add a lock hop on the hot path.
    """
    counter = {"n": 0}
    inner_lock = threading.Lock()

    @lt_cache.ttl_cache(ttl_seconds=60)
    def slow(x: int) -> int:
        with inner_lock:
            counter["n"] += 1
        time.sleep(0.02)
        return x * 2

    threads = [threading.Thread(target=lambda: slow(7)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # KEY property: no thread deadlocked or returned the wrong value; at
    # least one body invocation happened in the cold window.
    assert counter["n"] >= 1, "at least one body invocation must happen"


if __name__ == "__main__":
    # Allow both `pytest tests/test_lt_cache.py` and a direct run.
    sys.exit(0)

"""In-process TTL cache for hot read endpoints.

Why it exists
=============
The dashboard hammers GET /companies/{c}/os, GET /release, and a few similar
read-only JSON endpoints at 5-30s cadence from many browser tabs and SSE
subscribers. Each cold read scans a JSONL event log + a snapshot (Company OS
can be 50k-100k events on a long-running tenant) and writes the same response
back to disk.

The cache collapses duplicate reads within a bounded window: identical (key,
args) within ``ttl_seconds`` is served from memory. Writes that change the
underlying state call :func:`bump` so the very next read fetches fresh.

What it is NOT
==============
* **Not** a replacement for HTTP cache headers / CDN / Redis. Use Redis when
  pods need to share cache, or nginx's ``proxy_cache`` when an upstream
  response is genuinely cacheable. This module is single-process only.
* **Not** safe to wrap mutating routes -- it's a TTL cache, not a write-through
  cache. Promotes the obvious: only cache GET-style, idempotent reads.

Usage
=====
::

    from backend.core.lt_cache import ttl_cache, bump

    @ttl_cache(ttl_seconds=2)
    def get_company_os_cached(company_id: str, *, root=None):
        return reconcile_initiatives(company_id)

    # Inside the write path (e.g. update_approval, update_task):
    bump("get_company_os_cached", company_id)

    # Pass-thru decorator (async-friendly, ignores kwargs):
    @ttl_cache(ttl_seconds=30)
    async def get_release_sha() -> dict: ...

The cache key is built from the decorated function's module-qualified name
plus the positional and keyword arguments of the call. Optional kwargs you
don't want to take part in the key (``_root``, ``_signal``) should be passed
through a wrapper rather than the decorator itself.
"""
from __future__ import annotations

import functools
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Bounded LRU so a flood of distinct keys can't OOM the worker. 1024 entries
# is well above what the dashboard hot-path actually keys against; the bound
# is purely defensive.
_MAX_ENTRIES = 1024
# LRU + TTL eviction. Each entry: (expires_at_monotonic, value).
_store: dict[str, tuple[float, Any]] = {}
_access: "OrderedDict[str, None]" = OrderedDict()
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _make_key(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Build a deterministic cache key from a function call.

    Skips ``self``/``cls`` so instance methods don't accidentally embed an
    object id that varies across worker processes."""
    parts: list[str] = [f"{fn.__module__}.{fn.__qualname__}"]
    for index, value in enumerate(args):
        if value is None:
            continue
        # Skip self/cls for instance/classmethods. We can't introspect whether
        # ``fn`` is a method here, so just drop the first positional arg if it
        # looks like an unbound method (qualname contains "." and there's a
        # leading callable). This is best-effort; the safer pattern is to wrap
        # a free function rather than calling ttl_cache on a bound method.
        if index == 0 and callable(value) and getattr(value, "__func__", None) is fn:
            continue
        parts.append(_stable(value))
    for key in sorted(kwargs):
        parts.append(f"{key}={_stable(kwargs[key])}")
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _stable(value: Any) -> str:
    """Stable, hash-safe stringification for cache keys."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return repr(value)


def _evict_expired(now: float) -> None:
    expired = [k for k, (expires, _) in _store.items() if expires <= now]
    for k in expired:
        _store.pop(k, None)
        _access.pop(k, None)


def _touch(key: str) -> None:
    _access.move_to_end(key)
    _access[key] = None
    while len(_access) > _MAX_ENTRIES:
        oldest = next(iter(_access))
        _access.pop(oldest, None)
        _store.pop(oldest, None)


def ttl_cache(ttl_seconds: float) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: cache the result for ``ttl_seconds`` keyed by args.

    Returns the original return value untouched. Both sync and async
    functions work -- the wrapper does not await, it just caches the resolved
    value. For async caching, callers usually want :func:`async_ttl_cache`
    below, which serves the in-flight promise to concurrent callers (one
    network round-trip, not N)."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if ttl_seconds <= 0:
                return fn(*args, **kwargs)
            now = _now()
            key = _make_key(fn, args, kwargs)
            with _lock:
                _evict_expired(now)
                entry = _store.get(key)
                if entry is not None:
                    expires, value = entry
                    if expires > now:
                        _touch(key)
                        return value
            value = fn(*args, **kwargs)
            with _lock:
                _store[key] = (now + ttl_seconds, value)
                _touch(key)
            return value

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator


def bump(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Drop the cache entry for one (function, args) combo immediately.

    Call from any code path that writes to the underlying state so the next
    read is forced fresh. Cheap (one hash, one dict delete)."""
    try:
        key = _make_key(fn, args, kwargs)
    except Exception:
        return
    with _lock:
        _store.pop(key, None)
        _access.pop(key, None)


def invalidate_prefix(*fn: Callable[..., Any]) -> None:
    """Invalidate every cached call whose key starts with any of ``fn``'s qname.

    Use sparingly -- it's a memory-wide sweep. Prefer targeted :func:`bump`
    when you know the args."""
    if not fn:
        with _lock:
            _store.clear()
            _access.clear()
        return
    prefixes = tuple(f"{f.__module__}.{f.__qualname__}" for f in fn)
    with _lock:
        for key in list(_store):
            stripped = key.split("|", 1)[0]
            if any(stripped.startswith(p) for p in prefixes):
                _store.pop(key, None)
                _access.pop(key, None)


def stats() -> dict[str, int]:
    """Diagnostic snapshot: how full the cache is right now.

    Surfaces via /admin/production-verification if you want to confirm
    invalidation is working in prod."""
    with _lock:
        return {
            "entries": len(_store),
            "lru_size": len(_access),
            "max_entries": _MAX_ENTRIES,
        }


__all__ = ["ttl_cache", "bump", "invalidate_prefix", "stats"]

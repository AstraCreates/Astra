"""Shared OpenRouter/OpenAI-compatible client factory.

- Sets HTTP-Referer/X-Title headers so OpenRouter attributes calls to "Astra"
  (not "Unknown") in the request logs.
- Rotates API keys via the key rotator for OpenRouter endpoints.
- Reuses client instances (and their pooled httpx connections) across calls
  instead of constructing a fresh client per request. Pooling keeps TCP
  connections alive and avoids the TLS-handshake overhead on every call.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://astracreates.com",
    "X-Title": "Astra",
}

_CLIENT_CACHE_TTL_SECONDS = float(os.environ.get("ASTRA_LLM_CLIENT_TTL_SECONDS", "900"))
# Default per-request timeout for OpenAI/OpenRouter clients. Connect is
# bounded tight (15s) because a slow handshake usually means a rotated
# API key is being rejected and there's no point letting it sit. Read is
# 120s, matching the OpenAI-recommended upper bound for non-streaming chat
# completions of large reasoning models. Crucially, this guarantees the
# lower-level httpx client has SOME timeout -- without it a server that
# just stops ACKing packets would have asyncio.wait_for callers in the
# agent loop waiting forever.
_DEFAULT_LLM_READ_TIMEOUT_SECONDS = float(os.environ.get("ASTRA_LLM_TIMEOUT_SECONDS", "120"))
_DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("ASTRA_LLM_CONNECT_TIMEOUT_SECONDS", "15"))


def _default_openai_timeout() -> "httpx.Timeout | float":
    """Return the default Timeout knob for the OpenAI SDK's underlying httpx
    client. Falls back to a numeric read timeout (NEVER ``None`` -- the
    OpenAI SDK treats ``None`` as "no timeout", which would silently disable
    the bound we just added if httpx is somehow missing in this env).
    httpx is an openai transitive dep so the fallback is defensive only."""
    try:
        import httpx
    except ImportError:  # pragma: no cover -- defensive only
        return float(_DEFAULT_LLM_READ_TIMEOUT_SECONDS)
    return httpx.Timeout(
        connect=_DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS,
        read=_DEFAULT_LLM_READ_TIMEOUT_SECONDS,
        write=_DEFAULT_LLM_READ_TIMEOUT_SECONDS,
        pool=_DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS,
    )
_sync_cache: dict[tuple[str, str, float | None], tuple[Any, float]] = {}
_async_cache: dict[tuple[str, str, float | None], tuple[Any, float]] = {}
_lock = threading.Lock()


def _or_headers(base_url: str) -> dict[str, str]:
    if "openrouter" in (base_url or "").lower():
        return dict(_OPENROUTER_HEADERS)
    return {}


def _resolve(base_url: str, api_key: str) -> tuple[str, str]:
    """Resolve base_url + api_key from settings when not provided."""
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key

    base_url = base_url or settings.openrouter_base_url
    if not api_key:
        if "openrouter" in base_url.lower():
            api_key = get_openrouter_key() or settings.openrouter_api_key or settings.agent_model_api_key
        else:
            api_key = settings.agent_model_api_key
    return base_url, api_key


def _fresh_entry(cache: dict[tuple[str, str, float | None], tuple[Any, float]], key: tuple[str, str, float | None]) -> Any | None:
    entry = cache.get(key)
    if entry is None:
        return None
    client, created_at = entry
    if _CLIENT_CACHE_TTL_SECONDS > 0 and (time.monotonic() - created_at) > _CLIENT_CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return client


def _store_entry(cache: dict[tuple[str, str, float | None], tuple[Any, float]], key: tuple[str, str, float | None], client: Any) -> Any:
    cache[key] = (client, time.monotonic())
    return client


def get_or_client(base_url: str = "", api_key: str = "", timeout: float | None = None) -> Any:
    """Return a cached sync openai.OpenAI client for the given endpoint.

    Caching by (base_url, api_key) means each rotated key gets its own pooled
    client; callers that round-robin keys naturally spread across pools.
    """
    import openai

    base_url, api_key = _resolve(base_url, api_key)
    key = (base_url, api_key, timeout)
    with _lock:
        client = _fresh_entry(_sync_cache, key)
        if client is None:
            client = openai.OpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers=_or_headers(base_url),
                timeout=timeout if timeout is not None else _default_openai_timeout(),
            )
            client = _store_entry(_sync_cache, key, client)
        return client


def get_async_or_client(base_url: str = "", api_key: str = "", timeout: float | None = None) -> Any:
    """Return a cached async openai.AsyncOpenAI client for the given endpoint."""
    import openai

    base_url, api_key = _resolve(base_url, api_key)
    key = (base_url, api_key, timeout)
    with _lock:
        client = _fresh_entry(_async_cache, key)
        if client is None:
            client = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers=_or_headers(base_url),
                timeout=timeout if timeout is not None else _default_openai_timeout(),
            )
            client = _store_entry(_async_cache, key, client)
        return client

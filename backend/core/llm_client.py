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
                timeout=timeout,
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
                timeout=timeout,
            )
            client = _store_entry(_async_cache, key, client)
        return client

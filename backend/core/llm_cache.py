"""Helpers for provider-side prompt caching on OpenRouter-compatible chat calls."""
from __future__ import annotations

from typing import Any


def is_openrouter_base_url(base_url: str | None) -> bool:
    return "openrouter" in (base_url or "").lower()


def cacheable_messages(messages: list[dict[str, Any]], breakpoints: tuple[int, ...] = (0, 1)) -> list[dict[str, Any]]:
    """Mark stable text messages as cacheable without mutating the caller's list."""
    cached = list(messages)
    for idx in breakpoints:
        if idx >= len(cached):
            continue
        msg = cached[idx]
        content = msg.get("content")
        if isinstance(content, str):
            cached[idx] = {
                **msg,
                "content": [{
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }],
            }
    return cached


def openrouter_extra_body(model: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    body = dict(extra or {})
    if "hy3" in model and "reasoning" not in body:
        body["reasoning"] = {"effort": "none"}
    # Provider routing — the real fix for the agent crashes. OpenRouter was load-
    # balancing across providers, some of which 429'd (GMICloud) or returned a
    # malformed body / rejected json mode (SiliconFlow → "Json mode is not
    # supported"), which surfaced as 'NoneType object is not subscriptable'.
    #   require_parameters: only route to providers that support the request params
    #                       (e.g. response_format/json mode) → no more 400s.
    #   allow_fallbacks:    transparently retry the next provider on error/rate-limit
    #                       instead of handing back a broken response.
    body.setdefault("provider", {
        "require_parameters": True,
        "allow_fallbacks": True,
    })
    return body or None

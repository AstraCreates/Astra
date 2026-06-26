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
    # Disable chain-of-thought reasoning tokens for our reasoning models — agents do
    # their own JSON-structured reasoning, so the trace just burns tokens/latency
    # (mimo/hy3 were spending most of each call generating reasoning → slow agents).
    _m = (model or "").lower()
    if "deepseek-v4-flash" in _m and "reasoning" not in body:
        # Bench v11 #3: max effort raises P_hard; cost unchanged (same output rate).
        body["reasoning"] = {"effort": "max"}
    elif ("hy3" in _m or "qwen" in _m or "deepseek" in _m) and "thinking" not in _m and "reasoning" not in body:
        # Non-thinking Qwen/DeepSeek/HY3: suppress CoT to prevent token-budget exhaustion.
        # Exempt: qwen3-235b-a22b-thinking-2507 (bench v11 #2) and any -thinking suffixed model.
        # MiMo omitted: bench v11 #1 with thinking on; suppression would degrade prod to bench mismatch.
        body["reasoning"] = {"effort": "none"}
    # Provider routing: allow_fallbacks lets OpenRouter transparently retry the next
    # provider on error/rate-limit instead of returning a broken body. We do NOT set
    # require_parameters — it forces provider filtering that makes every call ~3x
    # slower, and it's unnecessary now that we no longer send json-mode response_format
    # (which is what some providers rejected).
    body.setdefault("provider", {"allow_fallbacks": True})
    # Usage accounting: OpenRouter only populates usage.prompt_tokens_details.cached_tokens
    # (and cost) when accounting is requested. Without this, prompt-cache HITS report 0
    # cached tokens, so we'd both lose the cache savings AND bill cached tokens at the full
    # input rate. Required for caching to be reflected for every model that supports it.
    body.setdefault("usage", {"include": True})
    return body

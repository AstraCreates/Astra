"""Per-session LLM token and cost tracking.

Usage is accumulated in-memory per session_id.
Expose via GET /sessions/{session_id}/cost.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

# Pricing per 1M tokens (input, output, cached_input) in USD
_PRICING: dict[str, tuple[float, float, float]] = {
    "Qwen/Qwen3-32B":                                    (0.08,  0.28,  0.02),
    "stepfun-ai/Step-3.5-Flash":                         (0.09,  0.30,  0.02),
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506":     (0.075, 0.20,  0.02),
    "zai-org/GLM-4.7-Flash":                             (0.06,  0.40,  0.01),
    "deepseek-ai/DeepSeek-V4-Flash":                     (0.10,  0.20,  0.02),
    "Qwen/Qwen3.6-35B-A3B":                              (0.15,  0.95,  0.04),
    "meta-llama/Llama-4-Scout-17B-16E-Instruct":         (0.08,  0.30,  0.02),
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": (0.15,  0.60,  0.03),
    "tencent/hy3-preview":                               (0.063, 0.21,  0.02),
    "inclusionai/ling-2.6-flash":                        (0.01,  0.03,  0.00),
    "deepseek/deepseek-v4-flash":                        (0.0983, 0.1966, 0.0197),
    "deepseek/deepseek-v4-pro":                          (0.435,  0.87,   0.003625),
    "xiaomi/mimo-v2.5":                                  (0.14,  0.40,  0.0028),
    "xiaomi/mimo-v2.5-pro":                              (0.435, 0.87,  0.0036),
    "minimax/minimax-m3":                                (0.30,  1.20,  0.06),
    "moonshotai/kimi-k2.6:free":                         (0.00,  0.00,  0.00),
    "google/gemma-4-31b-it:free":                        (0.00,  0.00,  0.00),
    "inclusionai/ling-2.6-flash":                        (0.01,  0.03,  0.00),
    "meta-llama/llama-3.3-70b-instruct":                 (0.05,  0.15,  0.01),
}

_DEFAULT_PRICING = (0.10, 0.30, 0.02)

# { session_id: { model: { prompt_tokens, completion_tokens, cached_tokens, calls } } }
_store: dict[str, dict[str, dict[str, int]]] = defaultdict(
    lambda: defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "calls": 0})
)
_lock = threading.Lock()


def record_usage(session_id: str, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> None:
    with _lock:
        entry = _store[session_id][model]
        entry["prompt_tokens"] += prompt_tokens
        entry["completion_tokens"] += completion_tokens
        entry["cached_tokens"] += cached_tokens
        entry["calls"] += 1


def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    in_price, out_price, cache_price = _PRICING.get(model, _DEFAULT_PRICING)
    # cached_tokens are already counted in prompt_tokens — charge cache rate for them, input rate for the rest
    uncached = max(0, prompt_tokens - cached_tokens)
    return (uncached * in_price + cached_tokens * cache_price + completion_tokens * out_price) / 1_000_000


def _tokens_to_credits(tokens: int) -> int:
    """Flat rate: 10 tokens = 1 credit. (Legacy — used only in the usage report.)"""
    return max(0, tokens // 10)


# ── Credit pricing ───────────────────────────────────────────────────────────────
# Credits are priced off REAL API cost so revenue scales with spend:
#   charged_usd = real_api_cost_usd * markup     (markup = 10× by default)
#   credits     = charged_usd / CREDIT_USD
# So $1 of real API cost bills as $10 of credits (10× markup), = 2000 credits at
# $0.005/credit. "Higher for certain use cases" = a bigger markup (e.g. MVP builds
# use BASE × mvp_credit_multiplier).
CREDIT_USD = 0.005         # 1 credit = $0.005 (the founder-facing price/credit)
BASE_MARKUP = 10.0         # bill 10× the real API cost


def cost_to_credits(model: str, prompt_tokens: int, completion_tokens: int,
                    cached_tokens: int = 0, markup: float = BASE_MARKUP) -> int:
    """Credits to charge for one call = real_api_cost_usd * markup / CREDIT_USD."""
    import math
    cost = _cost_usd(model, prompt_tokens, completion_tokens, cached_tokens)
    charged = cost * max(1.0, markup)
    return max(1, math.ceil(charged / CREDIT_USD))


def get_session_cost(session_id: str) -> dict[str, Any]:
    with _lock:
        models = dict(_store.get(session_id, {}))

    breakdown = []
    total_prompt = total_completion = total_cached = total_cost = 0.0

    for model, data in models.items():
        p, c, ca = data["prompt_tokens"], data["completion_tokens"], data["cached_tokens"]
        cost = _cost_usd(model, p, c, ca)
        total_prompt += p
        total_completion += c
        total_cached += ca
        total_cost += cost
        cache_pct = round(ca / p * 100, 1) if p else 0
        breakdown.append({
            "model": model,
            "prompt_tokens": p,
            "completion_tokens": c,
            "cached_tokens": ca,
            "cache_hit_pct": cache_pct,
            "total_tokens": p + c,
            "credits_used": _tokens_to_credits(p + c),
            "calls": data["calls"],
            "cost_usd": round(cost, 6),
        })

    breakdown.sort(key=lambda x: x["cost_usd"], reverse=True)

    total_tokens = int(total_prompt + total_completion)
    return {
        "session_id": session_id,
        "total_prompt_tokens": int(total_prompt),
        "total_completion_tokens": int(total_completion),
        "total_cached_tokens": int(total_cached),
        "cache_hit_pct": round(total_cached / total_prompt * 100, 1) if total_prompt else 0,
        "total_tokens": total_tokens,
        "total_credits_used": _tokens_to_credits(total_tokens),
        "total_cost_usd": round(total_cost, 6),
        "breakdown": breakdown,
    }


def get_all_sessions_cost() -> dict[str, Any]:
    with _lock:
        session_ids = list(_store.keys())

    sessions = [get_session_cost(sid) for sid in session_ids]
    grand_total = sum(s["total_cost_usd"] for s in sessions)
    return {
        "sessions": sessions,
        "grand_total_usd": round(grand_total, 6),
        "session_count": len(sessions),
    }

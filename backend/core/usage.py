"""Per-session LLM token and cost tracking.

Usage is accumulated in-memory per session_id.
Expose via GET /sessions/{session_id}/cost.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

# Pricing per 1M tokens (input, output) in USD
_PRICING: dict[str, tuple[float, float]] = {
    "Qwen/Qwen3-32B":                                 (0.08,  0.28),
    "stepfun-ai/Step-3.5-Flash":                      (0.09,  0.30),
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506":  (0.075, 0.20),
    "zai-org/GLM-4.7-Flash":                          (0.06,  0.40),
    "deepseek-ai/DeepSeek-V4-Flash":                  (0.10,  0.20),
    "Qwen/Qwen3.6-35B-A3B":                           (0.15,  0.95),
    "meta-llama/Llama-4-Scout-17B-16E-Instruct":      (0.08,  0.30),
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": (0.15, 0.60),
}

_DEFAULT_PRICING = (0.10, 0.30)  # fallback for unknown models

# { session_id: { model: { prompt_tokens, completion_tokens, calls } } }
_store: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}))
_lock = threading.Lock()


def record_usage(session_id: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    with _lock:
        entry = _store[session_id][model]
        entry["prompt_tokens"] += prompt_tokens
        entry["completion_tokens"] += completion_tokens
        entry["calls"] += 1


def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_price, out_price = _PRICING.get(model, _DEFAULT_PRICING)
    return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000


def get_session_cost(session_id: str) -> dict[str, Any]:
    with _lock:
        models = dict(_store.get(session_id, {}))

    breakdown = []
    total_prompt = total_completion = total_cost = 0.0

    for model, data in models.items():
        p, c = data["prompt_tokens"], data["completion_tokens"]
        cost = _cost_usd(model, p, c)
        total_prompt += p
        total_completion += c
        total_cost += cost
        breakdown.append({
            "model": model,
            "prompt_tokens": p,
            "completion_tokens": c,
            "total_tokens": p + c,
            "calls": data["calls"],
            "cost_usd": round(cost, 6),
        })

    breakdown.sort(key=lambda x: x["cost_usd"], reverse=True)

    return {
        "session_id": session_id,
        "total_prompt_tokens": int(total_prompt),
        "total_completion_tokens": int(total_completion),
        "total_tokens": int(total_prompt + total_completion),
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

"""Model capabilities and fallback routing policy."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    native_tool_calls: bool
    parallel_tool_calls: bool
    json_mode: bool
    context_length: int


_CAPABILITIES = {
    "deepseek/deepseek-v4-pro": ModelCapabilities(True, True, True, 1_000_000),
    "inclusionai/ling-2.6-flash": ModelCapabilities(True, True, True, 1_000_000),
    "xiaomi/mimo-v2.5": ModelCapabilities(True, True, False, 262_144),
    "xiaomi/mimo-v2.5-pro": ModelCapabilities(True, True, False, 262_144),
    "minimax/minimax-m3": ModelCapabilities(True, True, False, 1_000_000),
    # Self-hosted Qwen3.6-35B-A3B MoE via llama-server — supports OpenAI function calling
    "qwen3.6-35b-a3b-q4_k_m": ModelCapabilities(True, True, True, 32_768),
}
_DEFAULT = ModelCapabilities(False, False, True, 262_144)
# Capabilities returned for any self-hosted model (ASTRA_SELF_HOST=true).
# llama-server exposes OpenAI-compatible /v1/chat/completions with full tool-call support.
_SELF_HOST_CAPS = ModelCapabilities(True, True, True, 32_768)


def capabilities_for(model: str) -> ModelCapabilities:
    cap = _CAPABILITIES.get((model or "").lower())
    if cap is not None:
        return cap
    # When running a self-hosted model via llama-server, that model won't appear in the
    # catalog above (name is operator-defined). Detect it via settings and return
    # _SELF_HOST_CAPS so native function calling is enabled without requiring a catalog entry.
    from backend.config import settings
    if settings.astra_self_host and model and model.lower() in (
        (settings.self_host_model or "").lower(),
        "local",
    ):
        return _SELF_HOST_CAPS
    return _DEFAULT


def fallback_chain(model: str, configured_fallback: str = "") -> list[str]:
    chain = [model]
    if configured_fallback and configured_fallback not in chain:
        chain.append(configured_fallback)
    return chain

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
    "deepseek/deepseek-v4-flash": ModelCapabilities(True, True, True, 1_000_000),
    "xiaomi/mimo-v2.5": ModelCapabilities(True, True, False, 262_144),
    "xiaomi/mimo-v2.5-pro": ModelCapabilities(True, True, False, 262_144),
    "minimax/minimax-m3": ModelCapabilities(True, True, False, 1_000_000),
}
_DEFAULT = ModelCapabilities(False, False, True, 262_144)


def capabilities_for(model: str) -> ModelCapabilities:
    return _CAPABILITIES.get((model or "").lower(), _DEFAULT)


def fallback_chain(model: str, configured_fallback: str = "") -> list[str]:
    chain = [model]
    if configured_fallback and configured_fallback not in chain:
        chain.append(configured_fallback)
    return chain

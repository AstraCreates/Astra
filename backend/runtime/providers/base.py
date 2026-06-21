"""Provider-neutral completion contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    native_tool_calls: bool = False
    parallel_tool_calls: bool = False
    json_mode: bool = True
    vision: bool = False
    context_length: int = 262_144


@dataclass(frozen=True)
class ToolInvocation:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderRequest:
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 8192
    temperature: float = 0.1


@dataclass
class ProviderResponse:
    text: str = ""
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

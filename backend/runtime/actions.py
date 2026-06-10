"""Normalization target for JSON and provider-native agent actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.runtime.providers.base import ToolInvocation


@dataclass
class AgentAction:
    kind: str
    calls: list[ToolInvocation] = field(default_factory=list)
    output: dict[str, Any] | None = None
    target: str | None = None
    task: str | None = None
    reasoning: str = ""

    @classmethod
    def from_json(cls, parsed: dict[str, Any]) -> "AgentAction":
        kind = parsed.get("action") or ("tool" if parsed.get("tool") else "done")
        calls: list[ToolInvocation] = []
        if kind in {"tool", "tool_call", "function_call", "call_tool", "use_tool"}:
            calls.append(ToolInvocation(
                id="json_call",
                name=parsed.get("tool") or parsed.get("name") or parsed.get("function") or "",
                arguments=parsed.get("args") or parsed.get("arguments") or parsed.get("parameters") or {},
            ))
            kind = "tool"
        return cls(
            kind=kind,
            calls=calls,
            output=parsed.get("output"),
            target=parsed.get("agent"),
            task=parsed.get("task"),
            reasoning=parsed.get("reasoning", ""),
        )

"""Declarative specialist manifests with lightweight schema validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DelegationPolicy:
    allowed_roles: tuple[str, ...] = ()
    max_children: int = 3
    max_depth: int = 1


@dataclass(frozen=True)
class SpecialistManifest:
    name: str
    role: str
    model_policy: str = "default"
    toolsets: tuple[str, ...] = ()
    required_tools: frozenset[str] = field(default_factory=frozenset)
    output_schema: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 20
    max_cost_usd: float | None = None
    approval_categories: frozenset[str] = field(default_factory=frozenset)
    delegation_policy: DelegationPolicy = field(default_factory=DelegationPolicy)
    one_shot_tools: frozenset[str] = field(default_factory=frozenset)
    max_tool_calls: dict[str, int] = field(default_factory=dict)

    def validate(self, available_tools: set[str], available_toolsets: set[str]) -> list[str]:
        errors: list[str] = []
        missing_tools = sorted(self.required_tools - available_tools)
        missing_sets = sorted(set(self.toolsets) - available_toolsets)
        if missing_tools:
            errors.append(f"missing required tools: {', '.join(missing_tools)}")
        if missing_sets:
            errors.append(f"missing toolsets: {', '.join(missing_sets)}")
        if self.output_schema and self.output_schema.get("type") not in (None, "object"):
            errors.append("output_schema must describe an object")
        if self.max_iterations < 1:
            errors.append("max_iterations must be positive")
        return errors

    def missing_output_fields(self, output: dict[str, Any]) -> list[str]:
        return [key for key in self.output_schema.get("required", []) if output.get(key) in (None, "", [], {})]

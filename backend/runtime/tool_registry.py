"""Thread-safe self-registering tool platform.

Design adapted from NousResearch/hermes-agent `tools/registry.py` (MIT).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Mutability = Literal["read", "write", "external"]


@dataclass(frozen=True)
class ToolEntry:
    name: str
    toolset: str
    schema: dict[str, Any]
    handler: Callable
    check_fn: Callable[[], bool] | None = None
    requires_env: tuple[str, ...] = ()
    is_async: bool = False
    description: str = ""
    max_result_size_chars: int = 80_000
    risk_category: str | None = None
    mutability: Mutability = "read"
    context_fields: frozenset[str] = field(default_factory=frozenset)
    one_shot: bool = False


class ToolRegistry:
    def __init__(self, availability_ttl: float = 30.0):
        self._entries: dict[str, ToolEntry] = {}
        self._checks: dict[Callable, tuple[float, bool]] = {}
        self._ttl = availability_ttl
        self._lock = threading.RLock()

    def register(self, entry: ToolEntry, *, override: bool = False) -> ToolEntry:
        with self._lock:
            if entry.name in self._entries and not override:
                raise ValueError(f"Tool already registered: {entry.name}")
            self._entries[entry.name] = entry
        return entry

    def register_callable(
        self,
        name: str,
        handler: Callable,
        *,
        toolset: str = "legacy",
        schema: dict[str, Any] | None = None,
        override: bool = False,
        **metadata: Any,
    ) -> ToolEntry:
        entry = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema or schema_from_callable(name, handler),
            handler=handler,
            is_async=asyncio.iscoroutinefunction(handler),
            description=(inspect.getdoc(handler) or "").splitlines()[0] if inspect.getdoc(handler) else "",
            **metadata,
        )
        return self.register(entry, override=override)

    def get(self, name: str) -> ToolEntry | None:
        with self._lock:
            return self._entries.get(name)

    def snapshot(self) -> dict[str, ToolEntry]:
        with self._lock:
            return dict(self._entries)

    def is_available(self, entry: ToolEntry) -> bool:
        if any(not os.environ.get(key) for key in entry.requires_env):
            return False
        if entry.check_fn is None:
            return True
        now = time.monotonic()
        with self._lock:
            cached = self._checks.get(entry.check_fn)
            if cached and now - cached[0] < self._ttl:
                return cached[1]
        try:
            result = bool(entry.check_fn())
        except Exception:
            result = False
        with self._lock:
            self._checks[entry.check_fn] = (now, result)
        return result

    def resolve(self, *, names: list[str] | None = None, toolsets: list[str] | None = None) -> dict[str, ToolEntry]:
        wanted_names = set(names or [])
        wanted_sets = set(toolsets or [])
        return {
            name: entry for name, entry in self.snapshot().items()
            if (name in wanted_names or entry.toolset in wanted_sets) and self.is_available(entry)
        }

    def definitions(self, entries: dict[str, ToolEntry]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {**entry.schema, "name": entry.name}} for entry in entries.values()]

    async def dispatch(self, entry: ToolEntry, args: dict[str, Any], context: dict[str, Any]) -> Any:
        call_args = dict(args)
        for field_name in entry.context_fields:
            if field_name in context:
                call_args.setdefault(field_name, context[field_name])
        signature = inspect.signature(entry.handler)
        if not any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
            call_args = {key: value for key, value in call_args.items() if key in signature.parameters}
        if entry.is_async:
            result = await entry.handler(**call_args)
        else:
            result = await asyncio.to_thread(entry.handler, **call_args)
        if isinstance(result, str) and len(result) > entry.max_result_size_chars:
            return result[:entry.max_result_size_chars] + f"\n...[truncated {len(result)} chars]"
        return result

    def toolsets(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for entry in self.snapshot().values():
            row = result.setdefault(entry.toolset, {"tools": [], "available": True, "requirements": []})
            row["tools"].append(entry.name)
            row["available"] = row["available"] and self.is_available(entry)
            row["requirements"].extend(key for key in entry.requires_env if key not in row["requirements"])
        return result


def schema_from_callable(name: str, fn: Callable) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    try:
        signature = inspect.signature(fn)
    except Exception:
        signature = None
    if signature:
        for param_name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            properties[param_name] = {"type": "string"}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
    return {
        "name": name,
        "description": (inspect.getdoc(fn) or "").splitlines()[0] if inspect.getdoc(fn) else name,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


registry = ToolRegistry()

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
        call_args = _coerce_args_to_annotations(signature, call_args)
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


def _base_type_name(annotation: Any) -> str:
    """Reduce an annotation (type object OR string) to a base type name.

    Handles both runtime types (``int``) and stringified annotations produced
    by ``from __future__ import annotations`` (``"int"``, ``"Optional[int]"``,
    ``"int | None"``). Returns one of: int, float, bool, str, list, dict, or "".
    """
    # Type object path
    if not isinstance(annotation, str):
        ann = annotation
        ann_args = getattr(ann, "__args__", None)
        if ann_args:
            non_none = [a for a in ann_args if a is not type(None)]
            if len(non_none) == 1:
                ann = non_none[0]
        for typ, label in ((bool, "bool"), (int, "int"), (float, "float"), (str, "str")):
            if ann is typ:
                return label
        origin = getattr(ann, "__origin__", None)
        if ann in (list, tuple) or origin in (list, tuple):
            return "list"
        if ann is dict or origin is dict:
            return "dict"
        return ""
    # Stringified annotation path
    text = annotation.strip()
    # Strip Optional[...] / Union wrapper and " | None" tails
    inner = text
    if inner.startswith("Optional[") and inner.endswith("]"):
        inner = inner[len("Optional["):-1].strip()
    inner = inner.replace("| None", "").replace("|None", "").strip()
    inner = inner.split("|")[0].strip()  # X | Y -> X
    low = inner.lower()
    if low.startswith("bool"):
        return "bool"
    if low.startswith("int"):
        return "int"
    if low.startswith("float"):
        return "float"
    if low.startswith("str"):
        return "str"
    if low.startswith("list") or low.startswith("tuple") or low.startswith("sequence"):
        return "list"
    if low.startswith("dict") or low.startswith("mapping"):
        return "dict"
    return ""


def _coerce_args_to_annotations(signature: inspect.Signature, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce string args to their annotated types.

    LLMs frequently emit numbers/bools as JSON strings ("10", "true"). Tool
    handlers annotated int/float/bool then crash on type mismatch. Coerce
    defensively based on the handler signature. Best-effort: leave value as-is
    on failure so the handler's own validation/defaults still apply.
    """
    coerced = dict(args)
    for key, value in args.items():
        param = signature.parameters.get(key)
        if param is None or param.annotation is inspect.Parameter.empty:
            continue
        base = _base_type_name(param.annotation)
        try:
            if base == "bool" and isinstance(value, str):
                low = value.strip().lower()
                if low in {"true", "1", "yes"}:
                    coerced[key] = True
                elif low in {"false", "0", "no"}:
                    coerced[key] = False
            elif base == "int" and isinstance(value, (str, float)):
                coerced[key] = int(float(value))
            elif base == "float" and isinstance(value, (str, int)):
                coerced[key] = float(value)
        except (TypeError, ValueError):
            pass  # leave original; handler default/validation applies
    return coerced


def _json_type_for(annotation: Any) -> str:
    """Map a Python annotation to a JSON-schema type string."""
    base = _base_type_name(annotation)
    return {
        "bool": "boolean",
        "int": "integer",
        "float": "number",
        "list": "array",
        "dict": "object",
    }.get(base, "string")


def schema_from_callable(name: str, fn: Callable) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    try:
        signature = inspect.signature(fn)
    except Exception:
        signature = None
    _INJECTED_PARAMS = {"founder_id", "session_id"}
    if signature:
        for param_name, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if param_name in _INJECTED_PARAMS:
                continue  # injected from AgentContext, model must not generate these
            if param.annotation is inspect.Parameter.empty:
                properties[param_name] = {"type": "string"}
            else:
                properties[param_name] = {"type": _json_type_for(param.annotation)}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
    return {
        "name": name,
        "description": (inspect.getdoc(fn) or "").splitlines()[0] if inspect.getdoc(fn) else name,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


registry = ToolRegistry()

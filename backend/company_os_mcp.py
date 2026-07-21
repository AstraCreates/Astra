"""Company OS bridge for Astra's in-process MCP tool surface.

Company OS remains the local source of truth.  This module makes every tool
call explicit in that source of truth so Copilot and department heads use the
same MCP boundary as external MCP clients rather than bypassing it.
"""
from __future__ import annotations

import hashlib
import asyncio
import inspect
import json
from typing import Any, Mapping

from backend.company_os import append_event, get_company_os


def _runtime_tool(name: str):
    from backend.runtime.tool_registry import registry
    entry = registry.get(name)
    if entry is None:
        # Specialist construction is lazy in API workers.  Load it only when
        # a Company OS call actually needs the specialist catalog.
        try:
            from backend.core.factory import get_orchestrator
            get_orchestrator()
        except Exception:
            pass
        entry = registry.get(name)
    return entry


def available_tools(*, include_external: bool = True) -> list[dict[str, Any]]:
    """Return the single tool catalog shared by Copilot and Company OS squads.

    The legacy Astra MCP definitions are still the public protocol surface;
    specialist tools live in the runtime registry.  Keeping this merge here
    prevents one caller from seeing tools that another caller cannot execute.
    """
    from backend import astra_mcp
    from backend.runtime.tool_registry import registry
    if not registry.snapshot():
        try:
            from backend.core.factory import get_orchestrator
            get_orchestrator()
        except Exception:
            pass

    tools: dict[str, dict[str, Any]] = {
        item["name"]: {
            "name": item["name"],
            "schema": item.get("inputSchema") or {},
            "toolset": "astra",
            "mutability": "read",
            "available": True,
            "source": "astra_mcp",
        }
        for item in astra_mcp.TOOLS
    }
    for name, entry in registry.snapshot().items():
        if not include_external and entry.mutability == "external":
            continue
        tools[name] = {
            "name": name,
            "schema": entry.schema,
            "toolset": entry.toolset,
            "mutability": entry.mutability,
            "risk_category": entry.risk_category,
            "available": registry.is_available(entry),
            "source": "specialist_runtime",
        }
    return sorted(tools.values(), key=lambda item: item["name"])


def invoke(company_id: str, tool: str, arguments: Mapping[str, Any] | None = None, *,
           task_id: str | None = None, mission_id: str | None = None,
           squad_id: str | None = None, initiative_id: str | None = None,
           approved: bool = False) -> dict[str, Any]:
    """Call one MCP tool and durably audit its input and outcome.

    Tool handlers execute in-process, avoiding an HTTP loopback while retaining
    the identical registered MCP contract used by stdio and HTTP clients.
    """
    company = get_company_os(company_id)
    if not company:
        raise KeyError(f"unknown company: {company_id}")
    args = dict(arguments or {})
    args.setdefault("company_id", company_id)
    args.setdefault("founder_id", company["founder_id"])
    if tool == "astra_company_research":
        # Only this tool reads task_id (to persist a live search-count onto
        # the task as evidence comes in) -- injecting it for every tool broke
        # the generic runtime registry's strict unknown-argument check for
        # handlers that don't accept **kwargs.
        args.setdefault("task_id", task_id)
        args.setdefault("mission_id", mission_id)
        args.setdefault("squad_id", squad_id)
        args.setdefault("initiative_id", initiative_id)
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    call_id = hashlib.sha256(f"{company_id}:{tool}:{canonical}".encode()).hexdigest()[:20]
    append_event(company_id, "mcp.tool_called", {"call_id": call_id, "tool": tool,
                  "task_id": task_id, "mission_id": mission_id,
                  "profile": "company_os_deep_research" if tool == "astra_company_research" else "quick_lookup_or_specialist",
                  "arguments": _safe_args(args)})
    try:
        from backend import astra_mcp
        try:
            result = astra_mcp.call_tool(tool, args, company["founder_id"])
        except ValueError as exc:
            # Company OS tasks may use any registered specialist MCP tool, not
            # only the two Company OS-specific tools. External effects still
            # require an approval recorded by dispatch before this is allowed.
            from backend.runtime.tool_registry import registry
            entry = _runtime_tool(tool)
            if entry is None:
                raise exc
            if entry.mutability == "external" and not approved:
                raise PermissionError(f"Tool '{tool}' requires an approved Company OS action")
            if not registry.is_available(entry):
                raise RuntimeError(f"Tool '{tool}' is currently unavailable")
            context = {"founder_id": company["founder_id"], "task_id": task_id,
                       "mission_id": mission_id}
            runtime_args = dict(args)
            signature = inspect.signature(entry.handler)
            has_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
            if not has_kwargs:
                for injected in ("company_id", "founder_id"):
                    if injected not in signature.parameters:
                        runtime_args.pop(injected, None)
            result = asyncio.run(registry.dispatch(entry, runtime_args, context))
    except Exception as exc:
        append_event(company_id, "mcp.tool_failed", {"call_id": call_id, "tool": tool,
                      "task_id": task_id, "mission_id": mission_id, "error": str(exc)})
        raise
    append_event(company_id, "mcp.tool_completed", {"call_id": call_id, "tool": tool,
            "task_id": task_id, "mission_id": mission_id,
            "ok": not bool(result.get("error")) if isinstance(result, dict) else True,
            "error": result.get("error") if isinstance(result, dict) else None,
            "research_status": result.get("research_status") if isinstance(result, dict) else None,
            "research_metadata": result.get("research_metadata") if isinstance(result, dict) else None,
            "evidence_validation": result.get("evidence_validation") if isinstance(result, dict) else None})
    return result if isinstance(result, dict) else {"ok": True, "result": result}


def _safe_args(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Keep an auditable shape without writing credential material to events."""
    secrets = ("token", "secret", "password", "authorization", "api_key", "credential")
    return {key: "[redacted]" if any(word in key.lower() for word in secrets) else value for key, value in arguments.items()}

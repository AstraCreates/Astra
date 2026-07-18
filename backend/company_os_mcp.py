"""Company OS bridge for Astra's in-process MCP tool surface.

Company OS remains the local source of truth.  This module makes every tool
call explicit in that source of truth so Copilot and department heads use the
same MCP boundary as external MCP clients rather than bypassing it.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from backend.company_os import append_event, get_company_os


def invoke(company_id: str, tool: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
    call_id = hashlib.sha256(f"{company_id}:{tool}:{repr(sorted(args.items()))}".encode()).hexdigest()[:20]
    append_event(company_id, "mcp.tool_called", {"call_id": call_id, "tool": tool, "arguments": _safe_args(args)})
    try:
        from backend import astra_mcp
        result = astra_mcp.call_tool(tool, args, company["founder_id"])
    except Exception as exc:
        append_event(company_id, "mcp.tool_failed", {"call_id": call_id, "tool": tool, "error": str(exc)})
        raise
    append_event(company_id, "mcp.tool_completed", {"call_id": call_id, "tool": tool, "ok": not bool(result.get("error")) if isinstance(result, dict) else True})
    return result if isinstance(result, dict) else {"ok": True, "result": result}


def _safe_args(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Keep an auditable shape without writing credential material to events."""
    secrets = ("token", "secret", "password", "authorization", "api_key", "credential")
    return {key: "[redacted]" if any(word in key.lower() for word in secrets) else value for key, value in arguments.items()}

"""API for founder-defined custom agents.

CRUD + connector readiness + run-now. Mounted under /api.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.tenant_auth import require_founder_access
from backend.custom_agents import store
from backend.custom_agents.tool_catalog import (
    CONNECTOR_BY_KEY,
    filter_valid_tool_keys,
    public_catalog,
    public_connectors,
)
from backend.custom_agents.builder import connector_readiness

logger = logging.getLogger(__name__)

custom_agents_router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ScheduleSpec(BaseModel):
    every_days: int
    enabled: bool = True


class CreateAgentRequest(BaseModel):
    name: str
    role: str
    tool_keys: list[str] = []
    model: str = "highoutput"
    use_computer: bool = False
    schedule: ScheduleSpec | None = None
    company_id: str | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    tool_keys: list[str] | None = None
    model: str | None = None
    use_computer: bool | None = None
    schedule: ScheduleSpec | None = None
    clear_schedule: bool = False


class RunAgentRequest(BaseModel):
    goal: str | None = None
    company_id: str | None = None


# ── Tool catalog ──────────────────────────────────────────────────────────────

@custom_agents_router.get("/custom-agents/tool-catalog")
async def get_tool_catalog():
    """Public list of tools a founder can attach to a custom agent + connector meta."""
    return {"tools": public_catalog(), "connectors": public_connectors()}


# ── On-demand connect (custom-agent only; NOT the Integrations page) ───────────

@custom_agents_router.get("/custom-agents/{founder_id}/connect/{connector_key}")
async def connect_agent_connector(founder_id: str, connector_key: str, request: Request):
    """Start connecting a connector a custom agent needs.

    For Composio connectors: returns an OAuth URL the founder opens to authorize.
    For key connectors: returns the field the founder must save a credential for.
    These connectors are deliberately absent from the Integrations page.
    """
    require_founder_access(request, founder_id, min_role="operator")
    meta = CONNECTOR_BY_KEY.get(connector_key)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_key}")

    if meta.kind == "composio":
        from backend.tools.composio_tools import connect_founder_tools
        slug = meta.composio_slug or connector_key
        result = await asyncio.to_thread(connect_founder_tools, founder_id, [slug])
        url = result.get(slug, "")
        if not url or str(url).startswith("error"):
            raise HTTPException(status_code=502, detail=f"Could not start {meta.label} connect: {url or 'no url'}")
        return {"kind": "composio", "connector": connector_key, "label": meta.label, "oauth_url": url}

    # key-based connector — the founder saves a credential (token) for this service
    return {"kind": "key", "connector": connector_key, "label": meta.label, "field": "token"}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@custom_agents_router.get("/custom-agents/{founder_id}")
async def list_custom_agents(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    agents = store.list_agents(founder_id)
    # Attach connector readiness so the UI can flag agents needing setup.
    for a in agents:
        a["connector_status"] = connector_readiness(founder_id, a.get("tool_keys", []), a.get("company_id"))
    return {"agents": agents}


@custom_agents_router.post("/custom-agents/{founder_id}")
async def create_custom_agent(founder_id: str, body: CreateAgentRequest, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not (body.role or "").strip():
        raise HTTPException(status_code=400, detail="role (the agent's prompt) is required")

    valid, unknown = filter_valid_tool_keys(body.tool_keys)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown tool keys: {unknown}")

    spec = store.create_agent(
        founder_id,
        name=body.name.strip(),
        role=body.role.strip(),
        tool_keys=valid,
        model=body.model,
        use_computer=body.use_computer,
        schedule=body.schedule.model_dump() if body.schedule else None,
        company_id=body.company_id,
    )
    spec["connector_status"] = connector_readiness(founder_id, valid, body.company_id)
    return spec


@custom_agents_router.put("/custom-agents/{founder_id}/{agent_id}")
async def update_custom_agent(founder_id: str, agent_id: str, body: UpdateAgentRequest, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    valid = None
    if body.tool_keys is not None:
        valid, unknown = filter_valid_tool_keys(body.tool_keys)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown tool keys: {unknown}")

    spec = store.update_agent(
        founder_id,
        agent_id,
        name=body.name,
        role=body.role,
        tool_keys=valid,
        model=body.model,
        use_computer=body.use_computer,
        schedule=(body.schedule.model_dump() if body.schedule else None),
        _schedule_explicit=body.clear_schedule or body.schedule is not None,
    )
    if spec is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    spec["connector_status"] = connector_readiness(founder_id, spec.get("tool_keys", []), spec.get("company_id"))
    return spec


@custom_agents_router.delete("/custom-agents/{founder_id}/{agent_id}")
async def delete_custom_agent(founder_id: str, agent_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    ok = store.delete_agent(founder_id, agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return {"ok": True}


# ── Connector readiness ───────────────────────────────────────────────────────

@custom_agents_router.get("/custom-agents/{founder_id}/{agent_id}/connector-check")
async def check_agent_connectors(founder_id: str, agent_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    spec = store.get_agent(founder_id, agent_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return connector_readiness(founder_id, spec.get("tool_keys", []), spec.get("company_id"))


# ── Run now ───────────────────────────────────────────────────────────────────

@custom_agents_router.post("/custom-agents/{founder_id}/{agent_id}/run")
async def run_custom_agent(founder_id: str, agent_id: str, body: RunAgentRequest, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    spec = store.get_agent(founder_id, agent_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")

    from backend.custom_agents.runner import launch_custom_agent_run

    session_id = await launch_custom_agent_run(
        founder_id=founder_id,
        spec=spec,
        goal=(body.goal or "").strip() or None,
        company_id=body.company_id or spec.get("company_id"),
    )
    return {"session_id": session_id, "status": "running", "agent_id": agent_id}

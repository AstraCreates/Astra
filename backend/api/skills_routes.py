"""Skills API — CRUD + attach/detach endpoints.

Mounted at /api by main.py  →  all paths below are relative to /api.

POST   /skills                              — create skill
GET    /skills?founder_id=x                — list skills for founder
GET    /skills/for-agent?founder_id=x&agent_key=y — skills attached to agent
GET    /skills/{id}?founder_id=x           — get single skill
PATCH  /skills/{id}                        — update skill fields
DELETE /skills/{id}?founder_id=x          — delete skill
POST   /skills/{id}/attach?agent_key=x    — attach to agent
DELETE /skills/{id}/attach?agent_key=x   — detach from agent
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.skills.store import (
    attach_skill,
    create_skill,
    delete_skill,
    detach_skill,
    get_skill,
    get_skills_for_agent,
    list_skills,
    update_skill,
)
from backend.skills.proposals import (
    activate_proposal,
    create_proposal,
    list_proposals,
    resolve_proposal,
    rollback_skill,
)

logger = logging.getLogger(__name__)

skills_router = APIRouter(prefix="/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateSkillRequest(BaseModel):
    founder_id: str
    name: str
    description: str = ""
    content: str = ""
    agent_keys: list[str] = []
    is_builtin: bool = False


class UpdateSkillRequest(BaseModel):
    founder_id: str
    name: str | None = None
    description: str | None = None
    content: str | None = None
    agent_keys: list[str] | None = None


class CreateProposalRequest(BaseModel):
    founder_id: str
    specialist: str
    source_session: str
    evidence: str
    proposed_change: str
    risk_level: str = "low"
    reviewer: str = "agent"
    skill_id: str | None = None


class ResolveProposalRequest(BaseModel):
    founder_id: str
    reviewer: str
    status: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@skills_router.post("")
async def api_create_skill(body: CreateSkillRequest) -> dict[str, Any]:
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    if not body.name:
        raise HTTPException(status_code=400, detail="name is required")
    skill = create_skill(
        founder_id=body.founder_id,
        name=body.name,
        description=body.description,
        content=body.content,
        agent_keys=body.agent_keys,
        is_builtin=body.is_builtin,
    )
    return {"ok": True, "skill": skill}


@skills_router.get("/for-agent")
async def api_skills_for_agent(
    founder_id: str = Query(...),
    agent_key: str = Query(...),
) -> dict[str, Any]:
    """Return all skills attached to a specific agent."""
    if not founder_id or not agent_key:
        raise HTTPException(status_code=400, detail="founder_id and agent_key are required")
    skills = get_skills_for_agent(founder_id, agent_key)
    return {"founder_id": founder_id, "agent_key": agent_key, "skills": skills}


@skills_router.get("")
async def api_list_skills(founder_id: str = Query(...)) -> dict[str, Any]:
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    skills = list_skills(founder_id)
    return {"founder_id": founder_id, "skills": skills}


@skills_router.post("/proposals")
async def api_create_skill_proposal(body: CreateProposalRequest) -> dict[str, Any]:
    try:
        proposal = create_proposal(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "proposal": proposal}


@skills_router.get("/proposals/list")
async def api_list_skill_proposals(founder_id: str = Query(...), status: str | None = None) -> dict[str, Any]:
    return {"founder_id": founder_id, "proposals": list_proposals(founder_id, status)}


@skills_router.post("/proposals/{proposal_id}/resolve")
async def api_resolve_skill_proposal(proposal_id: str, body: ResolveProposalRequest) -> dict[str, Any]:
    try:
        proposal = resolve_proposal(body.founder_id, proposal_id, body.status, body.reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"ok": True, "proposal": proposal}


@skills_router.post("/proposals/{proposal_id}/activate")
async def api_activate_skill_proposal(
    proposal_id: str,
    founder_id: str = Query(...),
    reviewer: str = Query(...),
) -> dict[str, Any]:
    result = activate_proposal(founder_id, proposal_id, reviewer)
    if result is None:
        raise HTTPException(status_code=409, detail="Proposal must exist and be approved")
    return {"ok": True, **result}


@skills_router.post("/{skill_id}/rollback")
async def api_rollback_skill(skill_id: str, founder_id: str = Query(...)) -> dict[str, Any]:
    skill = rollback_skill(founder_id, skill_id)
    if skill is None:
        raise HTTPException(status_code=409, detail="Skill has no prior version to restore")
    return {"ok": True, "skill": skill}


@skills_router.get("/{skill_id}")
async def api_get_skill(skill_id: str, founder_id: str = Query(...)) -> dict[str, Any]:
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    skill = get_skill(founder_id, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"skill": skill}


@skills_router.patch("/{skill_id}")
async def api_update_skill(skill_id: str, body: UpdateSkillRequest) -> dict[str, Any]:
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    skill = update_skill(
        founder_id=body.founder_id,
        skill_id=skill_id,
        name=body.name,
        description=body.description,
        content=body.content,
        agent_keys=body.agent_keys,
    )
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True, "skill": skill}


@skills_router.delete("/{skill_id}")
async def api_delete_skill(skill_id: str, founder_id: str = Query(...)) -> dict[str, Any]:
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    deleted = delete_skill(founder_id, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True, "skill_id": skill_id}


@skills_router.post("/{skill_id}/attach")
async def api_attach_skill(
    skill_id: str,
    founder_id: str = Query(...),
    agent_key: str = Query(...),
) -> dict[str, Any]:
    if not founder_id or not agent_key:
        raise HTTPException(status_code=400, detail="founder_id and agent_key are required")
    skill = attach_skill(founder_id, skill_id, agent_key)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True, "skill": skill}


@skills_router.delete("/{skill_id}/attach")
async def api_detach_skill(
    skill_id: str,
    founder_id: str = Query(...),
    agent_key: str = Query(...),
) -> dict[str, Any]:
    if not founder_id or not agent_key:
        raise HTTPException(status_code=400, detail="founder_id and agent_key are required")
    skill = detach_skill(founder_id, skill_id, agent_key)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True, "skill": skill}

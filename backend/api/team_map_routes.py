"""Team Map API — department capability scoring and gap detection."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.genome.team_map import score_team_map, create_goal_from_gap
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateGoalFromGapRequest(BaseModel):
    dept: str
    gap: str


@router.get("/team-map")
async def get_team_map_route(
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Score department capabilities and identify gaps."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    result = score_team_map(founder_id, resolved_company_id)
    return result


@router.post("/team-map/{dept}/create-goal")
async def create_goal_from_gap_route(
    dept: str,
    body: CreateGoalFromGapRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Convert department gap into a goal in 'next' bucket."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    result = create_goal_from_gap(
        founder_id,
        company_id=resolved_company_id,
        dept=dept,
        gap=body.gap,
    )
    return result

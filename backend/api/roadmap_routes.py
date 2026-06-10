"""Roadmap API — personalized Now/Next/Later goals from company genome."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.missions.roadmap import generate_roadmap, apply_roadmap
from backend.tenant_auth import require_founder_access, require_company_access

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateRoadmapRequest(BaseModel):
    genome: Optional[dict[str, Any]] = None


class ApplyRoadmapRequest(BaseModel):
    roadmap: Optional[dict[str, Any]] = None


@router.post("/roadmap/generate")
async def generate_roadmap_route(
    body: GenerateRoadmapRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Generate personalized roadmap from company genome using LLM."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    result = generate_roadmap(
        founder_id,
        company_id=resolved_company_id,
        genome=body.genome,
    )
    return result


@router.post("/roadmap/apply")
async def apply_roadmap_route(
    body: ApplyRoadmapRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Convert roadmap into company_goal goals with bucket + success_criteria."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    ok = apply_roadmap(
        founder_id,
        company_id=resolved_company_id,
        roadmap=body.roadmap,
    )
    return {"ok": ok}

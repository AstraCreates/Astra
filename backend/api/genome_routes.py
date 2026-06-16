"""Genome API — structured editable company knowledge."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.genome.store import (
    get_genome,
    get_section,
    set_fact,
    resolve_conflict,
    get_conflicts,
)
from backend.tenant_auth import require_founder_access, require_company_access

logger = logging.getLogger(__name__)
router = APIRouter()


class SetFactRequest(BaseModel):
    section: str
    key: str
    value: Any
    source: str = "founder"
    confidence: float = 1.0


class ResolveConflictRequest(BaseModel):
    conflict_id: str
    keep_value: Optional[Any] = None


@router.get("/genome")
async def get_genome_route(
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Fetch company genome."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    genome = get_genome(founder_id, resolved_company_id)
    return {"genome": genome, "conflicts": get_conflicts(founder_id, resolved_company_id)}


@router.get("/genome/section/{section}")
async def get_section_route(
    section: str,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Fetch one section of the genome."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    facts = get_section(founder_id, section, resolved_company_id)
    return {"section": section, "facts": facts}


@router.post("/genome/fact")
async def set_fact_route(
    body: SetFactRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Set or update a genome fact."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    updated_genome = set_fact(
        founder_id,
        body.section,
        body.key,
        body.value,
        source=body.source,
        confidence=body.confidence,
        company_id=resolved_company_id,
    )
    try:
        from backend.funding.kit import mark_stale
        mark_stale(founder_id)
    except Exception:
        pass
    return {"genome": updated_genome, "ok": True}


@router.post("/genome/conflict/resolve")
async def resolve_conflict_route(
    body: ResolveConflictRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Founder resolves a genome conflict."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    ok = resolve_conflict(
        founder_id,
        resolved_company_id,
        body.conflict_id,
        body.keep_value,
    )
    return {"ok": ok}

"""Outcomes API — business results ledger."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.outcomes.store import (
    add_outcome,
    list_outcomes,
    update_outcome_state,
    weekly_rollup,
)
from backend.tenant_auth import require_founder_access, require_company_access

logger = logging.getLogger(__name__)
router = APIRouter()


class AddOutcomeRequest(BaseModel):
    run_id: str
    agent: str
    metric: str
    value: float
    unit: str
    evidence: Optional[dict] = None
    credits_cost: float = 0.0


class UpdateOutcomeStateRequest(BaseModel):
    outcome_id: str
    new_state: str


@router.post("/outcomes")
async def add_outcome_route(
    body: AddOutcomeRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Record an outcome."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    outcome = add_outcome(
        founder_id,
        resolved_company_id,
        run_id=body.run_id,
        agent=body.agent,
        metric=body.metric,
        value=body.value,
        unit=body.unit,
        evidence=body.evidence,
        credits_cost=body.credits_cost,
    )
    return {"outcome": outcome, "ok": True}


@router.get("/outcomes")
async def list_outcomes_route(
    founder_id: str,
    company_id: str = "",
    since: str = "",
    states: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Fetch outcomes, optionally filtered."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    state_list = [s.strip() for s in states.split(",") if s.strip()] if states else None
    outcomes = list_outcomes(founder_id, resolved_company_id, since=since or None, states=state_list)
    return {"outcomes": outcomes, "count": len(outcomes)}


@router.patch("/outcomes")
async def update_outcome_state_route(
    body: UpdateOutcomeStateRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Transition outcome state."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    ok = update_outcome_state(founder_id, body.outcome_id, body.new_state, resolved_company_id)
    return {"ok": ok}


@router.get("/outcomes/weekly")
async def weekly_rollup_route(
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Get this week's outcome rollup by metric + state."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    rollup = weekly_rollup(founder_id, resolved_company_id)
    return {"rollup": rollup}

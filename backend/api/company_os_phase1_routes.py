"""Operator-only controls for the Company OS Phase 1 internal cohort."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.tenant_auth import require_platform_admin

router = APIRouter(prefix="/admin/company-os/phase1", tags=["company-os-phase1"], dependencies=[Depends(require_platform_admin)])
phase2_router = APIRouter(prefix="/admin/company-os/phase2", tags=["company-os-phase2"], dependencies=[Depends(require_platform_admin)])


class CohortBody(BaseModel):
    company_id: str
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class FixtureBody(BaseModel):
    company_id: str
    fixture: dict[str, Any]


class CompanyBody(BaseModel):
    company_id: str


class Phase2DrainBody(BaseModel):
    confirmation: str


@router.post("/cohort")
async def configure_cohort(body: CohortBody):
    from backend.company_os_phase1 import configure_internal_test_cohort
    return configure_internal_test_cohort(body.company_id, enabled=body.enabled, metadata=body.metadata)


@router.get("/cohort")
async def list_cohort():
    from backend.company_os_phase1 import list_internal_test_cohort
    return {"companies": list_internal_test_cohort()}


@router.post("/dual-write")
async def dual_write_fixture(body: FixtureBody):
    from backend.company_os_phase1 import dual_write_legacy_fixture
    try:
        return dual_write_legacy_fixture(body.company_id, body.fixture)
    except (KeyError, PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parity")
async def assess_fixture_parity(body: FixtureBody):
    from backend.company_os_phase1 import assess_parity
    try:
        return assess_parity(body.company_id, body.fixture)
    except (KeyError, PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rebuild")
async def rebuild_projections(body: CompanyBody):
    from backend.company_os_projection import rebuild_company_projections
    try:
        return rebuild_company_projections(body.company_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/recovery-drill")
async def recovery_drill(body: CompanyBody):
    from backend.company_os_integrity import run_recovery_drill
    return run_recovery_drill(body.company_id)


@router.get("/{company_id}/gate")
async def phase_1_gate(company_id: str, request: Request):
    from backend.company_os_integrity import evaluate_phase_1_gate
    return evaluate_phase_1_gate(company_id)


@router.post("/{company_id}/authorize-phase-2")
async def authorize_phase_2(company_id: str):
    """The sole Company OS Phase 2 handoff; it is impossible to authorize without proof."""
    from backend.company_os_integrity import require_phase_1_gate
    try:
        return {"authorized": True, "gate": require_phase_1_gate(company_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@phase2_router.get("/inventory")
async def phase_2_inventory():
    from backend.company_os_phase2 import inventory_legacy_work, read_phase_2_receipts
    return {"inventory": await inventory_legacy_work(), "receipts": read_phase_2_receipts()}


@phase2_router.post("/drain")
async def phase_2_drain(body: Phase2DrainBody, request: Request):
    from backend.company_os_phase2 import force_drain_legacy_work
    operator = getattr(request.state, "user", None) or "platform_admin"
    try:
        return await force_drain_legacy_work(operator_id=str(operator), confirmation=body.confirmation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

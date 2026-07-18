"""Company OS API: the permanent Copilot thread and its durable work graph."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.company_os import append_message, create_company_os, ensure_company_operations, get_company_os
from backend.company_os_dispatch import dispatch_intent, scheduler_tick
from backend.company_os_runner import launch_mission
from backend.tenant_auth import require_founder_access

router = APIRouter(tags=["company-os"])


class CompanyOSCreateBody(BaseModel):
    founder_id: str
    name: str = Field(min_length=1, max_length=160)
    company_id: str | None = None


class CopilotMessageBody(BaseModel):
    founder_id: str
    message: str = Field(min_length=1, max_length=20_000)
    proposed_spend: float = Field(default=0, ge=0)


def _artifact(company_id: str, artifact_id: str) -> dict[str, Any]:
    company = get_company_os(company_id) or {}
    artifact = next((item for item in company.get("artifacts", []) if item.get("artifact_id") == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


def _company(request: Request, company_id: str, founder_id: str, *, operator: bool = False) -> dict[str, Any]:
    """Authorize access, then lazily create the local Company OS for a new company."""
    require_founder_access(request, founder_id, min_role="operator" if operator else "viewer")
    company = get_company_os(company_id)
    if company:
        if company["founder_id"] != founder_id:
            raise HTTPException(status_code=404, detail="Company not found")
        ensure_company_operations(company_id)
        return company
    created = create_company_os(company_id, founder_id, "Company")
    ensure_company_operations(company_id)
    return created


@router.post("/company-os")
async def create_company_os_route(body: CompanyOSCreateBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")
    company_id = body.company_id or body.founder_id
    company = create_company_os(company_id, body.founder_id, body.name)
    ensure_company_operations(company_id)
    return get_company_os(company_id) or company


@router.get("/companies/{company_id}/os")
async def get_company_os_route(company_id: str, founder_id: str, request: Request):
    return _company(request, company_id, founder_id)


@router.get("/companies/{company_id}/os/artifacts/{artifact_id}")
async def get_company_os_artifact(company_id: str, artifact_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    return _artifact(company_id, artifact_id)


@router.get("/companies/{company_id}/os/artifacts/{artifact_id}/download")
async def download_company_os_artifact(company_id: str, artifact_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    artifact = _artifact(company_id, artifact_id)
    safe_name = "".join(char if char.isalnum() or char in " -_." else "_" for char in str(artifact.get("name") or "artifact"))
    return PlainTextResponse(str(artifact.get("content") or ""), headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'})


@router.post("/companies/{company_id}/os/copilot")
async def copilot_message_route(company_id: str, body: CopilotMessageBody, request: Request):
    _company(request, company_id, body.founder_id, operator=True)
    append_message(company_id, body.message, author="founder", role="user")
    dispatch = dispatch_intent(company_id, body.message, proposed_spend=body.proposed_spend)
    squad = dispatch["squad"]
    initiative = dispatch["initiative"]
    department = dispatch["department"].replace("_", " ").title()
    acknowledgement = (
        f"I formed the {squad['name'].title()} Squad for {initiative['name']}. "
        f"The {department} Lead is coordinating the work and will surface any approval needed."
    )
    append_message(company_id, acknowledgement, author="copilot", role="assistant",
                   scope="initiative", scope_id=initiative["initiative_id"])
    launch_mission(company_id, dispatch["mission"]["mission_id"])
    return {"message": acknowledgement, "dispatch": dispatch, "company": get_company_os(company_id)}


@router.post("/companies/{company_id}/os/operations/tick")
async def operations_tick_route(company_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id, operator=True)
    # The scheduler can only execute policy-approved internal tasks. This executor
    # deliberately produces a local audit artifact rather than performing I/O.
    results = scheduler_tick(company_id, lambda task: {"kind": "local_internal_update", "task": task.get("name")})
    return {"results": results, "company": get_company_os(company_id)}

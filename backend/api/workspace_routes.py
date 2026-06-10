"""Company management API with backward-compatible workspace routes."""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core import workspace_store
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateWorkspaceBody(BaseModel):
    founder_id: str
    name: str = ""
    goal: str = ""
    stack_id: str = "idea_to_revenue"
    company_name: str = ""


class DuplicateCompanyBody(BaseModel):
    name: str = ""


class CreateChapterBody(BaseModel):
    session_id: str
    name: str = ""
    phase_scope: Optional[str] = None


class UpdateWorkspaceBody(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None
    status: Optional[str] = None


class UpdateChapterBody(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None


def _owned_company(
    request: Request,
    company_id: str,
    min_role: str = "viewer",
) -> dict:
    company = workspace_store.get_workspace(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    require_founder_access(
        request,
        str(company.get("founder_id") or ""),
        min_role=min_role,
    )
    return company


def _company_detail(company_id: str) -> dict:
    company = workspace_store.get_workspace(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        **company,
        "chapters": workspace_store.list_chapters(company_id),
        "vault": workspace_store.get_vault(company_id),
    }


def _create_company(body: CreateWorkspaceBody) -> dict:
    return workspace_store.create_workspace(
        founder_id=body.founder_id,
        name=body.name,
        goal=body.goal,
        stack_id=body.stack_id,
        company_name=body.company_name,
    )


@router.post("/companies")
async def create_company_route(body: CreateWorkspaceBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")
    return _create_company(body)


@router.get("/companies")
async def list_companies_route(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    return workspace_store.list_workspaces(founder_id)


@router.get("/companies/{company_id}")
async def get_company_route(company_id: str, request: Request):
    _owned_company(request, company_id)
    return _company_detail(company_id)


@router.patch("/companies/{company_id}")
async def update_company_route(
    company_id: str,
    body: UpdateWorkspaceBody,
    request: Request,
):
    _owned_company(request, company_id, min_role="operator")
    fields = {key: value for key, value in body.model_dump().items() if value is not None}
    company = workspace_store.update_workspace_meta(company_id, **fields) if fields else None
    return {"ok": True, **(company or _company_detail(company_id))}


@router.post("/companies/{company_id}/archive")
async def archive_company_route(company_id: str, request: Request):
    _owned_company(request, company_id, min_role="admin")
    return workspace_store.archive_workspace(company_id)


@router.post("/companies/{company_id}/duplicate")
async def duplicate_company_route(
    company_id: str,
    body: DuplicateCompanyBody,
    request: Request,
):
    _owned_company(request, company_id, min_role="operator")
    duplicate = workspace_store.duplicate_workspace(company_id, name=body.name)
    if not duplicate:
        raise HTTPException(status_code=404, detail="Company not found")
    return duplicate


@router.get("/companies/{company_id}/export")
async def export_company_route(company_id: str, request: Request):
    company = _owned_company(request, company_id)
    archive = workspace_store.export_workspace_zip(company_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="Company not found")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(company.get("name") or company_id)).strip("-")
    filename = f"{safe_name or company_id}-astra-export.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Existing workspace routes remain available while clients migrate terminology.


@router.post("/workspaces")
async def create_workspace_route(body: CreateWorkspaceBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")
    return _create_company(body)


@router.get("/workspaces")
async def list_workspaces_route(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    return workspace_store.list_workspaces(founder_id)


@router.get("/workspaces/{workspace_id}")
async def get_workspace_route(workspace_id: str, request: Request):
    _owned_company(request, workspace_id)
    return _company_detail(workspace_id)


@router.patch("/workspaces/{workspace_id}")
async def update_workspace_route(
    workspace_id: str,
    body: UpdateWorkspaceBody,
    request: Request,
):
    _owned_company(request, workspace_id, min_role="operator")
    fields = {key: value for key, value in body.model_dump().items() if value is not None}
    company = workspace_store.update_workspace_meta(workspace_id, **fields) if fields else None
    return {"ok": True, **(company or _company_detail(workspace_id))}


@router.post("/workspaces/{workspace_id}/chapters")
async def create_chapter_route(
    workspace_id: str,
    body: CreateChapterBody,
    request: Request,
):
    _owned_company(request, workspace_id, min_role="operator")
    return workspace_store.create_chapter(
        workspace_id=workspace_id,
        session_id=body.session_id,
        name=body.name,
        phase_scope=body.phase_scope,
    )


@router.get("/workspaces/{workspace_id}/chapters")
async def list_chapters_route(workspace_id: str, request: Request):
    _owned_company(request, workspace_id)
    return workspace_store.list_chapters(workspace_id)


@router.patch("/workspaces/{workspace_id}/chapters/{chapter_id}")
async def update_chapter_route(
    workspace_id: str,
    chapter_id: str,
    body: UpdateChapterBody,
    request: Request,
):
    _owned_company(request, workspace_id, min_role="operator")
    fields = {key: value for key, value in body.model_dump().items() if value is not None}
    if fields:
        workspace_store.update_chapter(workspace_id, chapter_id, **fields)
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/vault")
async def get_vault_route(workspace_id: str, request: Request):
    _owned_company(request, workspace_id)
    return workspace_store.get_vault(workspace_id)

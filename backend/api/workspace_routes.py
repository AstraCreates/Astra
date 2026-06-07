"""Workspace and chapter management REST API."""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core import workspace_store

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateWorkspaceBody(BaseModel):
    founder_id: str
    name: str = ""
    goal: str = ""
    stack_id: str = "idea_to_revenue"
    company_name: str = ""


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


@router.post("/workspaces")
async def create_workspace_route(body: CreateWorkspaceBody):
    return workspace_store.create_workspace(
        founder_id=body.founder_id,
        name=body.name,
        goal=body.goal,
        stack_id=body.stack_id,
        company_name=body.company_name,
    )


@router.get("/workspaces")
async def list_workspaces_route(founder_id: str):
    return workspace_store.list_workspaces(founder_id)


@router.get("/workspaces/{workspace_id}")
async def get_workspace_route(workspace_id: str):
    ws = workspace_store.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    chapters = workspace_store.list_chapters(workspace_id)
    vault = workspace_store.get_vault(workspace_id)
    return {**ws, "chapters": chapters, "vault": vault}


@router.patch("/workspaces/{workspace_id}")
async def update_workspace_route(workspace_id: str, body: UpdateWorkspaceBody):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        workspace_store.update_workspace_meta(workspace_id, **fields)
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/chapters")
async def create_chapter_route(workspace_id: str, body: CreateChapterBody):
    ws = workspace_store.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return workspace_store.create_chapter(
        workspace_id=workspace_id,
        session_id=body.session_id,
        name=body.name,
        phase_scope=body.phase_scope,
    )


@router.get("/workspaces/{workspace_id}/chapters")
async def list_chapters_route(workspace_id: str):
    return workspace_store.list_chapters(workspace_id)


@router.patch("/workspaces/{workspace_id}/chapters/{chapter_id}")
async def update_chapter_route(workspace_id: str, chapter_id: str, body: UpdateChapterBody):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        workspace_store.update_chapter(workspace_id, chapter_id, **fields)
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/vault")
async def get_vault_route(workspace_id: str):
    return workspace_store.get_vault(workspace_id)

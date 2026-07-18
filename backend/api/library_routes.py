"""Library API — structured per-founder file storage.

Endpoints:
  POST   /library                — create file
  GET    /library?founder_id=x&department=y — list files (no content)
  GET    /library/{id}?founder_id=x — get file with content
  PATCH  /library/{id}           — update file
  DELETE /library/{id}?founder_id=x — delete file
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.tenant_auth import FounderActor, current_founder_from_query, require_current_founder
from backend.library.store import (
    create_file,
    delete_file,
    get_file,
    list_files,
    update_file,
)

logger = logging.getLogger(__name__)

library_router = APIRouter()


# ── Request schemas ────────────────────────────────────────────────────────────

class CreateFileRequest(BaseModel):
    founder_id: str
    department: str
    filename: str
    content: str
    is_canonical: bool = False


class UpdateFileRequest(BaseModel):
    founder_id: str
    content: Optional[str] = None
    filename: Optional[str] = None
    department: Optional[str] = None
    is_canonical: Optional[bool] = None


def require_create_file_actor(body: CreateFileRequest, request: Request) -> FounderActor:
    return require_current_founder(request, body.founder_id, min_role="operator")


def require_update_file_actor(body: UpdateFileRequest, request: Request) -> FounderActor:
    return require_current_founder(request, body.founder_id, min_role="operator")


# ── Routes ─────────────────────────────────────────────────────────────────────

@library_router.post("/library")
async def api_create_file(
    body: CreateFileRequest,
    actor: FounderActor = Depends(require_create_file_actor),
):
    """Create a new library file for a founder."""
    if not body.filename or not body.department:
        raise HTTPException(status_code=400, detail="founder_id, filename, and department are required")
    founder_id = actor.founder_id
    record = create_file(
        founder_id=founder_id,
        department=body.department,
        filename=body.filename,
        content=body.content,
        is_canonical=body.is_canonical,
    )
    return {"ok": True, "file": record}


@library_router.get("/library")
async def api_list_files(
    actor: FounderActor = Depends(current_founder_from_query(min_role="viewer")),
    department: Optional[str] = Query(None, description="Optional department filter"),
):
    """List library file metadata for a founder (no content included)."""
    founder_id = actor.founder_id
    files = list_files(founder_id=founder_id, department=department or None)
    return {"ok": True, "files": files, "count": len(files)}


@library_router.get("/library/examples")
async def api_list_examples():
    """Return all entries from the backend examples library (agent code patterns)."""
    import asyncio
    from backend.tools.examples_library import _load_examples
    examples = await asyncio.to_thread(_load_examples)
    return {"ok": True, "examples": examples}


@library_router.get("/library/{file_id}")
async def api_get_file(
    file_id: str,
    actor: FounderActor = Depends(current_founder_from_query(min_role="viewer")),
):
    """Get a single library file including its content."""
    founder_id = actor.founder_id
    record = get_file(founder_id=founder_id, file_id=file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True, "file": record}


@library_router.patch("/library/{file_id}")
async def api_update_file(
    file_id: str,
    body: UpdateFileRequest,
    actor: FounderActor = Depends(require_update_file_actor),
):
    """Update file content or metadata."""
    founder_id = actor.founder_id
    record = update_file(
        founder_id=founder_id,
        file_id=file_id,
        content=body.content,
        filename=body.filename,
        department=body.department,
        is_canonical=body.is_canonical,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True, "file": record}


@library_router.delete("/library/{file_id}")
async def api_delete_file(
    file_id: str,
    actor: FounderActor = Depends(current_founder_from_query(min_role="operator")),
):
    """Delete a library file."""
    founder_id = actor.founder_id
    deleted = delete_file(founder_id=founder_id, file_id=file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    # Keep the Company OS artifact projection in sync when the Library is the
    # deletion entry point. Event history remains intact; the artifact is archived.
    try:
        from backend.company_os import list_company_os, update_artifact
        for company in list_company_os(founder_id):
            for artifact in company.get("artifacts", []):
                if artifact.get("library_file_id") == file_id and artifact.get("state") != "archived":
                    update_artifact(company["company_id"], artifact["artifact_id"], state="archived")
    except Exception:
        logger.warning("Library delete Company OS cascade failed file=%s", file_id, exc_info=True)
    return {"ok": True, "file_id": file_id, "deleted": True}

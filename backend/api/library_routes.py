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

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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


# ── Routes ─────────────────────────────────────────────────────────────────────

@library_router.post("/library")
async def api_create_file(body: CreateFileRequest):
    """Create a new library file for a founder."""
    if not body.founder_id or not body.filename or not body.department:
        raise HTTPException(status_code=400, detail="founder_id, filename, and department are required")
    record = create_file(
        founder_id=body.founder_id,
        department=body.department,
        filename=body.filename,
        content=body.content,
        is_canonical=body.is_canonical,
    )
    return {"ok": True, "file": record}


@library_router.get("/library")
async def api_list_files(
    founder_id: str = Query(..., description="Founder ID to list files for"),
    department: Optional[str] = Query(None, description="Optional department filter"),
):
    """List library file metadata for a founder (no content included)."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    files = list_files(founder_id=founder_id, department=department or None)
    return {"ok": True, "files": files, "count": len(files)}


@library_router.get("/library/{file_id}")
async def api_get_file(
    file_id: str,
    founder_id: str = Query(..., description="Founder ID who owns the file"),
):
    """Get a single library file including its content."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    record = get_file(founder_id=founder_id, file_id=file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True, "file": record}


@library_router.patch("/library/{file_id}")
async def api_update_file(file_id: str, body: UpdateFileRequest):
    """Update file content or metadata."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    record = update_file(
        founder_id=body.founder_id,
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
    founder_id: str = Query(..., description="Founder ID who owns the file"),
):
    """Delete a library file."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    deleted = delete_file(founder_id=founder_id, file_id=file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True, "file_id": file_id, "deleted": True}

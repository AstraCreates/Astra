"""Funding kit API — status and generation trigger."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/funding/status/{founder_id}")
async def funding_status(founder_id: str, company_id: str = "", request: Request = None):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.funding.kit import get_status
    return await asyncio.to_thread(get_status, founder_id, company_id or None)


@router.post("/funding/generate/{founder_id}")
async def funding_generate(
    founder_id: str,
    company_id: str = "",
    background_tasks: BackgroundTasks = None,
    request: Request = None,
):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.funding.kit import generate_funding_kit, get_status

    status = await asyncio.to_thread(get_status, founder_id, company_id or None)
    if status.get("generating"):
        raise HTTPException(status_code=409, detail="Generation already in progress")

    async def _run():
        try:
            await asyncio.to_thread(generate_funding_kit, founder_id, company_id or None)
        except Exception as exc:
            logger.error("funding_generate bg task failed: %s", exc)

    background_tasks.add_task(_run)
    return {"started": True}

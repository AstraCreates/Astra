"""Cross-company benchmarks + auto-maintained data room API."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from backend import run_ledger
from backend.dataroom import build_data_room
from backend.insights.benchmarks import get_session_benchmark
from backend.tenant_auth import require_company_access, require_founder_access

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/insights/benchmark/{session_id}")
async def session_benchmark_route(session_id: str, founder_id: str, request: Request):
    """How this session's outcome count stacks up against every other
    company's completed run of the same stack template."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="viewer")

    run = run_ledger.get_run(session_id)
    if run and run.get("founder_id") and run.get("founder_id") != founder_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different founder")

    return await asyncio.to_thread(get_session_benchmark, session_id)


@router.get("/dataroom/{founder_id}/{company_id}")
async def data_room_route(founder_id: str, company_id: str, request: Request):
    """Always-current snapshot of a company: every deliverable generated
    across every session, live Stripe revenue if connected, and profile."""
    require_company_access(request, founder_id, company_id, min_role="viewer")
    return await asyncio.to_thread(build_data_room, founder_id, company_id)

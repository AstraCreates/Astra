"""Connectors API — check status, request missing connectors at moment of value."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.connector_validation import validate_stack_connectors
from backend.connector_coverage import build_connector_coverage
from backend.safety.connector_check import (
    check_connector_availability,
    get_connector_requirements,
)
from backend.tenant_auth import require_founder_access, require_company_access

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectorCheckRequest(BaseModel):
    tool_name: str


@router.get("/connectors")
async def list_connectors_route(
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Get connector status: connected/degraded/expired/missing per connector."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    coverage = build_connector_coverage(founder_id, stack_id=resolved_company_id) or {}
    return {"connectors": coverage, "ok": True}


@router.post("/connectors/check")
async def check_tool_connectors_route(
    body: ConnectorCheckRequest,
    founder_id: str,
    company_id: str = "",
    request: Request = None,
) -> dict[str, Any]:
    """Check if a tool's required connectors are available.

    Returns missing/expired/degraded lists. Empty = all available.
    """
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    resolved_company_id = company_id or founder_id
    check_result = check_connector_availability(
        founder_id, body.tool_name, company_id=resolved_company_id
    )
    return check_result


@router.get("/connectors/requirements/{tool_name}")
async def get_tool_requirements_route(
    tool_name: str,
    request: Request = None,
) -> dict[str, Any]:
    """Get list of connectors required by a tool."""
    requirements = get_connector_requirements(tool_name)
    return {"tool": tool_name, "requirements": requirements}


@router.post("/connectors/validate")
async def validate_connectors_route(
    founder_id: str,
    company_id: str = "",
    live: bool = True,
    request: Request = None,
) -> dict[str, Any]:
    """Validate all configured connectors (live check)."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="operator")

    resolved_company_id = company_id or founder_id
    result = validate_stack_connectors(
        founder_id, stack_id=resolved_company_id, live=live
    )
    return result

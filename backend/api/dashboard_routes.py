"""Dashboard CRUD + live-refresh endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

from backend.tenant_auth import require_current_founder
from backend.tools.dashboard_tools import (
    dashboard_add_element,
    dashboard_clear,
    dashboard_get,
    dashboard_remove_element,
)

router = APIRouter()


class AddElementBody(BaseModel):
    title: str
    type: str
    size: str = "medium"
    config: dict[str, Any] = {}
    section: str = ""
    order: int = -1
    refresh_interval: int = 0
    agent: str = ""
    session_id: str = ""
    data_source: Optional[dict[str, Any]] = None


@router.get("/dashboard/{founder_id}")
async def get_dashboard(founder_id: str, request: Request) -> dict:
    actor = require_current_founder(request, founder_id, min_role="viewer")
    return dashboard_get(actor.founder_id)


@router.post("/dashboard/{founder_id}/elements")
async def add_element(founder_id: str, body: AddElementBody, request: Request) -> dict:
    actor = require_current_founder(request, founder_id, min_role="operator")
    return dashboard_add_element(
        founder_id=actor.founder_id,
        title=body.title,
        type=body.type,
        size=body.size,
        config=body.config,
        section=body.section,
        order=body.order,
        refresh_interval=body.refresh_interval,
        agent=body.agent,
        session_id=body.session_id,
        data_source=body.data_source,
    )


@router.delete("/dashboard/{founder_id}/elements/{element_id}")
async def remove_element(founder_id: str, element_id: str, request: Request) -> dict:
    actor = require_current_founder(request, founder_id, min_role="operator")
    return dashboard_remove_element(actor.founder_id, element_id)


@router.delete("/dashboard/{founder_id}/elements")
async def clear_elements(founder_id: str, request: Request, section: str = "") -> dict:
    actor = require_current_founder(request, founder_id, min_role="operator")
    return dashboard_clear(actor.founder_id, section)


# Explicit allowlist of read-only tools permitted in the refresh endpoint.
# Never derive this from user-supplied data or getattr — every entry here is
# a deliberate decision that the tool is safe to call with founder-supplied params.
_REFRESH_ALLOWED_TOOLS: dict[str, Any] = {}

def _build_refresh_allowlist() -> None:
    """Populate _REFRESH_ALLOWED_TOOLS lazily on first refresh call."""
    if _REFRESH_ALLOWED_TOOLS:
        return
    try:
        from backend.tools.klaviyo_tools import klaviyo_get_metrics
        _REFRESH_ALLOWED_TOOLS["klaviyo_get_metrics"] = klaviyo_get_metrics
    except ImportError:
        pass
    try:
        from backend.tools.square_tools import square_get_revenue, square_list_bookings, square_list_services
        _REFRESH_ALLOWED_TOOLS["square_get_revenue"] = square_get_revenue
        _REFRESH_ALLOWED_TOOLS["square_list_bookings"] = square_list_bookings
        _REFRESH_ALLOWED_TOOLS["square_list_services"] = square_list_services
    except ImportError:
        pass
    try:
        from backend.tools.printful_tools import printful_get_orders, printful_get_products
        _REFRESH_ALLOWED_TOOLS["printful_get_orders"] = printful_get_orders
        _REFRESH_ALLOWED_TOOLS["printful_get_products"] = printful_get_products
    except ImportError:
        pass
    try:
        from backend.tools.yelp_tools import yelp_get_business, yelp_search_businesses
        _REFRESH_ALLOWED_TOOLS["yelp_get_business"] = yelp_get_business
        _REFRESH_ALLOWED_TOOLS["yelp_search_businesses"] = yelp_search_businesses
    except ImportError:
        pass
    try:
        from backend.tools.lemonsqueezy_tools import ls_get_sales
        _REFRESH_ALLOWED_TOOLS["ls_get_sales"] = ls_get_sales
    except ImportError:
        pass
    try:
        from backend.tools.twilio_tools import twilio_get_usage
        _REFRESH_ALLOWED_TOOLS["twilio_get_usage"] = twilio_get_usage
    except ImportError:
        pass


@router.get("/dashboard/{founder_id}/elements/{element_id}/refresh")
async def refresh_element(founder_id: str, element_id: str, request: Request) -> dict:
    """Call the element's data_source.tool and return updated config values.

    Requires operator-level access (same as writes) because this endpoint
    executes a tool on behalf of the caller.  Only explicitly allowlisted
    read-only tools are callable — arbitrary tool names are rejected.
    """
    actor = require_current_founder(request, founder_id, min_role="operator")
    founder_id = actor.founder_id

    result = dashboard_get(founder_id)
    elements = result.get("elements", [])
    element = next((e for e in elements if e.get("id") == element_id), None)
    if not element:
        raise HTTPException(status_code=404, detail="Element not found")

    ds = element.get("data_source")
    if not ds or not ds.get("tool"):
        return {"ok": True, "config": element.get("config", {}), "refreshed": False}

    tool_name = str(ds["tool"])
    params = dict(ds.get("params") or {})
    field_map = dict(ds.get("field_map") or {})

    _build_refresh_allowlist()
    tool_fn = _REFRESH_ALLOWED_TOOLS.get(tool_name)
    if tool_fn is None:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool_name}' is not permitted for dashboard refresh.",
        )

    try:
        tool_result = tool_fn(**params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tool '{tool_name}' failed: {exc}")

    # Apply field_map: start from base config, overlay only the mapped keys
    # (don't inherit stale keys from prior refreshes)
    base_config = dict(element.get("config") or {})
    if isinstance(tool_result, dict) and field_map:
        updated_config = {k: v for k, v in base_config.items() if k not in field_map.values()}
        for src_key, dst_key in field_map.items():
            if src_key in tool_result:
                updated_config[dst_key] = tool_result[src_key]
    else:
        updated_config = base_config

    return {"ok": True, "config": updated_config, "refreshed": True}

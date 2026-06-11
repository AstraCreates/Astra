"""Push notification subscription endpoints."""
from __future__ import annotations
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.tenant_auth import require_founder_access

router = APIRouter()


class SubscribeRequest(BaseModel):
    founder_id: str
    subscription: dict[str, Any]


class UnsubscribeRequest(BaseModel):
    founder_id: str
    endpoint: str


@router.post("/notifications/subscribe")
def subscribe(req: SubscribeRequest, request: Request):
    from backend.notifications.store import save_subscription
    # IDOR guard: caller may only manage their own (or their org's) endpoints.
    founder_id = require_founder_access(request, req.founder_id, min_role="viewer")
    if not req.subscription.get("endpoint"):
        raise HTTPException(400, "Missing subscription.endpoint")
    save_subscription(founder_id, req.subscription)
    return {"ok": True}


@router.delete("/notifications/subscribe")
def unsubscribe(req: UnsubscribeRequest, request: Request):
    from backend.notifications.store import remove_subscription
    founder_id = require_founder_access(request, req.founder_id, min_role="viewer")
    remove_subscription(founder_id, req.endpoint)
    return {"ok": True}


@router.get("/notifications/vapid-public-key")
def vapid_public_key():
    return {"publicKey": os.environ.get("VAPID_PUBLIC_KEY", "")}

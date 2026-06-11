"""Push notification subscription endpoints."""
from __future__ import annotations
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class SubscribeRequest(BaseModel):
    founder_id: str
    subscription: dict[str, Any]


class UnsubscribeRequest(BaseModel):
    founder_id: str
    endpoint: str


@router.post("/notifications/subscribe")
def subscribe(req: SubscribeRequest):
    from backend.notifications.store import save_subscription
    if not req.subscription.get("endpoint"):
        raise HTTPException(400, "Missing subscription.endpoint")
    save_subscription(req.founder_id, req.subscription)
    return {"ok": True}


@router.delete("/notifications/subscribe")
def unsubscribe(req: UnsubscribeRequest):
    from backend.notifications.store import remove_subscription
    remove_subscription(req.founder_id, req.endpoint)
    return {"ok": True}


@router.get("/notifications/vapid-public-key")
def vapid_public_key():
    return {"publicKey": os.environ.get("VAPID_PUBLIC_KEY", "")}

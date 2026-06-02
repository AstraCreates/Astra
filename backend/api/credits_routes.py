"""Credits API routes for Astra.

Endpoints:
  GET  /api/credits?founder_id=x         — fetch balance + recent transactions
  POST /api/credits/deduct               — deduct credits (internal / agent use)
  POST /api/credits/add                  — add credits (admin or Stripe webhook)
  POST /api/credits/checkout             — create Stripe checkout for credit purchase
  POST /api/credits/webhook              — Stripe webhook (checkout.session.completed)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

credits_router = APIRouter()

# ── Credit packs ───────────────────────────────────────────────────────────────

_PACKS: dict[str, dict] = {
    "starter": {"credits": 50,   "price_cents": 499,  "label": "50 credits — $4.99"},
    "pro":     {"credits": 200,  "price_cents": 1499, "label": "200 credits — $14.99"},
    "scale":   {"credits": 1000, "price_cents": 4999, "label": "1000 credits — $49.99"},
}

# ── Schemas ────────────────────────────────────────────────────────────────────

class DeductRequest(BaseModel):
    founder_id: str
    amount: int
    description: str
    session_id: str = ""


class AddRequest(BaseModel):
    founder_id: str
    amount: int
    type: str  # "grant" | "purchase" | "refund"
    description: str


class CheckoutRequest(BaseModel):
    founder_id: str
    pack: str  # "starter" | "pro" | "scale"


# ── Routes ─────────────────────────────────────────────────────────────────────

@credits_router.get("/credits")
async def get_credits_route(founder_id: str = ""):
    """Return the founder's credit balance and last 20 transactions."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")

    from backend.credits.store import get_credits
    data = get_credits(founder_id)
    return {
        "founder_id": data["founder_id"],
        "balance": data["balance"],
        "total_granted": data["total_granted"],
        "total_purchased": data["total_purchased"],
        "total_used": data["total_used"],
        "transactions": data["transactions"][-20:],
    }


@credits_router.post("/credits/deduct")
async def deduct_credits_route(body: DeductRequest):
    """Deduct credits from a founder's balance. Returns 402 if insufficient."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be a positive integer")

    from backend.credits.store import deduct_credits
    try:
        data = deduct_credits(
            body.founder_id,
            body.amount,
            body.description,
            session_id=body.session_id or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc))

    return {"balance": data["balance"], "deducted": body.amount}


@credits_router.post("/credits/add")
async def add_credits_route(body: AddRequest):
    """Add credits to a founder's balance (admin grant or Stripe purchase)."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be a positive integer")
    if body.type not in ("grant", "purchase", "refund"):
        raise HTTPException(status_code=400, detail="type must be 'grant', 'purchase', or 'refund'")

    from backend.credits.store import add_credits
    try:
        data = add_credits(
            body.founder_id,
            body.amount,
            body.type,
            body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"balance": data["balance"]}


@credits_router.post("/credits/checkout")
async def credits_checkout(body: CheckoutRequest, request: Request):
    """Create a Stripe Checkout session for a credit pack purchase.

    Packs:
      starter  — 50 credits  / $4.99
      pro      — 200 credits / $14.99
      scale    — 1000 credits / $49.99
    """
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")

    pack = _PACKS.get(body.pack)
    if not pack:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown pack '{body.pack}'. Valid options: {list(_PACKS.keys())}",
        )

    from backend.config import settings
    import stripe  # type: ignore

    stripe.api_key = settings.stripe_secret_key
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured on this server.")

    frontend_base = settings.frontend_url.rstrip("/")
    success_url = f"{frontend_base}/credits?purchased=1&pack={body.pack}"
    cancel_url = f"{frontend_base}/credits?cancelled=1"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": pack["price_cents"],
                        "product_data": {
                            "name": f"Astra Credits — {pack['label']}",
                            "description": f"{pack['credits']} Astra AI credits",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "founder_id": body.founder_id,
                "pack": body.pack,
                "credits": str(pack["credits"]),
            },
        )
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        logger.error("Stripe checkout creation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return {"checkout_url": session.url}


@credits_router.post("/credits/webhook")
async def credits_stripe_webhook(request: Request):
    """Stripe webhook endpoint — handles checkout.session.completed to grant purchased credits."""
    from backend.config import settings
    import stripe  # type: ignore

    stripe.api_key = settings.stripe_secret_key

    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    webhook_secret = settings.stripe_webhook_secret
    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(body, sig, webhook_secret)
        except stripe.error.SignatureVerificationError:  # type: ignore[attr-defined]
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Webhook parse error: {exc}")
    else:
        # No secret configured — accept without verification (dev/test only)
        try:
            event = json.loads(body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type") if isinstance(event, dict) else event["type"]

    if event_type != "checkout.session.completed":
        return {"ok": True, "skipped": event_type}

    obj = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else event["data"]["object"]
    )
    metadata = obj.get("metadata", {})
    founder_id = metadata.get("founder_id", "")
    pack_name = metadata.get("pack", "")
    credits_str = metadata.get("credits", "")

    if not founder_id or not credits_str:
        logger.warning("credits webhook: missing metadata in session %s", obj.get("id"))
        return {"ok": True, "warning": "missing metadata"}

    try:
        credits_amount = int(credits_str)
    except ValueError:
        logger.error("credits webhook: invalid credits value %r", credits_str)
        return {"ok": True, "warning": "invalid credits value"}

    from backend.credits.store import add_credits
    try:
        data = add_credits(
            founder_id,
            credits_amount,
            "purchase",
            f"Purchased {credits_amount} credits ({pack_name} pack)",
            session_id=obj.get("id", ""),
        )
        logger.info(
            "Credits webhook: +%d credits for %s (session=%s, new_balance=%d)",
            credits_amount, founder_id, obj.get("id"), data["balance"],
        )
    except Exception as exc:
        logger.error("Credits webhook: add_credits failed for %s: %s", founder_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"ok": True}

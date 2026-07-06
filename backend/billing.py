"""Astra platform billing webhook handling.

Founder-connected Stripe accounts handle customer revenue. This module handles
Astra's own subscription billing so workspace entitlements change when Stripe
subscription events arrive.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import requests

from backend.accounts import PLANS, append_audit_event, find_org_by_stripe, get_or_create_org, update_subscription


STRIPE_API = "https://api.stripe.com/v1"


def verify_stripe_signature(body: bytes, signature_header: str, secret: str, tolerance_seconds: int = 300) -> bool:
    """Verify Stripe webhook signature using the v1 HMAC scheme."""
    if not secret:
        return False
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts.setdefault(key, []).append(value)
    timestamp_values = parts.get("t") or []
    signatures = parts.get("v1") or []
    if not timestamp_values or not signatures:
        return False
    try:
        timestamp = int(timestamp_values[0])
    except ValueError:
        return False
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False
    signed_payload = f"{timestamp}.{body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def apply_platform_billing_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Stripe platform billing event to workspace entitlement state."""
    event_type = str(payload.get("type") or "")
    event_id = str(payload.get("id") or "")
    data = ((payload.get("data") or {}).get("object") or {})
    if not isinstance(data, dict):
        data = {}

    if event_type.startswith("customer.subscription."):
        return _apply_subscription_event(event_type, event_id, data)
    if event_type in {"invoice.paid", "invoice.payment_failed", "checkout.session.completed"}:
        return _apply_billing_status_event(event_type, event_id, data)
    return {"ok": True, "handled": False, "event_type": event_type, "event_id": event_id}


def billing_config_status() -> dict[str, Any]:
    """Return platform billing configuration without exposing secrets."""
    from backend.config import settings

    prices = _price_ids()
    paid_plans = ["starter", "team", "scale"]
    missing_prices = [plan for plan in paid_plans if not prices.get(plan)]
    return {
        "stripe_configured": bool(settings.stripe_secret_key),
        "portal_available": bool(settings.stripe_secret_key),
        "checkout_available": bool(settings.stripe_secret_key and not missing_prices),
        "plans": {
            plan_id: {
                **plan,
                "price_configured": bool(prices.get(plan_id)) if plan_id != "beta" else True,
                "self_serve": plan_id != "beta",
            }
            for plan_id, plan in PLANS.items()
        },
        "missing_price_ids": missing_prices,
    }


def create_checkout_session(
    org_id: str,
    *,
    actor_id: str,
    plan: str,
    success_url: str = "",
    cancel_url: str = "",
    customer_email: str = "",
) -> dict[str, Any]:
    """Create a Stripe Checkout session for an Astra workspace subscription."""
    from backend.config import settings

    plan = plan.lower().strip()
    if plan not in {"starter", "team", "scale"}:
        return {"ok": False, "setup_required": False, "error": f"Unsupported paid plan: {plan}."}
    if not settings.stripe_secret_key:
        return {"ok": False, "setup_required": True, "error": "STRIPE_SECRET_KEY is not configured."}
    price_id = _price_ids().get(plan, "")
    if not price_id:
        return {"ok": False, "setup_required": True, "error": f"Stripe price id for {plan} is not configured."}

    org = get_or_create_org(org_id, org_id)
    customer_id = str((org.get("subscription") or {}).get("stripe_customer_id") or "")
    if not customer_id:
        customer = _stripe_post(
            "/customers",
            {
                "metadata[org_id]": org_id,
                "metadata[owner_id]": org.get("owner_id") or org_id,
                **({"email": customer_email} if customer_email else {}),
            },
            settings.stripe_secret_key,
        )
        customer_id = str(customer.get("id") or "")
        update_subscription(org_id, actor_id=actor_id, stripe_customer_id=customer_id)

    session = _stripe_post(
        "/checkout/sessions",
        {
            "mode": "subscription",
            "customer": customer_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url or f"{settings.frontend_url.rstrip('/')}/settings?billing=success",
            "cancel_url": cancel_url or f"{settings.frontend_url.rstrip('/')}/settings?billing=cancelled",
            "metadata[org_id]": org_id,
            "metadata[plan]": plan,
            "subscription_data[metadata][org_id]": org_id,
            "subscription_data[metadata][plan]": plan,
        },
        settings.stripe_secret_key,
    )
    append_audit_event(org_id, actor_id=actor_id, action="billing.checkout.created", payload={
        "plan": plan,
        "stripe_session_id": session.get("id"),
    })
    return {
        "ok": True,
        "kind": "checkout",
        "plan": plan,
        "url": session.get("url"),
        "session_id": session.get("id"),
        "customer_id": customer_id,
    }


def create_customer_portal_session(org_id: str, *, actor_id: str, return_url: str = "") -> dict[str, Any]:
    """Create a Stripe Billing Portal session for a workspace."""
    from backend.config import settings

    if not settings.stripe_secret_key:
        return {"ok": False, "setup_required": True, "error": "STRIPE_SECRET_KEY is not configured."}
    org = get_or_create_org(org_id, org_id)
    customer_id = str((org.get("subscription") or {}).get("stripe_customer_id") or "")
    if not customer_id:
        return {"ok": False, "setup_required": False, "error": "Workspace has no Stripe customer yet. Start checkout first."}
    session = _stripe_post(
        "/billing_portal/sessions",
        {
            "customer": customer_id,
            "return_url": return_url or f"{settings.frontend_url.rstrip('/')}/settings?billing=portal",
        },
        settings.stripe_secret_key,
    )
    append_audit_event(org_id, actor_id=actor_id, action="billing.portal.created", payload={
        "stripe_session_id": session.get("id"),
    })
    return {
        "ok": True,
        "kind": "portal",
        "url": session.get("url"),
        "session_id": session.get("id"),
        "customer_id": customer_id,
    }


def _price_ids() -> dict[str, str]:
    from backend.config import settings

    return {
        "starter": settings.stripe_price_starter,
        "team": settings.stripe_price_team,
        "scale": settings.stripe_price_scale,
    }


def _stripe_post(path: str, data: dict[str, Any], secret_key: str) -> dict[str, Any]:
    response = requests.post(
        f"{STRIPE_API}{path}",
        data={key: value for key, value in data.items() if value is not None},
        auth=(secret_key, ""),
        timeout=20,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400:
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else response.text
        raise RuntimeError(message or f"Stripe request failed with HTTP {response.status_code}")
    return payload


def _apply_subscription_event(event_type: str, event_id: str, sub: dict[str, Any]) -> dict[str, Any]:
    subscription_id = str(sub.get("id") or "")
    customer_id = _customer_id(sub)
    metadata = sub.get("metadata") or {}
    org_id = str(metadata.get("org_id") or metadata.get("founder_id") or "")
    org = get_or_create_org(org_id or customer_id or subscription_id) if org_id else find_org_by_stripe(customer_id, subscription_id)
    if not org:
        org = get_or_create_org(customer_id or subscription_id or "stripe_unknown")
    resolved_org_id = org["org_id"]
    plan = _plan_from_subscription(sub)
    status = _subscription_status(event_type, str(sub.get("status") or "active"))
    current_period_end = _iso_from_epoch(sub.get("current_period_end"))

    updated = update_subscription(
        resolved_org_id,
        actor_id="stripe",
        plan=plan,
        status=status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        current_period_end=current_period_end,
    )
    append_audit_event(resolved_org_id, actor_id="stripe", action=f"stripe.{event_type}", payload={
        "event_id": event_id,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "plan": plan,
        "status": status,
    })
    return {"ok": True, "handled": True, "event_type": event_type, "org": updated}


def _apply_billing_status_event(event_type: str, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
    customer_id = _customer_id(obj)
    subscription_id = str(obj.get("subscription") or "")
    metadata = obj.get("metadata") or {}
    org_id = str(metadata.get("org_id") or metadata.get("founder_id") or "")
    org = get_or_create_org(org_id or customer_id or subscription_id) if org_id else find_org_by_stripe(customer_id, subscription_id)
    if not org:
        return {"ok": True, "handled": False, "event_type": event_type, "event_id": event_id, "reason": "No matching org."}
    status = "active" if event_type in {"invoice.paid", "checkout.session.completed"} else "past_due"
    updated = update_subscription(
        org["org_id"],
        actor_id="stripe",
        status=status,
        stripe_customer_id=customer_id or org.get("subscription", {}).get("stripe_customer_id", ""),
        stripe_subscription_id=subscription_id or org.get("subscription", {}).get("stripe_subscription_id", ""),
    )
    append_audit_event(org["org_id"], actor_id="stripe", action=f"stripe.{event_type}", payload={
        "event_id": event_id,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "status": status,
    })
    return {"ok": True, "handled": True, "event_type": event_type, "org": updated}


def _customer_id(obj: dict[str, Any]) -> str:
    customer = obj.get("customer") or ""
    if isinstance(customer, dict):
        return str(customer.get("id") or "")
    return str(customer or "")


def _subscription_status(event_type: str, stripe_status: str) -> str:
    if event_type == "customer.subscription.deleted":
        return "canceled"
    if stripe_status in {"active", "trialing"}:
        return "active"
    if stripe_status in {"past_due", "unpaid"}:
        return "past_due"
    if stripe_status in {"canceled", "incomplete_expired"}:
        return "canceled"
    return stripe_status or "active"


def _plan_from_subscription(sub: dict[str, Any]) -> str:
    metadata = sub.get("metadata") or {}
    plan = str(metadata.get("plan") or metadata.get("astra_plan") or "").lower()
    if plan in {"starter", "team", "scale", "beta"}:
        return plan
    try:
        items = ((sub.get("items") or {}).get("data") or [])
        for item in items:
            price = item.get("price") or {}
            lookup = str(price.get("lookup_key") or price.get("nickname") or "").lower()
            for candidate in ("scale", "team", "starter", "beta"):
                if candidate in lookup:
                    return candidate
    except Exception:
        pass
    return "team"


def _iso_from_epoch(value: Any) -> str | None:
    try:
        if not value:
            return None
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(value)))
    except Exception:
        return None


def fake_signed_payload(payload: dict[str, Any], secret: str, timestamp: int | None = None) -> tuple[bytes, str]:
    """Helper for local tests."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ts = timestamp or int(time.time())
    digest = hmac.new(secret.encode("utf-8"), f"{ts}.{body.decode('utf-8')}".encode("utf-8"), hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={digest}"

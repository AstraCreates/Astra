"""
Stripe Standard Connect — OAuth-based account linking.
Each founder connects their own Stripe account via OAuth.
Astra stores their access_token + stripe_user_id to read their data.

Required env vars:
  STRIPE_SECRET_KEY   — Astra's platform secret key
  STRIPE_CLIENT_ID    — Astra's Connect client_id (ca_xxx)
"""
import asyncio
import hashlib
import logging
import os
import threading
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Durable idempotency for side-effecting Stripe calls ────────────────────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." The 4 functions below
# that call requests.post() (create_stripe_product, create_stripe_price,
# create_stripe_payment_link, register_stripe_webhook) route through this
# helper so a retried Temporal activity can't create duplicate Stripe
# products/prices/payment links/webhooks.

def _run_async(coro):
    """Run an async coroutine from sync code, safely, whether or not the
    calling thread already has a running event loop.

    These Stripe functions are called synchronously from a lot of places —
    some inside a running asyncio event loop (e.g. FastAPI route handlers in
    backend/api/routes.py call create_product_with_payment_link() directly,
    without await or to_thread), some from plain worker threads. asyncio.run()
    raises if a loop is already running on the current thread, so when one is
    detected we run the coroutine to completion on a dedicated helper thread
    instead of blocking/crashing the caller's loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _execute_with_idempotency(
    *,
    tool: str,
    run_id: str,
    step_id: str,
    args: dict[str, Any],
    http_call: Callable[[str], dict],
) -> dict:
    """Route a Stripe side-effecting call through Astra's durable action/receipt
    control plane (backend.control_plane.action_executor.execute_external_action)
    AND pass the computed idempotency key to Stripe's own Idempotency-Key HTTP
    header, so retries are protected at both layers: Astra's receipt (a retry
    of the same run/step/args replays the stored result without calling Stripe
    again) and, if a crash happens between a successful Stripe call and the
    receipt being persisted, Stripe's own native dedup on the header value.

    `http_call` is a zero-network-yet closure that takes the idempotency key
    and performs the actual `requests.post(...)` call, returning the parsed
    result dict this function already promises to its callers.

    If no run_id is available (a direct/manual call outside an agent run —
    e.g. a plain API route that doesn't thread run context through), we can't
    key a durable Astra receipt to anything, so we skip that layer entirely
    and fall back to a content-derived idempotency key sent to Stripe. That
    still protects against exact-duplicate resubmission within Stripe's own
    idempotency window, just without Astra's durable, cross-process replay
    guarantee.
    """
    from backend.control_plane.action_executor import canonicalize_tool_args

    if not run_id:
        fallback_key = hashlib.sha256(
            canonicalize_tool_args({"tool": tool, "args": args}).encode("utf-8")
        ).hexdigest()
        return http_call(fallback_key)

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        execute_external_action,
        get_default_repo_bundle,
    )

    # action_id feeds into the idempotency key hash (see compute_action_hashes).
    # A fresh random id per call would defeat retries, so derive it
    # deterministically from the same inputs that make the call idempotent —
    # a retry with the same run_id/step_id/tool/args reuses the same action
    # and replays its receipt instead of calling Stripe again.
    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::{tool}::{canonical_args}".encode("utf-8")).hexdigest()

    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, idempotency_key: str) -> dict:
        return http_call(idempotency_key)

    result = _run_async(execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or tool,
            action_id=action_id,
            tool=tool,
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    ))
    return dict(result.provider_result or {})


def _platform_stripe():
    """Stripe client using Astra's platform secret key."""
    try:
        import stripe as _s
    except ImportError:
        raise RuntimeError("stripe not installed — run: pip install stripe")
    try:
        from backend.config import settings
        key = settings.stripe_secret_key
    except Exception:
        key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY not set in environment")
    _s.api_key = key
    return _s


# ── OAuth ─────────────────────────────────────────────────────────────────────

def get_oauth_url(founder_id: str, redirect_uri: str) -> str:
    """
    Return the Stripe OAuth URL that sends the founder to connect/create their Stripe account.
    redirect_uri must be registered in your Stripe Connect settings.
    """
    client_id = os.environ.get("STRIPE_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError("STRIPE_CLIENT_ID not set in environment")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": redirect_uri,
        "state": founder_id,
        "stripe_user[email]": "",  # prefill hint — filled by caller if known
    }
    from urllib.parse import urlencode
    return f"https://connect.stripe.com/oauth/authorize?{urlencode(params)}"


def get_oauth_url_with_email(founder_id: str, redirect_uri: str, email: str = "") -> str:
    """OAuth URL with email prefilled so the founder can create their account faster."""
    try:
        from backend.config import settings
        client_id = settings.stripe_client_id
    except Exception:
        client_id = os.environ.get("STRIPE_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError("STRIPE_CLIENT_ID not set in environment")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": redirect_uri,
        "state": founder_id,
    }
    if email:
        params["stripe_user[email]"] = email
    from urllib.parse import urlencode
    return f"https://connect.stripe.com/oauth/authorize?{urlencode(params)}"


def exchange_oauth_code(code: str) -> dict:
    """
    Exchange a Stripe OAuth code for an access_token + stripe_user_id.
    """
    try:
        from backend.config import settings
        secret_key = settings.stripe_secret_key
    except Exception:
        secret_key = os.environ.get("STRIPE_SECRET_KEY", "")

    try:
        import requests as _req
        resp = _req.post(
            "https://connect.stripe.com/oauth/token",
            data={"grant_type": "authorization_code", "code": code},
            auth=(secret_key, ""),
            timeout=15,
        )
        body = resp.json()
        if resp.status_code != 200:
            logger.error("Stripe OAuth exchange HTTP %s: %s", resp.status_code, body)
            return {"error": body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"}
        return {
            "access_token": body.get("access_token"),
            "stripe_user_id": body.get("stripe_user_id"),
            "livemode": body.get("livemode", False),
            "token_type": body.get("token_type", "bearer"),
        }
    except Exception as e:
        logger.error("Stripe OAuth code exchange failed: %s", e, exc_info=True)
        return {"error": str(e)}


# ── Account info ──────────────────────────────────────────────────────────────

def get_account_status(access_token: str) -> dict:
    """
    Check the founder's Stripe account status using their access token.
    Uses direct HTTP — avoids Stripe SDK version issues.
    """
    try:
        import requests as _req
        resp = _req.get(
            "https://api.stripe.com/v1/account",
            auth=(access_token, ""),
            timeout=15,
        )
        account = resp.json()
        if resp.status_code != 200:
            return {"connected": False, "error": account.get("error", {}).get("message", f"HTTP {resp.status_code}")}
        return {
            "connected": True,
            "charges_enabled": account.get("charges_enabled", False),
            "payouts_enabled": account.get("payouts_enabled", False),
            "email": account.get("email", ""),
            "livemode": account.get("livemode", False),
            "country": account.get("country", ""),
            "default_currency": account.get("default_currency", "usd"),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Revenue data ──────────────────────────────────────────────────────────────

def get_stripe_data(access_token: str) -> dict:
    """
    Pull balance, charges, and payouts for the founder using their access token.
    Uses direct HTTP — avoids Stripe SDK version issues.
    """
    try:
        import requests as _req
        auth = (access_token, "")
        balance_resp = _req.get("https://api.stripe.com/v1/balance", auth=auth, timeout=15)
        charges_resp = _req.get("https://api.stripe.com/v1/charges?limit=20", auth=auth, timeout=15)
        payouts_resp = _req.get("https://api.stripe.com/v1/payouts?limit=10", auth=auth, timeout=15)

        if balance_resp.status_code != 200:
            return {"error": balance_resp.json().get("error", {}).get("message", "Failed to fetch balance")}

        balance = balance_resp.json()
        charges_data = charges_resp.json()
        payouts_data = payouts_resp.json()
    except Exception as e:
        return {"error": str(e)}

    currency = balance["available"][0]["currency"] if balance.get("available") else "usd"
    available = sum(b["amount"] for b in balance.get("available", []))
    pending = sum(b["amount"] for b in balance.get("pending", []))

    charges = [
        {
            "id": c["id"],
            "amount": c["amount"],
            "currency": c.get("currency", currency),
            "status": c["status"],
            "description": c.get("description"),
            "customer_email": c.get("receipt_email"),
            "created": c["created"],
        }
        for c in charges_data.get("data", [])
    ]

    payouts = [
        {
            "id": p["id"],
            "amount": p["amount"],
            "currency": p.get("currency", currency),
            "status": p["status"],
            "arrival_date": p["arrival_date"],
            "created": p["created"],
        }
        for p in payouts_data.get("data", [])
    ]

    succeeded = [c for c in charges if c["status"] == "succeeded"]
    total_revenue = sum(c["amount"] for c in succeeded)

    now = datetime.utcnow()
    month_start = int(datetime(now.year, now.month, 1).timestamp())
    mrr = sum(c["amount"] for c in succeeded if c["created"] >= month_start)

    return {
        "balance": {"available": available, "pending": pending, "currency": currency},
        "charges": charges,
        "payouts": payouts,
        "mrr": mrr,
        "total_revenue": total_revenue,
        "currency": currency,
    }


# ── EIN / Business upgrade ────────────────────────────────────────────────────
# With Standard Connect the founder owns their Stripe account independently.
# After LLC filing + EIN receipt, we guide them to update their Stripe account
# themselves, and record the upgrade in our credentials store.
# TODO: Wire auto-notification into the NWRA LLC filing confirmation flow.

def record_ein_upgrade(founder_id: str, ein: str, business_name: str) -> dict:
    """
    Record that the founder has upgraded their Stripe account to their LLC/EIN.
    With Standard Connect, Stripe account updates are done by the founder on stripe.com.
    This just marks the upgrade as complete in Astra's records.
    """
    return {
        "recorded": True,
        "founder_id": founder_id,
        "ein_last4": ein[-4:] if len(ein) >= 4 else ein,
        "business_name": business_name,
    }


# ── Products & Prices ─────────────────────────────────────────────────────────

def create_stripe_product(
    access_token: str,
    name: str,
    description: str = "",
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Create a Stripe Product in the founder's account.
    Returns {product_id, name, created}.

    run_id (or session_id, an alias so callers dispatched from
    backend/core/agent.py's tool-call injection — which auto-fills a
    `session_id` param — get it for free) keys a durable Astra action/receipt
    to this call so a retry replays instead of creating a duplicate product;
    it also seeds the idempotency key sent to Stripe's own Idempotency-Key
    header. See _execute_with_idempotency for the no-run_id fallback.
    """
    try:
        import requests as _req

        def _post(idempotency_key: str) -> dict:
            resp = _req.post(
                "https://api.stripe.com/v1/products",
                data={"name": name, "description": description},
                auth=(access_token, ""),
                headers={"Idempotency-Key": idempotency_key},
                timeout=15,
            )
            body = resp.json()
            if resp.status_code != 200:
                return {"error": body.get("error", {}).get("message", f"HTTP {resp.status_code}")}
            return {"product_id": body["id"], "name": body["name"], "created": True}

        return _execute_with_idempotency(
            tool="create_stripe_product",
            run_id=run_id or session_id,
            step_id=step_id or "create_stripe_product",
            args={"name": name, "description": description},
            http_call=_post,
        )
    except Exception as e:
        return {"error": str(e)}


def create_stripe_price(
    access_token: str,
    product_id: str,
    amount: int,          # in cents
    currency: str = "usd",
    interval: str = "",   # "month", "year", or "" for one-time
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Create a Stripe Price for a Product.
    Returns {price_id, amount, currency, interval, created}.

    See create_stripe_product for the run_id/session_id idempotency contract.
    """
    try:
        import requests as _req
        data: dict = {
            "product": product_id,
            "unit_amount": str(amount),
            "currency": currency.lower(),
        }
        if interval in ("month", "year", "week", "day"):
            data["recurring[interval]"] = interval

        def _post(idempotency_key: str) -> dict:
            resp = _req.post(
                "https://api.stripe.com/v1/prices",
                data=data,
                auth=(access_token, ""),
                headers={"Idempotency-Key": idempotency_key},
                timeout=15,
            )
            body = resp.json()
            if resp.status_code != 200:
                return {"error": body.get("error", {}).get("message", f"HTTP {resp.status_code}")}
            return {
                "price_id": body["id"],
                "amount": amount,
                "currency": currency,
                "interval": interval or "one_time",
                "created": True,
            }

        return _execute_with_idempotency(
            tool="create_stripe_price",
            run_id=run_id or session_id,
            step_id=step_id or "create_stripe_price",
            args={"product_id": product_id, "amount": amount, "currency": currency, "interval": interval},
            http_call=_post,
        )
    except Exception as e:
        return {"error": str(e)}


def create_stripe_payment_link(
    access_token: str,
    price_id: str,
    quantity: int = 1,
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Create a Stripe Payment Link for a Price.
    Returns {url, payment_link_id}.

    See create_stripe_product for the run_id/session_id idempotency contract.
    """
    try:
        import requests as _req

        def _post(idempotency_key: str) -> dict:
            resp = _req.post(
                "https://api.stripe.com/v1/payment_links",
                data={"line_items[0][price]": price_id, "line_items[0][quantity]": str(quantity)},
                auth=(access_token, ""),
                headers={"Idempotency-Key": idempotency_key},
                timeout=15,
            )
            body = resp.json()
            if resp.status_code != 200:
                return {"error": body.get("error", {}).get("message", f"HTTP {resp.status_code}")}
            return {"url": body["url"], "payment_link_id": body["id"], "active": body.get("active", True)}

        return _execute_with_idempotency(
            tool="create_stripe_payment_link",
            run_id=run_id or session_id,
            step_id=step_id or "create_stripe_payment_link",
            args={"price_id": price_id, "quantity": quantity},
            http_call=_post,
        )
    except Exception as e:
        return {"error": str(e)}


def list_stripe_products(access_token: str) -> dict:
    """List all active products and their prices/payment links."""
    try:
        import requests as _req
        auth = (access_token, "")
        products_resp = _req.get("https://api.stripe.com/v1/products?limit=20&active=true", auth=auth, timeout=15)
        prices_resp = _req.get("https://api.stripe.com/v1/prices?limit=50&active=true", auth=auth, timeout=15)
        links_resp = _req.get("https://api.stripe.com/v1/payment_links?limit=50", auth=auth, timeout=15)

        if products_resp.status_code != 200:
            return {"error": "Failed to fetch products"}

        products = products_resp.json().get("data", [])
        prices = prices_resp.json().get("data", [])
        links = links_resp.json().get("data", [])

        price_map: dict = {}
        for p in prices:
            pid = p.get("product")
            if pid not in price_map:
                price_map[pid] = []
            price_map[pid].append(p)

        link_map: dict = {}
        for l in links:
            items = l.get("line_items", {}).get("data", [])
            for item in items:
                price_id = item.get("price", {}).get("id") if isinstance(item.get("price"), dict) else item.get("price")
                if price_id:
                    link_map[price_id] = l.get("url")

        result = []
        for prod in products:
            prod_prices = price_map.get(prod["id"], [])
            result.append({
                "product_id": prod["id"],
                "name": prod["name"],
                "description": prod.get("description", ""),
                "created": prod["created"],
                "prices": [
                    {
                        "price_id": pr["id"],
                        "amount": pr.get("unit_amount", 0),
                        "currency": pr.get("currency", "usd"),
                        "interval": pr.get("recurring", {}).get("interval") if pr.get("recurring") else None,
                        "payment_link": link_map.get(pr["id"]),
                    }
                    for pr in prod_prices
                ],
            })
        return {"products": result, "total": len(result)}
    except Exception as e:
        return {"error": str(e)}


def create_product_with_payment_link(
    name: str,
    description: str,
    amount: int,
    founder_id: str = "",
    access_token: str = "",
    currency: str = "usd",
    interval: str = "",
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Full flow: create Product → Price → Payment Link in one call.
    Used by agents to set up pricing from research findings.
    Returns {product_id, price_id, payment_link_url, name, amount, currency, interval}.

    run_id/session_id and step_id are threaded through to each of the 3 sub-calls
    (with distinct step suffixes, since they're 3 separate idempotent actions,
    not one) — see create_stripe_product for the idempotency contract.
    """
    run_id = run_id or session_id
    base_step = step_id or "create_product_with_payment_link"
    # Load per-founder Stripe token from credentials store if access_token not provided
    if not access_token and founder_id:
        try:
            from backend.provisioning.credentials_store import load_credentials
            creds = load_credentials(founder_id, "stripe")
            if creds:
                access_token = creds.get("access_token") or creds.get("secret_key") or ""
        except Exception:
            pass
    # No real Stripe key connected (common in dev) — return a clean skip instead of
    # letting the agent hammer the API with guessed keys and emit repeated errors.
    tok = str(access_token or "")
    if not tok.startswith(("sk_live_", "sk_test_", "rk_live_", "rk_test_")) or "YOUR" in tok or "*" in tok:
        return {
            "skipped": True,
            "payment_link_url": None,
            "reason": "No Stripe account connected. Connect Stripe in Integrations to create a real payment link; the pricing plan is recorded for later.",
            "name": name, "amount": amount, "currency": currency, "interval": interval or "one_time",
        }
    product = create_stripe_product(
        access_token, name, description,
        run_id=run_id, step_id=f"{base_step}:product",
    )
    if "error" in product:
        return product

    price = create_stripe_price(
        access_token, product["product_id"], amount, currency, interval,
        run_id=run_id, step_id=f"{base_step}:price",
    )
    if "error" in price:
        return price

    link = create_stripe_payment_link(
        access_token, price["price_id"],
        run_id=run_id, step_id=f"{base_step}:payment_link",
    )
    if "error" in link:
        return {**product, **price, "payment_link_url": None, "payment_link_error": link["error"]}

    return {
        "product_id": product["product_id"],
        "price_id": price["price_id"],
        "payment_link_url": link["url"],
        "name": name,
        "amount": amount,
        "currency": currency,
        "interval": interval or "one_time",
        "created": True,
    }


# ── Webhooks ──────────────────────────────────────────────────────────────────

def register_stripe_webhook(
    access_token: str,
    endpoint_url: str,
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Register a webhook endpoint on the founder's Stripe account.
    Listens for payment, subscription, and payout events.
    Returns {webhook_id, secret, url}.

    See create_stripe_product for the run_id/session_id idempotency contract.
    """
    events = [
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "charge.succeeded",
        "charge.failed",
        "charge.refunded",
        "customer.subscription.created",
        "customer.subscription.deleted",
        "customer.subscription.updated",
        "payout.paid",
        "payout.failed",
    ]
    try:
        import requests as _req
        data: dict = {"url": endpoint_url, "enabled_events[]": events}

        def _post(idempotency_key: str) -> dict:
            resp = _req.post(
                "https://api.stripe.com/v1/webhook_endpoints",
                data=data,
                auth=(access_token, ""),
                headers={"Idempotency-Key": idempotency_key},
                timeout=15,
            )
            body = resp.json()
            if resp.status_code != 200:
                return {"error": body.get("error", {}).get("message", f"HTTP {resp.status_code}")}
            return {
                "webhook_id": body["id"],
                "secret": body.get("secret", ""),
                "url": body["url"],
                "registered": True,
            }

        return _execute_with_idempotency(
            tool="register_stripe_webhook",
            run_id=run_id or session_id,
            step_id=step_id or "register_stripe_webhook",
            args={"endpoint_url": endpoint_url},
            http_call=_post,
        )
    except Exception as e:
        return {"error": str(e)}


def store_webhook_event(founder_id: str, event: dict) -> None:
    """Store a Stripe webhook event for the founder."""
    import json
    from pathlib import Path
    events_path = Path(__file__).parent.parent.parent / ".credentials" / f"{founder_id}_events.json"
    events: list = []
    if events_path.exists():
        try:
            events = json.loads(events_path.read_text())
        except Exception:
            events = []
    events.insert(0, event)
    events = events[:50]  # keep last 50
    events_path.write_text(json.dumps(events, indent=2))


def get_webhook_events(founder_id: str, limit: int = 20) -> list:
    """Get stored webhook events for the founder."""
    import json
    from pathlib import Path
    events_path = Path(__file__).parent.parent.parent / ".credentials" / f"{founder_id}_events.json"
    if not events_path.exists():
        return []
    try:
        return json.loads(events_path.read_text())[:limit]
    except Exception:
        return []

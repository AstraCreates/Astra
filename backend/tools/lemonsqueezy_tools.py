"""Lemon Squeezy API — digital products, sales, discounts."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://api.lemonsqueezy.com/v1"
_TIMEOUT = 15


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.lemonsqueezy_api_key}", "Accept": "application/vnd.api+json"}


def _not_configured() -> dict:
    return {"error": "LEMONSQUEEZY_API_KEY not configured"}


def _get(path: str, params: dict | None = None) -> dict:
    if not settings.lemonsqueezy_api_key:
        return _not_configured()
    try:
        r = requests.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("LemonSqueezy GET %s failed: %s", path, e)
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    if not settings.lemonsqueezy_api_key:
        return _not_configured()
    try:
        r = requests.post(
            f"{_BASE}{path}",
            headers={**_headers(), "Content-Type": "application/vnd.api+json"},
            json=body,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("LemonSqueezy POST %s failed: %s", path, e)
        return {"error": str(e)}


def _get_first_store_id() -> str | None:
    """Get the first store ID for the account."""
    data = _get("/stores")
    stores = (data.get("data") or [])
    return stores[0].get("id") if stores else None


def ls_create_product(name: str, description: str, price_cents: int, store_id: str = "") -> dict:
    """Create a digital product in Lemon Squeezy.

    price_cents: price in cents (e.g. 4900 = $49.00)
    store_id: optional; auto-detected from account if omitted
    """
    sid = store_id or _get_first_store_id()
    if not sid:
        return {"error": "No store found. Create a store at app.lemonsqueezy.com first."}
    body = {
        "data": {
            "type": "products",
            "attributes": {
                "name": name,
                "description": description,
                "price": price_cents,
                "buy_now_url": None,
                "status": "draft",
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": sid}}
            },
        }
    }
    data = _post("/products", body)
    if "error" in data:
        return data
    item = data.get("data") or {}
    attrs = item.get("attributes") or {}
    return {
        "ok": True,
        "product_id": item.get("id"),
        "name": attrs.get("name"),
        "price_cents": attrs.get("price"),
        "status": attrs.get("status"),
        "buy_now_url": attrs.get("buy_now_url"),
    }


def ls_get_sales(limit: int = 50) -> dict:
    """Return recent orders/sales summary."""
    data = _get("/orders", {"page[size]": min(limit, 100)})
    if "error" in data:
        return data
    orders = data.get("data") or []
    total_cents = sum(
        (o.get("attributes") or {}).get("total", 0)
        for o in orders
        if (o.get("attributes") or {}).get("status") == "paid"
    )
    return {
        "order_count": len(orders),
        "total_cents": total_cents,
        "total_dollars": round(total_cents / 100, 2),
        "currency": "USD",
        "recent_orders": [
            {
                "id": o.get("id"),
                "status": (o.get("attributes") or {}).get("status"),
                "total": (o.get("attributes") or {}).get("total"),
                "created_at": (o.get("attributes") or {}).get("created_at"),
            }
            for o in orders[:10]
        ],
    }


def ls_create_discount(percent_off: int, code: str, store_id: str = "") -> dict:
    """Create a percentage discount code."""
    if not 1 <= percent_off <= 100:
        return {"error": "percent_off must be between 1 and 100"}
    if not code:
        return {"error": "code required"}
    sid = store_id or _get_first_store_id()
    if not sid:
        return {"error": "No store found"}
    body = {
        "data": {
            "type": "discounts",
            "attributes": {
                "name": f"{percent_off}% off — {code}",
                "code": code.upper(),
                "amount": percent_off,
                "amount_type": "percent",
                "status": "published",
                "is_limited_to_products": False,
                "is_limited_redemptions": False,
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": sid}}
            },
        }
    }
    data = _post("/discounts", body)
    if "error" in data:
        return data
    item = data.get("data") or {}
    attrs = item.get("attributes") or {}
    return {
        "ok": True,
        "discount_id": item.get("id"),
        "code": attrs.get("code"),
        "percent_off": percent_off,
        "status": attrs.get("status"),
    }

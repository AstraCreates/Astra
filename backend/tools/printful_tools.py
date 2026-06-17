"""Printful print-on-demand API — products, store catalog, orders."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://api.printful.com"
_TIMEOUT = 15


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.printful_api_key}", "Content-Type": "application/json"}


def _not_configured() -> dict:
    return {"error": "PRINTFUL_API_KEY not configured"}


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"{_BASE}{path}", headers=_headers() if settings.printful_api_key else {}, params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Printful GET %s failed: %s", path, e)
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    if not settings.printful_api_key:
        return _not_configured()
    try:
        r = requests.post(f"{_BASE}{path}", headers=_headers(), json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Printful POST %s failed: %s", path, e)
        return {"error": str(e)}


def printful_get_products(category_id: int = 0) -> dict:
    """List available blank products (no auth needed). category_id=0 returns all."""
    params = {}
    if category_id:
        params["category_id"] = category_id
    data = _get("/products", params)
    if "error" in data:
        return data
    products = [
        {
            "id": p.get("id"),
            "type": p.get("type"),
            "type_name": p.get("type_name"),
            "title": p.get("title"),
            "brand": p.get("brand"),
            "model": p.get("model"),
            "currency": p.get("currency"),
        }
        for p in (data.get("result") or [])[:30]
    ]
    return {"products": products, "count": len(products)}


def printful_create_store_product(product_id: int = 0, name: str = "", variants: list[dict] | None = None) -> dict:
    """Add a product to the Printful store with sync variants.

    variants: [{size, color, retail_price, sku}]
    """
    from backend.tools._arg_utils import parse_list_arg
    variants = parse_list_arg(variants, "variants")
    if not product_id or not name:
        return {"error": "product_id and name are required"}
    if not variants:
        return {"error": "variants is required — pass a list like [{\"retail_price\": \"25.00\", \"variant_id\": 123}]"}
    sync_variants = [
        {
            "retail_price": str(v.get("retail_price", "25.00")),
            "variant_id": v.get("variant_id", product_id),
            "files": v.get("files", []),
        }
        for v in variants if isinstance(v, dict)
    ]
    body = {
        "sync_product": {"name": name, "thumbnail": ""},
        "sync_variants": sync_variants,
    }
    data = _post("/store/products", body)
    if "error" in data:
        return data
    result = data.get("result") or {}
    return {
        "ok": True,
        "sync_product_id": (result.get("sync_product") or {}).get("id"),
        "name": name,
        "variant_count": len((result.get("sync_variants") or [])),
    }


def printful_get_orders() -> dict:
    """List recent orders from the Printful store."""
    data = _get("/orders", {"limit": 20})
    if "error" in data:
        return data
    orders = [
        {
            "id": o.get("id"),
            "status": o.get("status"),
            "created": o.get("created"),
            "recipient_name": (o.get("recipient") or {}).get("name"),
            "retail_costs": o.get("retail_costs"),
        }
        for o in (data.get("result") or [])
    ]
    return {"orders": orders, "count": len(orders)}


def printful_create_order(items: list[dict] | None = None, recipient: dict | None = None) -> dict:
    """Place a fulfillment order.

    items: [{sync_variant_id, quantity}]
    recipient: {name, address1, city, state_code, country_code, zip}
    """
    from backend.tools._arg_utils import parse_list_arg, parse_dict_arg
    items = parse_list_arg(items, "items")
    recipient = parse_dict_arg(recipient)
    if not items or not recipient:
        return {"error": "items (list) and recipient (dict with name/address1/city/state_code/country_code/zip) required"}
    body = {
        "recipient": recipient,
        "items": [{"sync_variant_id": i["sync_variant_id"], "quantity": i.get("quantity", 1)} for i in items if isinstance(i, dict)],
    }
    data = _post("/orders", body)
    if "error" in data:
        return data
    result = data.get("result") or {}
    return {
        "ok": True,
        "order_id": result.get("id"),
        "status": result.get("status"),
        "retail_costs": result.get("retail_costs"),
    }

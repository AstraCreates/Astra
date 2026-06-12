"""Square API — catalog services, bookings, revenue for local service businesses."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://connect.squareup.com/v2"
_TIMEOUT = 15


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.square_access_token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-01-17",
    }


def _not_configured() -> dict:
    return {"error": "SQUARE_ACCESS_TOKEN not configured"}


def _get(path: str, params: dict | None = None) -> dict:
    if not settings.square_access_token:
        return _not_configured()
    try:
        r = requests.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Square GET %s failed: %s", path, e)
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    if not settings.square_access_token:
        return _not_configured()
    try:
        r = requests.post(f"{_BASE}{path}", headers=_headers(), json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Square POST %s failed: %s", path, e)
        return {"error": str(e)}


def square_list_services() -> dict:
    """List catalog items (services) for the account."""
    data = _get("/catalog/list", {"types": "ITEM"})
    if "error" in data:
        return data
    items = []
    for obj in (data.get("objects") or []):
        item_data = obj.get("item_data") or {}
        variations = item_data.get("variations") or []
        price_cents = 0
        if variations:
            price_money = (variations[0].get("item_variation_data") or {}).get("price_money") or {}
            price_cents = price_money.get("amount", 0)
        items.append({
            "id": obj.get("id"),
            "name": item_data.get("name"),
            "description": item_data.get("description"),
            "price_cents": price_cents,
        })
    return {"services": items, "count": len(items)}


def square_create_service(name: str, price_cents: int, duration_minutes: int, description: str = "") -> dict:
    """Add a bookable service to the Square catalog."""
    import uuid
    idempotency_key = str(uuid.uuid4())
    body = {
        "idempotency_key": idempotency_key,
        "object": {
            "type": "ITEM",
            "id": f"#{name.replace(' ', '_').upper()}",
            "item_data": {
                "name": name,
                "description": description,
                "service_version": 1,
                "variations": [
                    {
                        "type": "ITEM_VARIATION",
                        "id": f"#{name.replace(' ', '_').upper()}_VAR",
                        "item_variation_data": {
                            "name": "Standard",
                            "pricing_type": "FIXED_PRICING",
                            "price_money": {"amount": price_cents, "currency": "USD"},
                            "service_duration": duration_minutes * 60000,
                        },
                    }
                ],
            },
        },
    }
    data = _post("/catalog/object", body)
    if "error" in data:
        return data
    obj = data.get("catalog_object") or {}
    return {"ok": True, "id": obj.get("id"), "name": name, "price_cents": price_cents}


def square_create_booking(service_variation_id: str, start_at: str, customer_note: str = "") -> dict:
    """Create an appointment booking. start_at must be RFC3339 (e.g. 2024-06-15T10:00:00Z)."""
    import uuid
    location_id = settings.square_location_id
    if not location_id:
        return {"error": "SQUARE_LOCATION_ID not configured"}
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "booking": {
            "location_id": location_id,
            "start_at": start_at,
            "appointment_segments": [
                {
                    "service_variation_id": service_variation_id,
                    "duration_minutes": 60,
                }
            ],
            "customer_note": customer_note,
        },
    }
    data = _post("/bookings", body)
    if "error" in data:
        return data
    booking = data.get("booking") or {}
    return {"ok": True, "booking_id": booking.get("id"), "status": booking.get("status"), "start_at": start_at}


def square_list_bookings(start_date: str = "", end_date: str = "") -> dict:
    """List upcoming bookings. Dates in YYYY-MM-DD format."""
    params: dict = {}
    if settings.square_location_id:
        params["location_id"] = settings.square_location_id
    if start_date:
        params["start_at_min"] = f"{start_date}T00:00:00Z"
    if end_date:
        params["start_at_max"] = f"{end_date}T23:59:59Z"
    data = _get("/bookings", params)
    if "error" in data:
        return data
    bookings = [
        {
            "id": b.get("id"),
            "status": b.get("status"),
            "start_at": b.get("start_at"),
            "customer_note": b.get("customer_note"),
        }
        for b in (data.get("bookings") or [])
    ]
    return {"bookings": bookings, "count": len(bookings)}


def square_get_revenue(start_date: str = "", end_date: str = "") -> dict:
    """Return payment revenue summary for a date range."""
    params: dict = {"sort_order": "DESC", "limit": "100"}
    if settings.square_location_id:
        params["location_id"] = settings.square_location_id
    if start_date:
        params["begin_time"] = f"{start_date}T00:00:00Z"
    if end_date:
        params["end_time"] = f"{end_date}T23:59:59Z"
    data = _get("/payments", params)
    if "error" in data:
        return data
    payments = data.get("payments") or []
    total_cents = sum(
        (p.get("amount_money") or {}).get("amount", 0)
        for p in payments
        if p.get("status") == "COMPLETED"
    )
    return {
        "total_cents": total_cents,
        "total_dollars": round(total_cents / 100, 2),
        "payment_count": len(payments),
        "currency": "USD",
    }

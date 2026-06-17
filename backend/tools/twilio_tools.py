"""Twilio SMS API — send messages, manage messaging services."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://api.twilio.com/2010-04-01"
_TIMEOUT = 15


def _auth() -> tuple[str, str] | None:
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not sid or not token:
        return None
    return (sid, token)


def _not_configured() -> dict:
    return {"error": "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN not configured"}


def _post(path: str, data: dict) -> dict:
    auth = _auth()
    if auth is None:
        return _not_configured()
    try:
        r = requests.post(
            f"{_BASE}/Accounts/{settings.twilio_account_sid}{path}",
            data=data,
            auth=auth,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Twilio POST %s failed: %s", path, e)
        return {"error": str(e)}


def _get(path: str, params: dict | None = None) -> dict:
    auth = _auth()
    if auth is None:
        return _not_configured()
    try:
        r = requests.get(
            f"{_BASE}/Accounts/{settings.twilio_account_sid}{path}",
            params=params or {},
            auth=auth,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Twilio GET %s failed: %s", path, e)
        return {"error": str(e)}


def twilio_send_sms(to: str, body: str, from_number: str = "") -> dict:
    """Send a single SMS. from_number defaults to account's first number if omitted."""
    if not to or not body:
        return {"error": "to and body required"}
    sender = from_number or _get_default_number()
    if not sender:
        return {"error": "No from_number provided and no Twilio phone numbers found"}
    data = _post("/Messages.json", {"To": to, "From": sender, "Body": body[:1600]})
    if "error" in data:
        return data
    return {"ok": True, "sid": data.get("sid"), "status": data.get("status"), "to": to}


def twilio_send_bulk_sms(to_list: list[str] | None = None, body: str = "", from_number: str = "") -> dict:
    """Send the same SMS to multiple recipients. Returns per-recipient status."""
    from backend.tools._arg_utils import parse_list_arg
    to_list = parse_list_arg(to_list, "to_list")
    if not to_list or not body:
        return {"error": "to_list (list of phone numbers) and body (message text) required"}
    sender = from_number or _get_default_number()
    if not sender:
        return {"error": "No from_number provided and no Twilio phone numbers found"}
    results = []
    for to in to_list:
        r = _post("/Messages.json", {"To": to, "From": sender, "Body": body[:1600]})
        results.append({"to": to, "ok": "error" not in r, "sid": r.get("sid"), "error": r.get("error")})
    sent = sum(1 for r in results if r["ok"])
    return {"ok": True, "sent": sent, "failed": len(results) - sent, "results": results}


def twilio_create_messaging_service(name: str) -> dict:
    """Create a Twilio Messaging Service (recommended for bulk/campaign SMS)."""
    auth = _auth()
    if auth is None:
        return _not_configured()
    try:
        r = requests.post(
            "https://messaging.twilio.com/v1/Services",
            data={"FriendlyName": name},
            auth=auth,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        d = r.json()
        return {"ok": True, "service_sid": d.get("sid"), "name": d.get("friendly_name")}
    except Exception as e:
        logger.error("Twilio create messaging service failed: %s", e)
        return {"error": str(e)}


def twilio_get_usage() -> dict:
    """Return usage summary (messages sent this month)."""
    data = _get("/Usage/Records/ThisMonth.json", {"Category": "sms"})
    if "error" in data:
        return data
    records = data.get("usage_records") or []
    if records:
        rec = records[0]
        return {"count": rec.get("count"), "price": rec.get("price"), "unit": rec.get("price_unit")}
    return {"count": 0, "price": "0", "unit": "USD"}


def _get_default_number() -> str:
    """Fetch first available phone number on the account."""
    data = _get("/IncomingPhoneNumbers.json", {"PageSize": "1"})
    numbers = data.get("incoming_phone_numbers") or []
    return numbers[0].get("phone_number", "") if numbers else ""

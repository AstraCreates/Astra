"""Klaviyo email marketing API — lists, flows, campaigns, metrics."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://a.klaviyo.com/api"
_TIMEOUT = 15
_REV = "2024-02-15"


def _headers() -> dict:
    return {
        "Authorization": f"Klaviyo-API-Key {settings.klaviyo_api_key}",
        "revision": _REV,
        "content-type": "application/json",
        "accept": "application/json",
    }


def _not_configured() -> dict:
    return {"error": "KLAVIYO_API_KEY not configured"}


def _get(path: str, params: dict | None = None) -> dict:
    if not settings.klaviyo_api_key:
        return _not_configured()
    try:
        r = requests.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Klaviyo GET %s failed: %s", path, e)
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    if not settings.klaviyo_api_key:
        return _not_configured()
    try:
        r = requests.post(f"{_BASE}{path}", headers=_headers(), json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("Klaviyo POST %s failed: %s", path, e)
        return {"error": str(e)}


def klaviyo_create_list(name: str) -> dict:
    """Create an audience list. Returns {list_id, name}."""
    data = _post("/lists/", {"data": {"type": "list", "attributes": {"name": name}}})
    if "error" in data:
        return data
    item = (data.get("data") or {})
    return {"list_id": item.get("id"), "name": (item.get("attributes") or {}).get("name")}


def klaviyo_add_to_list(list_id: str = "", emails: list[str] | None = None) -> dict:
    """Add contacts to a list by email address."""
    from backend.tools._arg_utils import parse_list_arg
    emails = parse_list_arg(emails, "emails")
    if not list_id or not emails:
        return {"error": "list_id and emails required — emails must be a list of email strings"}
    members = [{"type": "profile", "attributes": {"email": e}} for e in emails]
    data = _post(f"/lists/{list_id}/relationships/profiles/", {"data": members})
    if "error" in data:
        return data
    return {"ok": True, "added": len(emails), "list_id": list_id}


def klaviyo_create_campaign(name: str, subject: str, body_html: str, list_id: str) -> dict:
    """Create a one-time email campaign (not yet scheduled). Returns {campaign_id}."""
    payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": name,
                "audiences": {"included": [list_id]},
                "send_options": {"use_smart_sending": True},
                "tracking_options": {"is_tracking_clicks": True, "is_tracking_opens": True},
                "send_strategy": {"method": "immediate"},
            },
        }
    }
    data = _post("/campaigns/", payload)
    if "error" in data:
        return data
    campaign_id = (data.get("data") or {}).get("id")
    # Create message for the campaign
    msg_payload = {
        "data": {
            "type": "campaign-message",
            "attributes": {
                "channel": "email",
                "label": name,
                "content": {"subject": subject, "body": body_html, "from_email": "hello@astra.ai", "from_label": "Astra"},
            },
            "relationships": {"campaign": {"data": {"type": "campaign", "id": campaign_id}}},
        }
    }
    _post("/campaign-messages/", msg_payload)
    return {"ok": True, "campaign_id": campaign_id, "name": name}


def klaviyo_get_metrics() -> dict:
    """Return top-level account metrics (lists, campaigns count)."""
    lists = _get("/lists/", {"fields[list]": "name,created"})
    campaigns = _get("/campaigns/", {"fields[campaign]": "name,status"})
    if "error" in lists:
        return lists
    return {
        "list_count": len((lists.get("data") or [])),
        "campaign_count": len((campaigns.get("data") or [])),
        "lists": [{"id": i.get("id"), "name": (i.get("attributes") or {}).get("name")} for i in (lists.get("data") or [])[:10]],
    }

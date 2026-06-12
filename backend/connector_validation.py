"""Connector validation harness.

Readiness answers "do we have something saved?". Validation answers "is the
saved connector shaped correctly, webhook-safe, and optionally reachable?".
Live provider checks are opt-in so local tests and installs do not depend on
external networks, but production operators can enable them for real evidence.
"""

from __future__ import annotations

from typing import Any, Callable

import requests

from backend.provisioning.credentials_store import load_all_credentials
from backend.stacks.readiness import _CONNECTOR_SERVICE_ALIASES
from backend.stacks.templates import get_stack_template
from backend.tools.integration_connect import get_composio_app_status


DEFAULT_TIMEOUT = 8

_FIELD_SPECS: dict[str, list[dict[str, Any]]] = {
    "github": [{"key": "token", "required": True}],
    "vercel": [{"key": "token", "required": True}],
    "supabase": [{"key": "url", "required": True}, {"key": "service_role_key", "required": True}],
    "clerk": [{"key": "secret_key", "required": True}],
    "gmail": [{"key": "access_token", "required": True}],
    "google_drive": [{"key": "access_token", "required": True}],
    "google_sheets": [{"key": "access_token", "required": True}],
    "google_calendar": [{"key": "access_token", "required": True}],
    "slack": [{"key": "bot_token", "required": True}, {"key": "webhook_secret", "required": False}],
    "discord": [{"key": "bot_token", "required": True}, {"key": "webhook_secret", "required": False}],
    "notion": [{"key": "token", "required": True}, {"key": "webhook_secret", "required": False}],
    "linear": [{"key": "api_key", "required": True}],
    "crm": [{"key": "access_token", "required": True}],
    "linkedin": [{"key": "access_token", "required": True}],
    "meta_ads": [{"key": "access_token", "required": True}],
    "analytics": [{"key": "api_key", "required": True}],
    "website_cms": [{"key": "access_token", "required": True}],
    "helpdesk": [{"key": "token", "required": True}],
    "product_tracker": [{"key": "api_key", "required": True}],
    "figma": [{"key": "token", "required": True}],
    "sendgrid": [{"key": "api_key", "required": True}],
    "obsidian": [{"key": "vault_path", "required": True}],
    # Ecommerce
    "klaviyo": [{"key": "api_key", "required": True}],
    "printful": [{"key": "api_key", "required": True}],
    "lemonsqueezy": [{"key": "api_key", "required": True}],
    # Local service
    "twilio": [{"key": "account_sid", "required": True}, {"key": "auth_token", "required": True}],
    "square": [{"key": "access_token", "required": True}, {"key": "location_id", "required": False}],
    "yelp": [{"key": "api_key", "required": True}],
}

_WEBHOOK_CAPABLE = {"github", "slack", "discord", "notion", "google_drive", "linear", "crm", "helpdesk", "product_tracker"}
_COMPOSIO_CONNECTOR_APPS = {
    "gmail": "gmail",
    "google_drive": "google_drive",
    "google_sheets": "google_drive",
    "google_calendar": "googlecalendar",
    "notion": "notion",
    "linear": "linear",
    "linkedin": "linkedin",
    "product_tracker": "linear",
}


def validate_stack_connectors(founder_id: str, stack_id: str | None = None, *, live: bool = False) -> dict[str, Any]:
    """Validate connectors required/used by a stack."""
    stack = get_stack_template(stack_id)
    credentials = load_all_credentials(founder_id)
    connectors = [
        validate_connector(founder_id, connector.key, credentials=credentials, required=connector.required, live=live)
        | {
            "label": connector.label,
            "category": connector.category,
            "purpose": connector.purpose,
        }
        for connector in stack.connector_requirements
    ]
    required = [item for item in connectors if item["required"]]
    blockers = [item for item in required if item["status"] in {"missing_credentials", "invalid_credentials", "provider_error"}]
    live_blocked = [item for item in connectors if item["provider"]["status"] == "not_checked"]
    return {
        "founder_id": founder_id,
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "live": live,
        "ready": not blockers,
        "required_total": len(required),
        "validated_required": len([item for item in required if item["status"] in {"validated", "locally_valid"}]),
        "blocked_required": len(blockers),
        "connectors": connectors,
        "next_actions": _validation_next_actions(blockers, live_blocked, live),
        "summary": (
            f"{stack.name} validation: {len(blockers)} required connector(s) blocked; "
            f"live provider checks {'enabled' if live else 'not requested'}."
        ),
    }


def validate_connector(
    founder_id: str,
    connector_key: str,
    *,
    credentials: dict[str, Any] | None = None,
    required: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    credentials = credentials if credentials is not None else load_all_credentials(founder_id)
    aliases = _CONNECTOR_SERVICE_ALIASES.get(connector_key, (connector_key,))
    connected_alias = next((alias for alias in aliases if isinstance(credentials.get(alias), dict) and credentials.get(alias)), None)
    saved = credentials.get(connected_alias or connector_key) or {}
    fields = _FIELD_SPECS.get(connector_key, [{"key": "token", "required": True}])
    composio_app = _COMPOSIO_CONNECTOR_APPS.get(connector_key, "")
    composio_marker = bool(saved.get("connected_via") == "composio_oauth" and composio_app)
    missing_fields = [
        field["key"]
        for field in fields
        if field.get("required") and not _field_present(saved, field["key"])
    ]
    credential_status = (
        "valid_shape" if composio_marker else
        "missing" if missing_fields or not connected_alias else
        "valid_shape"
    )
    webhook_secret = bool(saved.get("webhook_secret") or saved.get("signing_secret") or saved.get("secret"))
    webhook_status = (
        "not_supported" if connector_key not in _WEBHOOK_CAPABLE else
        "secured" if webhook_secret else
        "missing_secret"
    )
    provider = (
        _composio_provider_check(founder_id, composio_app, live=live)
        if composio_marker else
        _provider_check(connector_key, saved, live=live)
        if credential_status == "valid_shape" else
        {"status": "not_checked", "ok": False, "detail": "Missing required credential fields."}
    )
    status = (
        "missing_credentials" if credential_status == "missing" else
        "provider_error" if provider["status"] == "error" else
        "validated" if provider["status"] == "ok" else
        "locally_valid"
    )
    return {
        "key": connector_key,
        "required": required,
        "credential_service": connected_alias or connector_key,
        "credential_aliases": list(aliases),
        "credential_status": credential_status,
        "missing_fields": missing_fields,
        "webhook": {
            "supported": connector_key in _WEBHOOK_CAPABLE,
            "status": webhook_status,
            "secret_configured": webhook_secret,
        },
        "provider": provider,
        "status": status,
    }


def _field_present(saved: dict[str, Any], key: str) -> bool:
    aliases = {
        "token": ("token", "api_key", "access_token", "bot_token"),
        "api_key": ("api_key", "token", "access_token"),
        "access_token": ("access_token", "token", "api_key"),
        "service_role_key": ("service_role_key", "service_key", "key"),
    }.get(key, (key,))
    return any(bool(saved.get(alias)) for alias in aliases)


def _provider_check(connector_key: str, saved: dict[str, Any], *, live: bool) -> dict[str, Any]:
    if not live:
        return {"status": "not_checked", "ok": True, "detail": "Live provider check not requested."}
    checker = _LIVE_CHECKS.get(connector_key)
    if not checker:
        return {"status": "unsupported", "ok": True, "detail": "No live provider checker implemented for this connector."}
    try:
        return _sanitize_provider_result(checker(saved), saved)
    except Exception as exc:
        return _sanitize_provider_result({"status": "error", "ok": False, "detail": str(exc)}, saved)


def _composio_provider_check(founder_id: str, composio_app: str, *, live: bool) -> dict[str, Any]:
    if not live:
        return {"status": "not_checked", "ok": True, "detail": "Composio OAuth marker present; live provider check not requested."}
    try:
        status = get_composio_app_status(founder_id)
        if status.get(composio_app):
            return {"status": "ok", "ok": True, "detail": f"Composio app {composio_app} is active."}
        return {"status": "error", "ok": False, "detail": f"Composio app {composio_app} is not active."}
    except Exception as exc:
        return {"status": "error", "ok": False, "detail": str(exc)}


def _bearer_get(url: str, token: str, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", **(extra_headers or {})}
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _github_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get("https://api.github.com/user", str(saved.get("token") or saved.get("access_token") or ""), {"Accept": "application/vnd.github+json"})


def _vercel_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get("https://api.vercel.com/v2/user", str(saved.get("token") or saved.get("access_token") or saved.get("api_key") or ""))


def _supabase_check(saved: dict[str, Any]) -> dict[str, Any]:
    url = str(saved.get("url") or "").rstrip("/")
    key = str(saved.get("service_role_key") or saved.get("service_key") or saved.get("key") or "")
    if not url:
        return {"status": "error", "ok": False, "detail": "Supabase URL missing."}
    response = requests.get(
        f"{url}/rest/v1/",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code in {200, 300, 301, 302, 404} or response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _clerk_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("secret_key") or saved.get("token") or "")
    return _bearer_get("https://api.clerk.com/v1/users?limit=1", token)


def _slack_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("bot_token") or saved.get("token") or "")
    response = requests.get("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {token}"}, timeout=DEFAULT_TIMEOUT)
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code < 400 and data.get("ok"):
        return {"status": "ok", "ok": True, "http_status": response.status_code, "team": data.get("team")}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": str(data or response.text)[:240]}


def _discord_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("bot_token") or saved.get("token") or "")
    response = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bot {token}"}, timeout=DEFAULT_TIMEOUT)
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _notion_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("token") or saved.get("api_key") or saved.get("access_token") or "")
    response = requests.post(
        "https://api.notion.com/v1/search",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
        json={"page_size": 1},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _linear_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("api_key") or saved.get("token") or "")
    response = requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"query": "{ viewer { id } }"},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _google_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("access_token") or saved.get("token") or "")
    response = requests.get("https://www.googleapis.com/oauth2/v1/tokeninfo", params={"access_token": token}, timeout=DEFAULT_TIMEOUT)
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _figma_check(saved: dict[str, Any]) -> dict[str, Any]:
    token = str(saved.get("token") or saved.get("api_key") or "")
    response = requests.get("https://api.figma.com/v1/me", headers={"X-Figma-Token": token}, timeout=DEFAULT_TIMEOUT)
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _sendgrid_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get("https://api.sendgrid.com/v3/user/profile", str(saved.get("api_key") or saved.get("token") or ""))


def _klaviyo_check(saved: dict[str, Any]) -> dict[str, Any]:
    key = str(saved.get("api_key") or "")
    response = requests.get(
        "https://a.klaviyo.com/api/accounts/",
        headers={"Authorization": f"Klaviyo-API-Key {key}", "revision": "2024-02-15"},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _twilio_check(saved: dict[str, Any]) -> dict[str, Any]:
    sid = str(saved.get("account_sid") or "")
    token = str(saved.get("auth_token") or "")
    response = requests.get(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
        auth=(sid, token),
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _square_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get(
        "https://connect.squareup.com/v2/locations",
        str(saved.get("access_token") or ""),
        extra_headers={"Square-Version": "2024-01-17"},
    )


def _printful_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get("https://api.printful.com/store", str(saved.get("api_key") or ""))


def _yelp_check(saved: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        "https://api.yelp.com/v3/businesses/search",
        headers={"Authorization": f"Bearer {saved.get('api_key', '')}"},
        params={"term": "coffee", "location": "NYC", "limit": "1"},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code < 400:
        return {"status": "ok", "ok": True, "http_status": response.status_code}
    return {"status": "error", "ok": False, "http_status": response.status_code, "detail": response.text[:240]}


def _lemonsqueezy_check(saved: dict[str, Any]) -> dict[str, Any]:
    return _bearer_get("https://api.lemonsqueezy.com/v1/stores", str(saved.get("api_key") or ""),
                       extra_headers={"Accept": "application/vnd.api+json"})


def _sanitize_provider_result(value: Any, saved: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_provider_result(item, saved) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_provider_result(item, saved) for item in value]
    if not isinstance(value, str):
        return value
    sanitized = value
    for secret in _credential_values(saved):
        sanitized = sanitized.replace(secret, "[redacted]")
    for marker in ("access_token", "token", "api_key", "apikey", "key"):
        sanitized = _redact_query_param(sanitized, marker)
    return sanitized


def _credential_values(saved: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in saved.values():
        if isinstance(item, str) and len(item) >= 4:
            values.append(item)
    return sorted(set(values), key=len, reverse=True)


def _redact_query_param(value: str, key: str) -> str:
    import re

    return re.sub(rf"([?&]{re.escape(key)}=)[^\\s&)'\\\"]+", r"\1[redacted]", value, flags=re.IGNORECASE)


_LIVE_CHECKS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "github": _github_check,
    "vercel": _vercel_check,
    "supabase": _supabase_check,
    "clerk": _clerk_check,
    "slack": _slack_check,
    "discord": _discord_check,
    "notion": _notion_check,
    "linear": _linear_check,
    "google_drive": _google_check,
    "google_sheets": _google_check,
    "google_calendar": _google_check,
    "gmail": _google_check,
    "figma": _figma_check,
    "sendgrid": _sendgrid_check,
    "website_cms": _vercel_check,
    "product_tracker": _linear_check,
    "klaviyo": _klaviyo_check,
    "twilio": _twilio_check,
    "square": _square_check,
    "printful": _printful_check,
    "yelp": _yelp_check,
    "lemonsqueezy": _lemonsqueezy_check,
}


def _validation_next_actions(blockers: list[dict[str, Any]], live_blocked: list[dict[str, Any]], live: bool) -> list[str]:
    actions = []
    for item in blockers:
        if item["status"] == "missing_credentials":
            actions.append(f"Add credentials for {item.get('label') or item['key']}: {', '.join(item['missing_fields'])}.")
        elif item["status"] == "provider_error":
            actions.append(f"Fix provider access for {item.get('label') or item['key']}: {item['provider'].get('detail', 'provider check failed')}.")
    if not live and live_blocked:
        actions.append("Run connector validation with live=true before production launch to verify provider reachability.")
    return actions[:10]

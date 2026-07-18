"""Provider webhook ingestion for Company Brain connectors."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request

from backend.provisioning.credentials_store import load_credentials
from backend.tools.company_brain import ingest_company_brain_records


def verify_connector_webhook(founder_id: str, source: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify a connector webhook with a stored shared or signing secret."""
    creds = load_credentials(founder_id, source) or {}
    secret = str(
        creds.get("webhook_secret")
        or creds.get("signing_secret")
        or creds.get("secret")
        or ""
    )
    if not secret:
        raise HTTPException(status_code=409, detail=f"{source} webhook secret is not configured.")

    provided_secret = headers.get("x-astra-webhook-secret") or headers.get("x-webhook-secret")
    if provided_secret and hmac.compare_digest(provided_secret, secret):
        return {"ok": True, "method": "shared_secret"}

    signature = (
        headers.get("x-astra-signature")
        or headers.get("x-hub-signature-256")
        or headers.get("x-signature-sha256")
        or ""
    )
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if signature and hmac.compare_digest(_normalize_signature(signature), expected):
        return {"ok": True, "method": "hmac_sha256"}

    slack_signature = headers.get("x-slack-signature") or ""
    slack_timestamp = headers.get("x-slack-request-timestamp") or ""
    if slack_signature and slack_timestamp and _valid_slack_signature(secret, body, slack_signature, slack_timestamp):
        return {"ok": True, "method": "slack_hmac"}

    raise HTTPException(status_code=401, detail="Invalid connector webhook signature.")


def ingest_connector_webhook(founder_id: str, source: str, payload: dict[str, Any], event_id: str = "") -> dict[str, Any]:
    """Normalize a provider webhook payload and ingest it into Company Brain."""
    normalized = normalize_connector_webhook_payload(source, payload)
    if normalized.get("challenge") is not None:
        return {"ok": True, "source": source, "handled": "challenge", "challenge": normalized["challenge"]}

    records = list(normalized.get("records") or [])
    sync_event_id = str(event_id or normalized.get("event_id") or "")
    event_type = str(normalized.get("event_type") or "")
    cursor = str(normalized.get("cursor") or sync_event_id or "")
    result = ingest_company_brain_records(founder_id, source, records)
    ledger_error = ""
    try:
        from backend.connector_sync_ledger import record_connector_webhook
        record_connector_webhook(
            founder_id,
            source,
            event_id=sync_event_id,
            event_type=event_type,
            changed_records=int(result.get("changed_records") or 0),
            cursor=cursor or None,
        )
    except Exception as exc:
        ledger_error = str(exc)
    return {
        **result,
        "source": source,
        "event_id": sync_event_id,
        "event_type": event_type,
        "cursor": cursor,
        "records": len(records),
        "degraded": bool(ledger_error),
        "warning": "Webhook ingested but sync ledger persistence failed." if ledger_error else "",
        "ledger_recorded": not ledger_error,
        "ledger_error": ledger_error,
    }


def normalize_connector_webhook_payload(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return normalized Company Brain records for common connector webhook shapes."""
    if payload.get("type") == "url_verification" and payload.get("challenge") is not None:
        return {"challenge": payload.get("challenge"), "records": []}

    if isinstance(payload.get("records"), list):
        records = [record for record in payload["records"] if isinstance(record, dict)]
        return {
            "records": records,
            "event_id": str(payload.get("event_id") or payload.get("id") or ""),
            "event_type": str(payload.get("event_type") or payload.get("type") or "records"),
            "cursor": _max_cursor(records),
        }

    if source == "slack":
        return _normalize_slack(payload)
    if source == "discord":
        return _normalize_discord(payload)
    if source == "github":
        return _normalize_github(payload)
    if source == "notion":
        return _normalize_notion(payload)
    if source == "google_drive":
        return _normalize_google_drive(payload)

    record = _generic_record(source, payload)
    return {
        "records": [record],
        "event_id": str(payload.get("event_id") or payload.get("id") or payload.get("delivery_id") or ""),
        "event_type": str(payload.get("event_type") or payload.get("type") or payload.get("action") or "webhook"),
        "cursor": str(payload.get("updated_at") or payload.get("timestamp") or payload.get("id") or ""),
    }


async def parse_verified_connector_webhook(request: Request, founder_id: str, source: str) -> tuple[dict[str, Any], dict[str, Any]]:
    body = await request.body()
    verification = verify_connector_webhook(founder_id, source, body, {k.lower(): v for k, v in request.headers.items()})
    try:
        payload = json.loads(body.decode() or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON webhook payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object.")
    return payload, verification


def _normalize_signature(value: str) -> str:
    value = value.strip()
    return value if value.startswith("sha256=") else f"sha256={value}"


def _valid_slack_signature(secret: str, body: bytes, signature: str, timestamp: str) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except Exception:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _normalize_slack(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    ts = str(event.get("ts") or event.get("event_ts") or payload.get("event_time") or "")
    channel = str(event.get("channel") or event.get("channel_name") or "")
    text = str(event.get("text") or event.get("message") or "")
    record = {
        "title": f"Slack #{channel or 'channel'} {ts or payload.get('event_id') or ''}".strip(),
        "content": text or json.dumps(event, sort_keys=True)[:4000],
        "kind": "message",
        "canonical": False,
        "stale_risk": "medium",
        "domain": "operations",
        "channel": channel,
        "thread_ts": event.get("thread_ts") or ts,
        "author": event.get("user") or event.get("bot_id") or "",
        "external_id": ts or payload.get("event_id"),
        "updated_at": ts,
    }
    return {
        "records": [record],
        "event_id": str(payload.get("event_id") or ts),
        "event_type": str(event.get("type") or payload.get("type") or "slack_event"),
        "cursor": ts or str(payload.get("event_id") or ""),
    }


def _normalize_discord(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload.get("d") if isinstance(payload.get("d"), dict) else payload
    author = message.get("author") or {}
    msg_id = str(message.get("id") or payload.get("id") or "")
    channel = str(message.get("channel_name") or message.get("channel_id") or "")
    record = {
        "title": f"Discord #{channel or 'channel'} {msg_id}".strip(),
        "content": str(message.get("content") or json.dumps(message, sort_keys=True)[:4000]),
        "kind": "message",
        "canonical": False,
        "stale_risk": "medium",
        "domain": "operations",
        "server": message.get("guild_name") or message.get("guild_id") or "",
        "channel": channel,
        "author": author.get("username") or author.get("id") or "",
        "external_id": msg_id,
        "updated_at": message.get("edited_timestamp") or message.get("timestamp") or "",
    }
    return {
        "records": [record],
        "event_id": str(payload.get("event_id") or msg_id),
        "event_type": str(payload.get("t") or payload.get("type") or "discord_message"),
        "cursor": msg_id,
    }


def _normalize_github(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("pull_request") or payload.get("issue") or payload.get("repository") or payload
    repo = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    event_type = str(payload.get("action") or payload.get("event_type") or "github_event")
    title = item.get("title") or item.get("full_name") or repo.get("full_name") or payload.get("ref") or "GitHub event"
    head_commit = payload.get("head_commit") if isinstance(payload.get("head_commit"), dict) else {}
    body = item.get("body") or item.get("description") or head_commit.get("message") or ""
    record = {
        "title": f"GitHub {event_type}: {title}",
        "content": str(body or json.dumps(payload, sort_keys=True)[:4000]),
        "url": item.get("html_url") or repo.get("html_url") or "",
        "kind": "pull_request" if "pull_request" in payload else "issue" if "issue" in payload else "repository",
        "canonical": False,
        "stale_risk": "medium",
        "domain": "architecture",
        "repo": repo.get("full_name") or item.get("full_name") or "",
        "state": item.get("state") or event_type,
        "external_id": item.get("id") or payload.get("delivery_id") or "",
        "updated_at": item.get("updated_at") or repo.get("updated_at") or "",
    }
    return {
        "records": [record],
        "event_id": str(payload.get("delivery_id") or item.get("id") or ""),
        "event_type": event_type,
        "cursor": str(item.get("updated_at") or repo.get("updated_at") or item.get("id") or ""),
    }


def _normalize_notion(payload: dict[str, Any]) -> dict[str, Any]:
    entity = payload.get("entity") if isinstance(payload.get("entity"), dict) else payload.get("page") if isinstance(payload.get("page"), dict) else payload
    title = entity.get("title") or entity.get("name") or entity.get("id") or "Notion update"
    edited_at = str(entity.get("last_edited_time") or payload.get("last_edited_time") or "")
    record = {
        "title": str(title),
        "content": str(entity.get("content") or entity.get("summary") or title),
        "url": entity.get("url") or "",
        "kind": entity.get("object") or "page",
        "canonical": True,
        "stale_risk": "low",
        "domain": "operations",
        "external_id": entity.get("id") or payload.get("id") or "",
        "updated_at": edited_at,
    }
    return {
        "records": [record],
        "event_id": str(payload.get("event_id") or entity.get("id") or ""),
        "event_type": str(payload.get("type") or "notion_update"),
        "cursor": edited_at or str(entity.get("id") or ""),
    }


def _normalize_google_drive(payload: dict[str, Any]) -> dict[str, Any]:
    file_obj = payload.get("file") if isinstance(payload.get("file"), dict) else payload
    modified = str(file_obj.get("modifiedTime") or file_obj.get("modified_time") or "")
    title = str(file_obj.get("name") or file_obj.get("id") or "Drive file")
    record = {
        "title": title,
        "content": str(file_obj.get("text") or file_obj.get("description") or file_obj.get("summary") or title),
        "url": file_obj.get("webViewLink") or file_obj.get("url") or "",
        "kind": "file",
        "canonical": False,
        "stale_risk": "medium",
        "domain": "operations",
        "external_id": file_obj.get("id") or payload.get("id") or "",
        "updated_at": modified,
    }
    return {
        "records": [record],
        "event_id": str(payload.get("event_id") or file_obj.get("id") or ""),
        "event_type": str(payload.get("type") or "drive_update"),
        "cursor": modified or str(file_obj.get("id") or ""),
    }


def _generic_record(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("event_type") or payload.get("type") or payload.get("action") or "webhook")
    title = str(payload.get("title") or payload.get("name") or payload.get("subject") or f"{source} {event_type}")
    return {
        "title": title,
        "content": str(payload.get("content") or payload.get("body") or payload.get("text") or json.dumps(payload, sort_keys=True)[:4000]),
        "kind": str(payload.get("kind") or "webhook_event"),
        "canonical": bool(payload.get("canonical", False)),
        "stale_risk": str(payload.get("stale_risk") or "medium"),
        "domain": str(payload.get("domain") or "operations"),
        "external_id": payload.get("event_id") or payload.get("id") or "",
        "updated_at": payload.get("updated_at") or payload.get("timestamp") or "",
    }


def _max_cursor(records: list[dict[str, Any]]) -> str:
    cursor = ""
    for record in records:
        candidate = str(record.get("updated_at") or record.get("external_id") or "")
        if candidate and candidate > cursor:
            cursor = candidate
    return cursor

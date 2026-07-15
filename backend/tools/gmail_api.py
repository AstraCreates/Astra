from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import threading
from typing import Any

import requests

from backend.config import settings
from backend.provisioning.credentials_store import load_credentials, store_credentials

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


# ── Durable idempotency for gmail_send_email ────────────────────────────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." A retried Temporal
# activity that times out AFTER Gmail successfully sent but BEFORE the
# activity's result is durably recorded would otherwise re-send the identical
# email to the real recipient. Unlike Stripe, the Gmail send API has no
# native idempotency-key parameter, so when no run_id is available (a caller
# with no run context threaded through) there is genuinely no protection
# possible -- only the durable Astra receipt (when run_id IS available) can
# prevent a duplicate send.
def _run_async(coro):
    """Run an async coroutine from sync code, whether or not the calling
    thread already has a running event loop (mirrors stripe_tools.py's
    _run_async, same reasoning: gmail_send_email is called both from plain
    sync contexts and from within an already-running asyncio loop)."""
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


def _send_with_idempotency(*, run_id: str, step_id: str, args: dict[str, Any], send_call: Any) -> dict[str, Any]:
    """Route the actual Gmail send through Astra's durable action/receipt
    control plane when run_id is available. With no run_id (a direct/manual
    call outside an agent run), there is no idempotency key to attach to
    anything -- Gmail's API has no dedup mechanism of its own -- so we just
    call directly and accept the retry-duplicates-send risk for that case."""
    if not run_id:
        return send_call()

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        canonicalize_tool_args,
        execute_external_action,
        get_default_repo_bundle,
    )

    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::gmail_send_email::{canonical_args}".encode("utf-8")).hexdigest()
    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, _idempotency_key: str) -> dict:
        return send_call()

    result = _run_async(execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or "gmail_send_email",
            action_id=action_id,
            tool="gmail_send_email",
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    ))
    return dict(result.provider_result or {})


def _extract_body(payload: dict[str, Any]) -> str:
    body = ((payload or {}).get("body") or {}).get("data") or ""
    if body:
        try:
            return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    text_parts: list[str] = []
    for part in (payload or {}).get("parts") or []:
        text_parts.append(_extract_body(part))
    return "\n".join(part for part in text_parts if part)


def _extract_verification_artifacts(body: str) -> dict[str, str]:
    code_match = re.search(r"(?<!\d)(\d{6,8})(?!\d)", body)
    links = re.findall(r'https?://[^\s<>"\')\]]+', body)
    for link in links:
        lower = link.lower()
        if any(marker in lower for marker in ("verify", "confirm", "activate", "magic", "token", "code", "login")):
            return {"code": code_match.group(1) if code_match else "", "link": re.sub(r'[.,;!?\'"]+$', "", link)}
    return {"code": code_match.group(1) if code_match else "", "link": ""}


def _gmail_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def refresh_gmail_access_token(creds: dict[str, Any]) -> dict[str, Any]:
    refresh_token = str(creds.get("refresh_token") or "")
    client_id = str(creds.get("client_id") or settings.google_client_id or "")
    client_secret = str(creds.get("client_secret") or settings.google_client_secret or "")
    if not refresh_token or not client_id or not client_secret:
        return {}
    resp = requests.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if not resp.ok:
        return {}
    payload = resp.json()
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        return {}
    merged = dict(creds)
    merged["access_token"] = access_token
    if payload.get("expires_in") is not None:
        merged["expires_in"] = payload.get("expires_in")
    return merged


def get_gmail_api_credentials(founder_id: str = "", inline_credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    inline_credentials = dict(inline_credentials or {})
    service_candidates: list[dict[str, Any]] = []
    if founder_id:
        for service in ("gmail", "google"):
            stored = load_credentials(founder_id, service) or {}
            if stored:
                service_candidates.append(dict(stored))
    if inline_credentials:
        service_candidates.insert(0, inline_credentials)
    for creds in service_candidates:
        if creds.get("access_token"):
            return creds
        refreshed = refresh_gmail_access_token(creds)
        if refreshed.get("access_token"):
            if founder_id:
                service_name = "gmail" if load_credentials(founder_id, "gmail") else "google"
                store_credentials(founder_id, service_name, refreshed)
            return refreshed
    return {}


def gmail_send_email(
    founder_id: str, to: str, subject: str, body: str, attachment_path: str = "",
    *, run_id: str = "", step_id: str = "",
) -> dict[str, Any]:
    """Send an email via the founder's connected Gmail account, optionally with a
    file attached (e.g. a generated PDF deliverable).

    run_id/step_id are optional and, when provided by the caller (an agent
    tool-dispatch context), route the send through Astra's durable
    action/receipt idempotency layer so a Temporal activity retry replays the
    stored result instead of re-sending to the real recipient. See
    _send_with_idempotency's docstring for why no protection is possible when
    they're absent."""
    creds = get_gmail_api_credentials(founder_id)
    access_token = str(creds.get("access_token") or "")
    if not access_token:
        return {"error": "Gmail not connected — go to /integrations and connect Gmail"}

    import mimetypes
    import os
    import email.mime.text
    import email.mime.multipart
    import email.mime.base
    import email.encoders
    msg = email.mime.multipart.MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject
    msg.attach(email.mime.text.MIMEText(body, "plain"))
    if attachment_path:
        if not os.path.isfile(attachment_path):
            return {"error": f"Attachment not found: {attachment_path}"}
        ctype, _ = mimetypes.guess_type(attachment_path)
        part = email.mime.base.MIMEBase(*(ctype.split("/", 1) if ctype else ("application", "octet-stream")))
        with open(attachment_path, "rb") as f:
            part.set_payload(f.read())
        email.encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(attachment_path))
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def _send(token: str) -> requests.Response:
        return requests.post(
            f"{_MESSAGES_URL}/send",
            headers={**_gmail_headers(token), "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=15,
        )

    def _do_send() -> dict[str, Any]:
        nonlocal creds, access_token
        resp = _send(access_token)
        if resp.status_code == 401 and creds.get("refresh_token"):
            creds = refresh_gmail_access_token(creds)
            access_token = str(creds.get("access_token") or "")
            if access_token:
                store_credentials(founder_id, "gmail", creds)
                resp = _send(access_token)
        if not resp.ok:
            return {"error": f"Gmail send failed: {resp.status_code} {resp.text[:200]}"}
        msg_id = resp.json().get("id", "")
        return {"ok": True, "message_id": msg_id, "to": to, "subject": subject}

    return _send_with_idempotency(
        run_id=run_id, step_id=step_id,
        args={"to": to, "subject": subject, "body": body, "attachment_path": attachment_path},
        send_call=_do_send,
    )


def fetch_gmail_verification(founder_id: str, service_name: str, inline_credentials: dict[str, Any] | None = None) -> dict[str, str]:
    creds = get_gmail_api_credentials(founder_id, inline_credentials)
    access_token = str(creds.get("access_token") or "")
    if not access_token:
        return {"code": "", "link": "", "error": "gmail_api_not_configured"}
    query = f"newer_than:1d ({service_name} OR from:{service_name})"
    listing = requests.get(
        _MESSAGES_URL,
        headers=_gmail_headers(access_token),
        params={"maxResults": 10, "q": query},
        timeout=15,
    )
    if listing.status_code == 401 and creds.get("refresh_token"):
        creds = refresh_gmail_access_token(creds)
        access_token = str(creds.get("access_token") or "")
        if not access_token:
            return {"code": "", "link": "", "error": "gmail_api_refresh_failed"}
        if founder_id:
            service_name_key = "gmail" if load_credentials(founder_id, "gmail") else "google"
            store_credentials(founder_id, service_name_key, creds)
        listing = requests.get(
            _MESSAGES_URL,
            headers=_gmail_headers(access_token),
            params={"maxResults": 10, "q": query},
            timeout=15,
        )
    if not listing.ok:
        return {"code": "", "link": "", "error": f"gmail_api_list_failed:{listing.status_code}"}
    for msg in (listing.json().get("messages") or []):
        msg_id = msg.get("id")
        if not msg_id:
            continue
        detail = requests.get(
            f"{_MESSAGES_URL}/{msg_id}",
            headers=_gmail_headers(access_token),
            params={"format": "full"},
            timeout=15,
        )
        if not detail.ok:
            continue
        body = _extract_body(detail.json().get("payload") or {})
        artifacts = _extract_verification_artifacts(body)
        if artifacts["code"] or artifacts["link"]:
            return artifacts
    return {"code": "", "link": "", "error": "gmail_api_message_not_found"}

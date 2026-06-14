from __future__ import annotations

import base64
import re
from typing import Any

import requests

from backend.config import settings
from backend.provisioning.credentials_store import load_credentials, store_credentials

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


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

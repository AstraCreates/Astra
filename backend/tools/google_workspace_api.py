from __future__ import annotations

from typing import Any, Iterable

import requests

from backend.config import settings
from backend.provisioning.credentials_store import load_credentials, store_credentials

GOOGLE_WORKSPACE_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DEFAULT_TIMEOUT = 20


def workspace_scope_string() -> str:
    return " ".join(GOOGLE_WORKSPACE_SCOPES)


def refresh_google_access_token(creds: dict[str, Any]) -> dict[str, Any]:
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


def get_google_credentials(
    founder_id: str,
    *,
    services: Iterable[str] = ("google_workspace", "gmail", "google_drive", "google"),
) -> tuple[str | None, dict[str, Any]]:
    for service in services:
        creds = load_credentials(founder_id, service) or {}
        if not creds:
            continue
        if creds.get("access_token"):
            return service, creds
        refreshed = refresh_google_access_token(creds)
        if refreshed.get("access_token"):
            store_credentials(founder_id, service, refreshed)
            return service, refreshed
    return None, {}


def google_api_request(
    founder_id: str,
    *,
    method: str,
    url: str,
    services: Iterable[str] = ("google_workspace", "gmail", "google_drive", "google"),
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> tuple[requests.Response | None, dict[str, Any]]:
    service, creds = get_google_credentials(founder_id, services=services)
    access_token = str(creds.get("access_token") or "")
    if not access_token:
        return None, {"error": "Google Workspace not connected — connect it in Integrations first"}

    base_headers = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        base_headers["Content-Type"] = "application/json"
    if headers:
        base_headers.update(headers)

    def _send(token: str) -> requests.Response:
        merged_headers = dict(base_headers)
        merged_headers["Authorization"] = f"Bearer {token}"
        return requests.request(
            method=method.upper(),
            url=url,
            params=params or None,
            json=json_body,
            data=data,
            headers=merged_headers,
            timeout=timeout,
        )

    resp = _send(access_token)
    if resp.status_code == 401 and creds.get("refresh_token") and service:
        refreshed = refresh_google_access_token(creds)
        new_token = str(refreshed.get("access_token") or "")
        if new_token:
            store_credentials(founder_id, service, refreshed)
            resp = _send(new_token)
    if resp.status_code >= 400:
        return resp, {"error": f"Google API error {resp.status_code}: {resp.text[:300]}"}
    try:
        return resp, resp.json() if resp.text else {}
    except Exception:
        return resp, {}

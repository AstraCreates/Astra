"""SSO bridge into the self-hosted Activepieces automations builder.

Activepieces' official embed/managed-auth flow (packages/server/api/src/app/ee/
managed-authn) is Enterprise-licensed — not available on the Community Edition
core we're self-hosting. This gets the same practical result (founder never
sees an Activepieces login screen, one account per founder) using only the
plain MIT-licensed sign-up/sign-in API: we provision an account server-side on
first visit, sign in server-side on every visit, and hand the frontend a fresh
session token to inject into the iframe via postMessage.
"""
from __future__ import annotations

import re
import secrets

import requests

from backend.provisioning.credentials_store import load_credentials, store_credentials

_SERVICE = "automations"
_BASE_URL = "http://automations:80"
_TIMEOUT = 10.0


def _founder_email(founder_id: str) -> str:
    local = re.sub(r"[^a-z0-9_.-]", "_", founder_id.lower())[:64] or "founder"
    return f"{local}@founders.astra.internal"


def ensure_automations_account(founder_id: str) -> dict:
    """Returns {email, password} for this founder, provisioning the account
    on the automations instance the first time it's needed."""
    creds = load_credentials(founder_id, _SERVICE)
    if creds and creds.get("email") and creds.get("password"):
        return creds

    email = _founder_email(founder_id)
    password = secrets.token_urlsafe(24)
    resp = requests.post(
        f"{_BASE_URL}/api/v1/authentication/sign-up",
        json={
            "email": email,
            "password": password,
            "firstName": "Astra",
            "lastName": "Founder",
            "trackEvents": False,
            "newsLetter": False,
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"automations sign-up failed ({resp.status_code}): {resp.text[:300]}")

    creds = {"email": email, "password": password}
    store_credentials(founder_id, _SERVICE, creds)
    return creds


def get_automations_session_token(founder_id: str) -> str:
    """Ensures the founder has an account, signs in server-side, returns a
    fresh session JWT for the frontend to inject into the embedded iframe."""
    creds = ensure_automations_account(founder_id)
    resp = requests.post(
        f"{_BASE_URL}/api/v1/authentication/sign-in",
        json={"email": creds["email"], "password": creds["password"]},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise RuntimeError("automations sign-in returned no token")
    return token

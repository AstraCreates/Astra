"""Tenant authorization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, Query, Request
import jwt
from jwt import PyJWKClient


ROLE_RANK = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
    "owner": 4,
}


@dataclass(frozen=True)
class Actor:
    user_id: str


@dataclass(frozen=True)
class FounderActor:
    actor_id: str
    founder_id: str
    min_role: str


def request_user_id(request: Request) -> str | None:
    """Extract the authenticated user id from a verified token or trusted dev header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token.lower().startswith("dev_") and _dev_auth_allowed():
            return token.removeprefix("dev_").strip()
        return _verified_jwt_subject(token)

    if _trusted_headers_allowed():
        for header in ("x-astra-user-id", "x-user-id", "x-clerk-user-id"):
            value = request.headers.get(header)
            if value:
                return value.strip()

    # Query params for EventSource/WebSocket (browsers can't set custom headers).
    # Prefer verified JWT; fall back to trusted user_id param.
    qp = getattr(request, "query_params", {})
    token_qp = qp.get("token", "")
    if token_qp:
        sub = _verified_jwt_subject(token_qp)
        if sub:
            return sub
    if _trusted_headers_allowed():
        for param in ("user_id", "founder_id"):
            value = qp.get(param, "")
            if value:
                return value.strip()
    return None


def _settings() -> Any:
    from backend.config import settings

    return settings


def _trusted_headers_allowed() -> bool:
    try:
        settings = _settings()
        return bool(settings.astra_trust_auth_headers) or not bool(settings.astra_require_auth)
    except Exception:
        return False  # fail closed — never trust headers if config unreadable


def _dev_auth_allowed() -> bool:
    try:
        settings = _settings()
        return bool(settings.astra_allow_dev_auth) or not bool(settings.astra_require_auth)
    except Exception:
        return False  # fail closed


def _verified_jwt_subject(token: str) -> str | None:
    try:
        settings = _settings()
        issuer = str(getattr(settings, "astra_jwt_issuer", "") or "").rstrip("/")
        audience = str(getattr(settings, "astra_jwt_audience", "") or "")
        secret = str(getattr(settings, "astra_jwt_secret", "") or "")
        jwks_url = str(getattr(settings, "astra_jwt_jwks_url", "") or "")
        if not jwks_url and issuer:
            jwks_url = f"{issuer}/.well-known/jwks.json"

        options = {"verify_aud": bool(audience), "verify_iss": bool(issuer)}
        kwargs: dict[str, Any] = {"options": options}
        if audience:
            kwargs["audience"] = audience
        if issuer:
            kwargs["issuer"] = issuer

        if secret:
            payload = jwt.decode(token, secret, algorithms=["HS256"], **kwargs)
        elif jwks_url:
            signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, algorithms=["RS256"], **kwargs)
        else:
            return None
        sub = payload.get("sub") or payload.get("user_id") or payload.get("uid")
        return str(sub) if sub else None
    except Exception:
        return None


@lru_cache(maxsize=8)
def _jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def require_authenticated_user(request: Request) -> str:
    user_id = request_user_id(request)
    if user_id:
        return user_id
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid or unverified authentication token.")
    raise HTTPException(status_code=401, detail="Authentication required.")


def _require_auth_enabled() -> bool:
    try:
        settings = _settings()
        return bool(settings.astra_require_auth)
    except Exception:
        return False


def _missing_user_allowed() -> bool:
    return not _require_auth_enabled()


def actor_or_body(request: Request, fallback: str | None = None) -> str:
    user_id = request_user_id(request)
    if user_id:
        return user_id
    if _missing_user_allowed():
        return fallback or "local_dev"
    return require_authenticated_user(request)


def current_actor(request: Request) -> Actor:
    """Return the authenticated actor while preserving local-dev fallback behavior."""
    return Actor(user_id=actor_or_body(request))


def require_founder_access(request: Request, founder_id: str, min_role: str = "viewer") -> str:
    """Require caller to be the founder or an authorized member of that founder workspace."""
    user_id = request_user_id(request)
    if not user_id:
        if _missing_user_allowed():
            return founder_id
        user_id = require_authenticated_user(request)
    if user_id == founder_id:
        return user_id
    # In dev mode (auth not required), trust the caller regardless of ID mismatch.
    # This handles the common case where a user's browser ID drifts (e.g. after
    # Google sign-in overwrites the localStorage ID that was used to create sessions).
    if _missing_user_allowed():
        return user_id
    return require_org_access(request, founder_id, min_role=min_role)


def require_current_founder(request: Request, founder_id: str, min_role: str = "viewer") -> FounderActor:
    """Authorize a founder-scoped request and return the actor/founder pair."""
    founder_id = str(founder_id or "").strip()
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    actor_id = require_founder_access(request, founder_id, min_role=min_role)
    return FounderActor(actor_id=actor_id, founder_id=founder_id, min_role=min_role)


def current_founder_from_query(min_role: str = "viewer"):
    """Build a dependency for routes scoped by the standard founder_id query param."""

    async def dependency(
        request: Request,
        founder_id: str = Query(..., description="Founder ID"),
    ) -> FounderActor:
        return require_current_founder(request, founder_id, min_role=min_role)

    return dependency


def require_org_access(request: Request, org_id: str, min_role: str = "viewer") -> str:
    """Require caller membership in an org with at least min_role."""
    user_id = request_user_id(request)
    if not user_id:
        if _missing_user_allowed():
            return org_id
        user_id = require_authenticated_user(request)
    try:
        from backend.accounts import get_or_create_org
        org = get_or_create_org(org_id, org_id)
        member = (org.get("members") or {}).get(user_id)
        role = "owner" if org.get("owner_id") == user_id else (member or {}).get("role", "")
        active = member is None and org.get("owner_id") == user_id or (member or {}).get("status") == "active"
    except Exception:
        role = "owner" if user_id == org_id else ""
        active = user_id == org_id
    if not active or ROLE_RANK.get(role, 0) < ROLE_RANK.get(min_role, 1):
        raise HTTPException(status_code=403, detail="Insufficient workspace permissions.")
    return user_id


def require_company_access(request: Request, founder_id: str, company_id: str, min_role: str = "viewer") -> str:
    """Require caller to have access to a company within a founder's workspace."""
    # First check founder/org access
    user_id = require_founder_access(request, founder_id, min_role=min_role)

    # In dev mode or same-company, allow access
    if _missing_user_allowed() or company_id == founder_id:
        return user_id

    # In prod, verify company belongs to this founder's workspace
    try:
        from backend.core.workspace_store import get_workspace
        workspace = get_workspace(founder_id) or {}
        companies = workspace.get("companies", [])
        if company_id not in companies and company_id != founder_id:
            raise HTTPException(
                status_code=403,
                detail="Company not found in this workspace.",
            )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("workspace lookup failed for %s: %s", founder_id, e)
        raise HTTPException(
            status_code=403,
            detail="Company access could not be verified.",
        )

    return user_id


def require_platform_admin(request: Request) -> str:
    """Require a caller explicitly allowlisted for platform-wide admin access."""
    user_id = request_user_id(request)
    if not user_id:
        if _missing_user_allowed():
            return "local_dev"
        user_id = require_authenticated_user(request)
    try:
        settings = _settings()
        raw_admins = str(getattr(settings, "astra_platform_admins", "") or "")
        admins = {item.strip() for item in raw_admins.split(",") if item.strip()}
    except Exception:
        admins = set()
    if user_id in admins:
        return user_id
    raise HTTPException(status_code=403, detail="Platform admin access required.")

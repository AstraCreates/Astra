"""
Reverse proxy for company preview subdomains.

nginx routes *.{PUBLIC_HOST} traffic here; we read the Host header to extract
the slug, look up the port, and httpx-proxy to localhost:{port}.

Security posture:
- Target is always localhost:{port} — not user-supplied, not redirectable to other hosts
- follow_redirects=False prevents SSRF via upstream redirect
- Forwarded headers are whitelisted; Authorization and Cookie are never forwarded
- Auth: previews are dev builds on a separate nip.io domain (different eTLD+1 from
  the app) so browser cookies aren't shared. Slug registry keys include session_id
  suffix so slugs aren't guessable across tenants.
- Auth enforcement should be added when ASTRA_REQUIRE_AUTH is enabled (TODO W8).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Whitelist of headers safe to forward to the preview dev server.
# Intentionally excludes: Authorization, Cookie, X-Astra-*, x-preview-slug.
_FORWARD_HEADERS = {
    "accept", "accept-encoding", "accept-language", "cache-control",
    "content-type", "content-length", "range", "user-agent", "referer",
    "if-modified-since", "if-none-match",
}


def _preview_owner(slug: str, port: int | None) -> tuple[str, str] | None:
    """Resolve the preview's durable session metadata, never client input.

    ``port`` is the single snapshot the caller already resolved for this
    request -- re-resolving it here independently (the original shape of
    this function) would reopen the same TOCTOU gap _authorize_preview's
    docstring describes, just one level deeper."""
    try:
        from backend.tools import local_preview
        sessions = [session_id for session_id, value in local_preview._registry_load().items() if port is not None and value == port]
        if not sessions:
            _session_id, record = local_preview._record_for_slug(slug)
            if record and record.get("founder_id"):
                owner = str(record["founder_id"])
                return owner, str(record.get("company_id") or owner)
            return None
        if len(sessions) != 1:
            return None
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(sessions[0]) or {}
        founder_id = str(meta.get("founder_id") or "")
        company_id = str(meta.get("company_id") or meta.get("workspace_id") or founder_id)
        return (founder_id, company_id) if founder_id else None
    except Exception:
        logger.warning("Could not resolve preview owner for slug=%s", slug)
        return None


def _valid_signed_token(slug: str, token: str) -> bool:
    """Accept ``expiry.signature`` tokens signed for one preview slug."""
    secret = os.getenv("ASTRA_PREVIEW_SIGNING_SECRET", "")
    if not secret or not token:
        return False
    try:
        expiry_text, signature = token.split(".", 1)
        expiry = int(expiry_text)
        if expiry < int(time.time()) or expiry > int(time.time()) + 7 * 86_400:
            return False
        payload = f"{slug}.{expiry}".encode()
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        return hmac.compare_digest(expected, supplied)
    except (TypeError, ValueError):
        return False


def _authorize_preview(slug: str, request: Request, port: int | None) -> None:
    """``port`` must be a single snapshot resolved once per request by the
    caller and passed to both this and ``_proxy`` -- resolving it separately
    in each (the original bug here) opens a TOCTOU gap: a preview that comes
    up in the moment between the two independent lookups would sail through
    with the ownership check skipped, since this function's own "nothing to
    authorize" decision was made against a now-stale, no-longer-true snapshot
    of the registry."""
    if _valid_signed_token(slug, request.query_params.get("preview_token", "")):
        return
    owner = _preview_owner(slug, port)
    if not owner:
        raise HTTPException(status_code=403, detail="Preview ownership could not be verified.")
    from backend.tenant_auth import require_company_access
    require_company_access(request, owner[0], owner[1], min_role="viewer")


async def _proxy(slug: str, path: str, request: Request, port: int | None) -> StreamingResponse:
    if not port:
        raise HTTPException(status_code=404, detail=(
            f"No preview running for '{slug}' -- it was likely idle-evicted or stopped when the "
            "server last restarted. Ask Astra to rebuild it and you'll get a fresh preview link."
        ))

    # Target is always localhost — not attacker-influenced
    qs = f"?{request.url.query}" if request.url.query else ""
    target = f"http://localhost:{port}/{path}{qs}"

    # Whitelist-only header forwarding — never send Authorization, Cookie, or app tokens
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_HEADERS}

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                request.method,
                target,
                headers=headers,
                content=body,
                follow_redirects=False,  # prevent SSRF via redirect to non-localhost
            )
    except (httpx.ConnectError, httpx.TimeoutException):
        return StreamingResponse(
            iter([b"<html><body><h2>Preview starting up, please wait and refresh.</h2></body></html>"]),
            status_code=503,
            media_type="text/html",
        )

    # Strip hop-by-hop headers. content-encoding must be dropped because httpx
    # auto-decompresses the body — forwarding the header would cause double-decompress.
    skip_resp = {"transfer-encoding", "connection", "keep-alive", "content-encoding"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip_resp}

    return StreamingResponse(
        iter([resp.content]),
        status_code=resp.status_code,
        headers=resp_headers,
    )


@router.api_route("/preview-route/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def preview_proxy_path(path: str, request: Request):
    # Extract slug from Host header (set by nginx from the subdomain)
    host = request.headers.get("host", "")
    # Only extract slug from subdomain requests (host must contain a dot)
    slug = host.split(".")[0] if "." in host else ""
    if not slug:
        raise HTTPException(status_code=400, detail="Missing preview slug")
    from backend.tools.local_preview import get_port_for_slug, recover_preview_for_slug
    # Authorize against either the live registry or the durable seven-day
    # record *before* recovery starts a local process.
    port = get_port_for_slug(slug)
    _authorize_preview(slug, request, port)
    if port is None:
        port = recover_preview_for_slug(slug)
        if port is None:
            raise HTTPException(status_code=503, detail={
                "state": "failed",
                "message": "Preview could not be recovered. Rebuild the preview from its Company OS task.",
                "action": "rebuild_preview",
            })
    return await _proxy(slug, path, request, port)


@router.api_route("/preview-route", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def preview_proxy_root(request: Request):
    return await preview_proxy_path("", request)

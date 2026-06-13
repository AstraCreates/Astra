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

import logging

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


async def _proxy(slug: str, path: str, request: Request) -> StreamingResponse:
    from backend.tools.local_preview import get_port_for_slug

    port = get_port_for_slug(slug)
    if not port:
        raise HTTPException(status_code=404, detail=f"No preview running for '{slug}'")

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

    # Strip hop-by-hop response headers + content-encoding (we buffer full body above)
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
    return await _proxy(slug, path, request)


@router.api_route("/preview-route", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def preview_proxy_root(request: Request):
    return await preview_proxy_path("", request)

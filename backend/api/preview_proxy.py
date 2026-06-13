"""
Reverse proxy for company preview subdomains.

nginx routes *.{PUBLIC_HOST} traffic here with the X-Preview-Slug header set.
We look up the slug → port mapping and httpx-proxy the request to localhost:{port}.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()


async def _proxy(slug: str, path: str, request: Request) -> StreamingResponse:
    from backend.tools.local_preview import get_port_for_slug

    port = get_port_for_slug(slug)
    if not port:
        raise HTTPException(status_code=404, detail=f"No preview running for '{slug}'")

    # Build target URL inside the container (preview servers bind to 0.0.0.0:{port})
    qs = request.url.query
    target = f"http://localhost:{port}/{path}"
    if qs:
        target = f"{target}?{qs}"

    # Forward request headers, minus hop-by-hop and Astra-internal ones
    skip = {"host", "x-preview-slug", "x-astra-user-id", "connection", "transfer-encoding"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}

    body = await request.body()

    async def _stream():
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                async with client.stream(
                    request.method, target, headers=headers, content=body, follow_redirects=True
                ) as resp:
                    # Yield response body in chunks
                    async for chunk in resp.aiter_bytes(chunk_size=32768):
                        yield chunk
            except httpx.ConnectError:
                logger.warning("Preview connect error: slug=%s port=%s", slug, port)
                yield b"<html><body><h2>Preview starting up, please wait a moment and refresh.</h2></body></html>"

    # We need the status + headers from the upstream response before streaming.
    # Use a non-streaming request for the headers pass, then stream body separately.
    # Simpler: just do a normal (buffered) request for small assets; for large ones
    # streaming matters. Since previews are dev servers, buffering is fine for now.
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                request.method, target, headers=headers, content=body, follow_redirects=True
            )
    except httpx.ConnectError:
        return StreamingResponse(
            iter([b"<html><body><h2>Preview starting up, please wait and refresh.</h2></body></html>"]),
            status_code=503,
            media_type="text/html",
        )

    # Strip hop-by-hop response headers
    skip_resp = {"transfer-encoding", "connection", "keep-alive", "content-encoding"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip_resp}

    return StreamingResponse(
        iter([resp.content]),
        status_code=resp.status_code,
        headers=resp_headers,
    )


@router.api_route("/preview-route/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def preview_proxy_path(path: str, request: Request):
    slug = request.headers.get("x-preview-slug", "").strip()
    if not slug:
        # Fallback: try to extract from Host header (slug.PUBLIC_HOST)
        host = request.headers.get("host", "")
        slug = host.split(".")[0] if host else ""
    if not slug:
        raise HTTPException(status_code=400, detail="Missing preview slug")
    return await _proxy(slug, path, request)


@router.api_route("/preview-route", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def preview_proxy_root(request: Request):
    return await preview_proxy_path("", request)

"""Deployments API — staging/production promotion for Vercel deploys.

Routes (all prefixed with /api via main.py include_router):
  GET  /api/deployments?founder_id=x           list deployments for a founder
  GET  /api/deployments/{session_id}            get deployment for a session
  POST /api/deployments/{session_id}/publish    promote staging → prod via Vercel alias API
"""
from __future__ import annotations

import logging
import re

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deployments.store import (
    get_deployment,
    list_deployments,
    publish_deployment,
)
from backend.tenant_auth import FounderActor, current_founder_from_query, require_current_founder

logger = logging.getLogger(__name__)

deployments_router = APIRouter(tags=["deployments"])

_VERCEL_API = "https://api.vercel.com"


# ── Request / response models ──────────────────────────────────────────────────

class PublishRequest(BaseModel):
    vercel_token: str
    domain: str | None = None


class PublishResponse(BaseModel):
    ok: bool
    prod_url: str | None = None
    error: str | None = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@deployments_router.get("/deployments")
async def api_list_deployments(actor: FounderActor = Depends(current_founder_from_query(min_role="viewer"))):
    """List all deployments for a founder, newest first."""
    founder_id = actor.founder_id
    return {"deployments": list_deployments(founder_id)}


@deployments_router.get("/deployments/{session_id}")
async def api_get_deployment(session_id: str, request: Request):
    """Get the deployment record for a session."""
    record = get_deployment(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No deployment found for session {session_id}")
    founder_id = str(record.get("founder_id") or "")
    if not founder_id:
        raise HTTPException(status_code=404, detail=f"No deployment found for session {session_id}")
    require_current_founder(request, founder_id, min_role="viewer")
    return record


@deployments_router.post("/deployments/{session_id}/publish", response_model=PublishResponse)
async def api_publish_deployment(session_id: str, body: PublishRequest, request: Request):
    """Promote staging deployment to production.

    Uses Vercel's alias API to point a custom domain (or the default .vercel.app
    domain) at the existing preview deployment URL.

    Steps:
      1. Fetch the staging record to get the staging_url.
      2. Extract the deployment ID from the staging_url.
      3. PATCH /v2/deployments/{deployment_id}/aliases with the target domain.
      4. Persist the new prod_url in the store.
    """
    record = get_deployment(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No deployment found for session {session_id}")
    founder_id = str(record.get("founder_id") or "")
    if not founder_id:
        raise HTTPException(status_code=404, detail=f"No deployment found for session {session_id}")
    require_current_founder(request, founder_id, min_role="admin")

    staging_url: str = record.get("staging_url", "")
    if not staging_url:
        raise HTTPException(status_code=400, detail="Staging URL not set for this session")

    token = body.vercel_token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Extract deployment ID from staging_url.
    # Vercel preview URLs are of the form:
    #   https://<project>-<hash>-<scope>.vercel.app  (CLI / git preview)
    #   https://<deployment-id>.vercel.app            (direct deployment)
    # We can also query the Vercel API to map the URL → deployment ID.
    dep_id = _resolve_deployment_id(staging_url, headers)
    if not dep_id:
        raise HTTPException(
            status_code=422,
            detail=f"Could not resolve deployment ID from staging URL: {staging_url}",
        )

    # Determine the alias target (domain)
    alias = body.domain or _default_alias(staging_url, dep_id, headers)
    if not alias:
        raise HTTPException(status_code=422, detail="Could not determine target domain for alias")

    # Call Vercel alias API
    alias_url = f"{_VERCEL_API}/v2/deployments/{dep_id}/aliases"
    try:
        resp = requests.post(
            alias_url,
            json={"alias": alias},
            headers=headers,
            timeout=20,
        )
    except Exception as exc:
        logger.error("Vercel alias API request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Vercel API request failed: {exc}")

    if not resp.ok:
        err_text = resp.text[:400]
        logger.warning("Vercel alias API error %d: %s", resp.status_code, err_text)
        raise HTTPException(status_code=502, detail=f"Vercel alias API error: {err_text}")

    alias_data = resp.json()
    prod_url = f"https://{alias_data.get('alias', alias)}"

    # Persist to store
    updated = publish_deployment(session_id, prod_url)

    return PublishResponse(ok=True, prod_url=prod_url)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_deployment_id(staging_url: str, headers: dict) -> str | None:
    """Resolve a staging URL to a Vercel deployment ID.

    Strategy:
    1. Query GET /v13/deployments?url=<hostname> to find by URL.
    2. Fall back to extracting the ID from the URL pattern if possible.
    """
    try:
        from urllib.parse import urlparse
        hostname = urlparse(staging_url).netloc
        if not hostname:
            return None

        # Query Vercel API to find the deployment by URL
        search_url = f"{_VERCEL_API}/v13/deployments"
        resp = requests.get(
            search_url,
            params={"url": hostname, "limit": 1},
            headers=headers,
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            deployments = data.get("deployments", [])
            if deployments:
                dep_id = deployments[0].get("uid") or deployments[0].get("id")
                if dep_id:
                    return dep_id

    except Exception as exc:
        logger.warning("_resolve_deployment_id API query failed: %s", exc)

    # Fallback: some Vercel URL patterns embed the deployment ID
    # e.g. https://my-project-abc123xyz.vercel.app
    # This is a best-effort extraction; not always reliable.
    try:
        from urllib.parse import urlparse
        hostname = urlparse(staging_url).netloc
        # Vercel dpl-* IDs are sometimes in the URL for API deployments
        m = re.search(r"\bdpl_[a-zA-Z0-9]+\b", hostname)
        if m:
            return m.group(0)
    except Exception:
        pass

    return None


def _default_alias(staging_url: str, dep_id: str, headers: dict) -> str | None:
    """Determine the default production alias for a deployment.

    Looks up the project name from the deployment and returns
    <project_name>.vercel.app as the canonical production URL.
    """
    try:
        dep_resp = requests.get(
            f"{_VERCEL_API}/v13/deployments/{dep_id}",
            headers=headers,
            timeout=15,
        )
        if dep_resp.ok:
            dep_data = dep_resp.json()
            project_name = dep_data.get("name") or dep_data.get("projectName")
            if project_name:
                return f"{project_name}.vercel.app"
    except Exception as exc:
        logger.warning("_default_alias lookup failed: %s", exc)

    return None

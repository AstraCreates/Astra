"""n8n workflow automation — trigger webhooks, list workflows, get executions."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TIMEOUT = 30


async def n8n_trigger_workflow(
    workflow_webhook_id: str,
    payload: dict,
    founder_id: str = "",
) -> dict:
    """Trigger an n8n workflow via webhook. Returns the n8n execution result.

    workflow_webhook_id: the webhook path ID configured in n8n (e.g. "abc123")
    payload:             JSON body to send to the webhook
    founder_id:          auto-injected by agent runtime — do not pass
    """
    import httpx
    from backend.config import settings

    base = settings.n8n_base_url.rstrip("/")
    url = f"{base}/webhook/{workflow_webhook_id}"

    body = dict(payload)
    if founder_id:
        body.setdefault("founder_id", founder_id)

    auth = None
    if settings.n8n_basic_auth_password:
        auth = (settings.n8n_basic_auth_user, settings.n8n_basic_auth_password)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=body, auth=auth)
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("n8n trigger_workflow %s failed: %s", workflow_webhook_id, e)
        return {"error": str(e)}


async def n8n_list_workflows(
    founder_id: str = "",
) -> dict:
    """List all active n8n workflows via the REST API.

    founder_id: auto-injected by agent runtime — do not pass
    """
    import httpx
    from backend.config import settings

    base = settings.n8n_base_url.rstrip("/")
    url = f"{base}/api/v1/workflows"

    if not settings.n8n_api_key:
        return {"error": "N8N_API_KEY not configured"}

    headers = {"X-N8N-API-KEY": settings.n8n_api_key}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"active": "true"})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error("n8n list_workflows failed: %s", e)
        return {"error": str(e)}


async def n8n_get_execution(
    execution_id: str,
    founder_id: str = "",
) -> dict:
    """Get the result of a completed n8n workflow execution.

    execution_id: n8n execution ID returned after a workflow run
    founder_id:   auto-injected by agent runtime — do not pass
    """
    import httpx
    from backend.config import settings

    base = settings.n8n_base_url.rstrip("/")
    url = f"{base}/api/v1/executions/{execution_id}"

    if not settings.n8n_api_key:
        return {"error": "N8N_API_KEY not configured"}

    headers = {"X-N8N-API-KEY": settings.n8n_api_key}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error("n8n get_execution %s failed: %s", execution_id, e)
        return {"error": str(e)}

"""Generic automation runtime helpers backed by Windmill."""
from __future__ import annotations

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

_TIMEOUT = 30


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def automation_trigger_flow(
    flow_path: str,
    payload: dict,
    founder_id: str = "",
) -> dict:
    """Trigger a flow in the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    path = quote((flow_path or "").strip("/"), safe="/")
    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/jobs/run/f/{path}"

    body = dict(payload)
    if founder_id:
        body.setdefault("founder_id", founder_id)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=body, headers=_headers(settings.automation_token))
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("automation trigger_flow %s failed: %s", flow_path, e)
        return {"error": str(e)}


async def automation_list_flows(
    founder_id: str = "",
) -> dict:
    """List flows from the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/flows/list"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers(settings.automation_token))
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return {"items": data}
            if isinstance(data, dict):
                return data
            return {"items": []}
    except Exception as e:
        logger.error("automation list_flows failed: %s", e)
        return {"error": str(e)}


async def automation_get_run(
    run_id: str,
    founder_id: str = "",
) -> dict:
    """Get a run/job from the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/jobs_u/get/{quote(run_id, safe='')}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers(settings.automation_token))
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("automation get_run %s failed: %s", run_id, e)
        return {"error": str(e)}

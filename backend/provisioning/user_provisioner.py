"""
Auto-provisions a new user on sign-up (no browser automation required).

Steps:
1. Store Astra platform credentials as the user's credentials so agents
   can act on their behalf immediately (GitHub, Vercel, SendGrid).
2. Create a Supabase project for the user's data (via Management API).
3. Initialize a Composio entity for the user (generates OAuth URLs).

Designed to run in the background from the Clerk webhook — fast, API-only.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from backend.provisioning.credentials_store import store_credentials
from backend.provisioning.integration_automation import apply_platform_credentials

logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _provision_platform_creds(founder_id: str) -> dict:
    """
    Map Astra's platform API keys as this user's credentials so all
    agents work immediately without the user connecting anything.
    """
    mapped = apply_platform_credentials(founder_id)

    logger.info("Platform creds mapped for %s: %s", founder_id, list(mapped.keys()))
    return mapped


def _provision_supabase(founder_id: str, email: str) -> dict:
    """Create a dedicated Supabase project for this user."""
    try:
        from backend.provisioning.supabase_provisioner import provision_supabase_project
        project_name = (email.split("@")[0] or founder_id[:12]).replace(".", "-").replace("_", "-")[:20]
        result = provision_supabase_project(founder_id, project_name)
        if result.get("created"):
            store_credentials(founder_id, "supabase", {
                "project_url": result.get("project_url"),
                "anon_key": result.get("anon_key"),
                "service_role_key": result.get("service_role_key"),
                "ref": result.get("ref"),
            })
        return result
    except Exception as e:
        logger.warning("Supabase provisioning failed for %s: %s", founder_id, e)
        return {"created": False, "error": str(e)}


def _provision_composio_entity(founder_id: str) -> dict:
    """Initialize a Composio entity and return OAuth connection URLs."""
    try:
        from backend.tools.composio_tools import connect_founder_tools
        urls = connect_founder_tools(founder_id, None)
        return urls or {}
    except Exception as e:
        logger.warning("Composio entity init failed for %s: %s", founder_id, e)
        return {"error": str(e)}


async def provision_new_user(founder_id: str, email: str, name: str = "") -> dict:
    """
    Full async auto-provision for a new user. Called from Clerk webhook.
    Returns summary of what was set up.
    """
    logger.info("Auto-provisioning new user: %s (%s)", founder_id, email)

    loop = asyncio.get_event_loop()

    # Platform creds — sync, fast
    platform = _provision_platform_creds(founder_id)

    # Supabase + Composio in parallel (Stripe is connected via OAuth on the Payments page)
    supabase_fut = loop.run_in_executor(_EXECUTOR, _provision_supabase, founder_id, email)
    composio_fut = loop.run_in_executor(_EXECUTOR, _provision_composio_entity, founder_id)

    supabase_result, composio_result = await asyncio.gather(supabase_fut, composio_fut)

    summary = {
        "founder_id": founder_id,
        "email": email,
        "platform_creds": platform,
        "supabase": supabase_result,
        "composio_oauth_urls": composio_result,
    }

    logger.info("Auto-provisioning complete for %s: platform=%s supabase=%s",
                founder_id, list(platform.keys()), supabase_result.get("created"))
    return summary

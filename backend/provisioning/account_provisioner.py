"""
Orchestrates full account provisioning from a single email + password.
Runs all browser automations concurrently (separate threads) and
stores credentials encrypted per-founder.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.provisioning.browser_provisioner import (
    provision_composio,
    provision_github,
    provision_sendgrid,
    provision_vercel,
)
from backend.provisioning.credentials_store import load_all_credentials, store_credentials

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

OAUTH_URLS = {
    "instagram": (
        "https://www.facebook.com/dialog/oauth"
        "?client_id={meta_app_id}"
        "&redirect_uri={redirect_uri}/oauth/instagram/callback"
        "&scope=instagram_basic,instagram_content_publish,ads_management"
        "&response_type=code"
    ),
    "tiktok": (
        "https://www.tiktok.com/auth/authorize"
        "?client_key={tiktok_client_key}"
        "&scope=video.upload,video.list"
        "&response_type=code"
        "&redirect_uri={redirect_uri}/oauth/tiktok/callback"
    ),
}


async def provision_all(
    founder_id: str,
    email: str,
    password: str,
    base_url: str = "http://localhost:8000",
) -> dict:
    """
    Provision GitHub, Vercel, SendGrid concurrently.
    Also generates Composio OAuth URLs for Gmail, LinkedIn, Twitter, Calendar, Notion, Linear.
    Returns status per service + all OAuth URLs.
    """
    loop = asyncio.get_event_loop()

    # Run all browser automations concurrently
    from backend.tools.composio_tools import connect_founder_tools, _reset_toolset

    from backend.config import settings
    imap_pw = settings.test_email_imap_password or None

    github_fut = loop.run_in_executor(_EXECUTOR, provision_github, email, password, None, imap_pw)
    sendgrid_fut = loop.run_in_executor(_EXECUTOR, provision_sendgrid, email, password, imap_pw)
    composio_provision_fut = loop.run_in_executor(_EXECUTOR, provision_composio, email, password)

    results = {}
    for service, fut in [("github", github_fut), ("sendgrid", sendgrid_fut)]:
        try:
            results[service] = await fut
        except Exception as e:
            logger.error("Provisioning failed for %s: %s", service, e)
            results[service] = {"created": False, "error": str(e)}

    # Vercel uses GitHub token — provision after GitHub
    github_token = results.get("github", {}).get("token")
    try:
        results["vercel"] = await loop.run_in_executor(
            _EXECUTOR, provision_vercel, email, password, github_token, imap_pw
        )
    except Exception as e:
        results["vercel"] = {"created": False, "error": str(e)}

    # Composio account — inject API key into settings + .env if obtained
    try:
        composio_result = await composio_provision_fut
    except Exception as e:
        composio_result = {"api_key": None, "created": False, "error": str(e)}

    results["composio"] = composio_result
    if composio_result.get("api_key"):
        _inject_composio_key(composio_result["api_key"])
        _reset_toolset()

    # Now generate per-founder OAuth URLs (uses freshly injected key if available)
    try:
        composio_urls = await loop.run_in_executor(
            _EXECUTOR, connect_founder_tools, founder_id, None
        )
    except Exception as e:
        composio_urls = {"error": str(e)}

    # Store credentials that were successfully obtained
    _store_service_creds(founder_id, results)

    # OAuth connect URLs for social (require existing accounts + phone verification)
    results["oauth_connect"] = {
        "instagram": f"{base_url}/oauth/instagram?founder_id={founder_id}",
        "tiktok": f"{base_url}/oauth/tiktok?founder_id={founder_id}",
        "meta_ads": f"{base_url}/oauth/meta?founder_id={founder_id}",
    }

    return {
        "founder_id": founder_id,
        "email": email,
        "services": results,
        "summary": _summarize(results),
        "composio_oauth_urls": composio_urls,
    }


def _inject_composio_key(api_key: str) -> None:
    """Write Composio API key to .env and update settings in-memory."""
    from backend.config import settings
    settings.composio_api_key = api_key

    env_path = ".env"
    try:
        try:
            with open(env_path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []

        updated = False
        for i, line in enumerate(lines):
            if line.startswith("COMPOSIO_API_KEY="):
                lines[i] = f"COMPOSIO_API_KEY={api_key}\n"
                updated = True
                break
        if not updated:
            lines.append(f"COMPOSIO_API_KEY={api_key}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)
        logger.info("Composio API key written to .env")
    except Exception as e:
        logger.warning("Could not write Composio key to .env: %s", e)


def _store_service_creds(founder_id: str, results: dict) -> None:
    mappings = {
        "github": lambda r: {"token": r.get("token"), "username": r.get("username")},
        "vercel": lambda r: {"token": r.get("token")},
        "sendgrid": lambda r: {"api_key": r.get("api_key")},
    }
    for service, extractor in mappings.items():
        r = results.get(service, {})
        if r.get("created"):
            try:
                store_credentials(founder_id, service, extractor(r))
            except Exception as e:
                logger.error("Failed to store %s creds: %s", service, e)


def _summarize(results: dict) -> list[str]:
    lines = []
    service_labels = {
        "github": "GitHub",
        "vercel": "Vercel",
        "sendgrid": "SendGrid (email)",
        "composio": "Composio (tool execution)",
    }
    for key, label in service_labels.items():
        r = results.get(key, {})
        if r.get("created"):
            lines.append(f"✓ {label} — connected")
        elif r.get("needs_verification") or r.get("needs_email_link"):
            lines.append(f"⚠ {label} — check your email to verify")
        elif key == "composio" and not r:
            pass  # composio not attempted yet — skip
        else:
            lines.append(f"✗ {label} — {r.get('error', r.get('note', 'failed'))}")
    lines.append("→ Connect Gmail / LinkedIn / Twitter / Calendar via OAuth buttons below")
    lines.append("→ Instagram / TikTok / Meta Ads require phone verification — connect manually")
    return lines


async def get_founder_setup_status(founder_id: str) -> dict:
    """Returns which services are connected for this founder."""
    try:
        creds = load_all_credentials(founder_id)
    except Exception:
        creds = {}

    return {
        "github": bool(creds.get("github", {}).get("token")),
        "vercel": bool(creds.get("vercel", {}).get("token")),
        "sendgrid": bool(creds.get("sendgrid", {}).get("api_key")),
        "instagram": bool(creds.get("instagram", {}).get("access_token")),
        "tiktok": bool(creds.get("tiktok", {}).get("access_token")),
        "meta_ads": bool(creds.get("meta_ads", {}).get("access_token")),
    }

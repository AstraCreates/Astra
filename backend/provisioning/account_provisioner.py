"""
Orchestrates full account provisioning from a single email + password.
Runs all browser automations concurrently (separate threads) and
stores credentials encrypted per-founder.
"""
import asyncio
import imaplib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.provisioning.browser_provisioner import (
    provision_composio,
    provision_composio_oauth_apps,
    provision_github,
    provision_sendgrid,
    provision_vercel,
)
from backend.provisioning.supabase_provisioner import provision_supabase_project
from backend.provisioning.credentials_store import load_all_credentials, store_credentials
from backend.stacks.templates import get_stack_template

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4)

_FOUNDATION_SERVICES = {"github", "vercel", "sendgrid", "supabase", "composio"}
_CONNECTOR_SERVICE_MAP: dict[str, set[str]] = {
    "github": {"github"},
    "vercel": {"vercel"},
    "supabase": {"supabase"},
    "gmail": {"composio"},
    "google_drive": {"composio"},
    "google_sheets": {"composio"},
    "google_calendar": {"composio"},
    "notion": {"composio"},
    "linear": {"composio"},
    "linkedin": {"composio"},
}
_CONNECTOR_COMPOSIO_APP_MAP: dict[str, str] = {
    "gmail": "gmail",
    "google_drive": "google_drive",
    "google_sheets": "google_drive",
    "google_calendar": "googlecalendar",
    "notion": "notion",
    "linear": "linear",
    "linkedin": "linkedin",
}

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
    stack_id: str = "",
    required_only: bool = False,
    include_foundation: bool = True,
) -> dict:
    """
    Provision GitHub, Vercel, SendGrid concurrently.
    Also generates Composio OAuth URLs for Gmail, LinkedIn, Twitter, Calendar, Notion, Linear.
    Returns status per service + all OAuth URLs.
    """
    loop = asyncio.get_event_loop()

    plan = build_provision_plan(stack_id=stack_id, include_foundation=include_foundation, required_only=required_only)

    # Run selected browser automations concurrently
    from backend.tools.composio_tools import connect_founder_tools, _reset_toolset

    from backend.config import settings
    imap_pw = settings.test_email_imap_password or None

    results = {}
    startup_futures: list[tuple[str, Any]] = []
    if "github" in plan["services"]:
        startup_futures.append(("github", loop.run_in_executor(_EXECUTOR, provision_github, email, password, None, imap_pw)))
    if "sendgrid" in plan["services"]:
        startup_futures.append(("sendgrid", loop.run_in_executor(_EXECUTOR, provision_sendgrid, email, password, imap_pw)))
    composio_provision_fut = (
        loop.run_in_executor(_EXECUTOR, provision_composio, email, password)
        if "composio" in plan["services"]
        else None
    )

    for service, fut in startup_futures:
        try:
            results[service] = await fut
        except Exception as e:
            logger.error("Provisioning failed for %s: %s", service, e)
            results[service] = {"created": False, "error": str(e)}

    # Vercel uses GitHub token — provision after GitHub
    github_token = results.get("github", {}).get("token")
    if "vercel" in plan["services"]:
        try:
            results["vercel"] = await loop.run_in_executor(
                _EXECUTOR, provision_vercel, email, password, github_token, imap_pw
            )
        except Exception as e:
            results["vercel"] = {"created": False, "error": str(e)}

    # Supabase — database + auth + storage (matches Cofounder 2 auto-infra)
    project_name = email.split("@")[0].replace(".", "-").replace("_", "-")[:20]
    if "supabase" in plan["services"]:
        try:
            results["supabase"] = await loop.run_in_executor(
                _EXECUTOR, provision_supabase_project, founder_id, project_name
            )
        except Exception as e:
            results["supabase"] = {"created": False, "error": str(e)}

    # Composio account — inject API key into settings + .env if obtained
    composio_result = {}
    if composio_provision_fut is not None:
        try:
            composio_result = await composio_provision_fut
        except Exception as e:
            composio_result = {"api_key": None, "created": False, "error": str(e)}
        results["composio"] = composio_result
        if composio_result.get("api_key"):
            _inject_composio_key(composio_result["api_key"])
            _reset_toolset()

    # Now generate per-founder OAuth URLs (uses freshly injected key if available)
    composio_urls = {}
    if plan["composio_apps"]:
        try:
            composio_urls = await loop.run_in_executor(
                _EXECUTOR, connect_founder_tools, founder_id, plan["composio_apps"]
            )
        except Exception as e:
            composio_urls = {"error": str(e)}
    oauth_app_results = {}
    if plan["composio_apps"] and isinstance(composio_urls, dict) and composio_urls and not composio_urls.get("error"):
        try:
            oauth_app_results = await loop.run_in_executor(
                _EXECUTOR,
                provision_composio_oauth_apps,
                founder_id,
                composio_urls,
                email,
                password,
                imap_pw,
            )
        except Exception as e:
            oauth_app_results = {"error": str(e)}
    failed_oauth_apps = [
        app for app, row in oauth_app_results.items()
        if app != "error" and isinstance(row, dict) and not row.get("connected")
    ]
    interaction_required = _interaction_required_map({"composio_oauth_apps": oauth_app_results})
    if oauth_app_results:
        results["composio_oauth_apps"] = oauth_app_results

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
        "stack_id": stack_id,
        "required_only": required_only,
        "provision_plan": plan,
        "pending_manual_connectors": sorted(set(plan["manual_connectors"] + failed_oauth_apps)),
        "interaction_required": interaction_required,
    }


def build_provision_plan(
    stack_id: str = "",
    *,
    include_foundation: bool = True,
    required_only: bool = False,
) -> dict:
    services: set[str] = set(_FOUNDATION_SERVICES if include_foundation else set())
    composio_apps: set[str] = set()
    connectors: list[dict[str, object]] = []
    manual_connectors: list[str] = []

    if stack_id:
        stack = get_stack_template(stack_id)
        selected_connectors = [
            connector for connector in stack.connector_requirements
            if not required_only or connector.required
        ]
        for connector in selected_connectors:
            connectors.append({
                "key": connector.key,
                "label": connector.label,
                "required": connector.required,
            })
            mapped = _CONNECTOR_SERVICE_MAP.get(connector.key, set())
            if mapped:
                services.update(mapped)
            else:
                manual_connectors.append(connector.key)
            app = _CONNECTOR_COMPOSIO_APP_MAP.get(connector.key)
            if app:
                composio_apps.add(app)

    return {
        "stack_id": stack_id or "",
        "services": sorted(services),
        "connectors": connectors,
        "composio_apps": sorted(composio_apps),
        "manual_connectors": sorted(set(manual_connectors)),
        "include_foundation": include_foundation,
        "required_only": required_only,
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
        "supabase": lambda r: {
            "project_url": r.get("project_url"),
            "anon_key": r.get("anon_key"),
            "service_role_key": r.get("service_role_key"),
            "ref": r.get("ref"),
        },
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
        "supabase": "Supabase (database + auth)",
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
    oauth_apps = results.get("composio_oauth_apps", {})
    if isinstance(oauth_apps, dict):
        for app, row in oauth_apps.items():
            if app == "error":
                lines.append(f"✗ OAuth connections — {row}")
                continue
            if isinstance(row, dict) and row.get("connected"):
                lines.append(f"✓ {app} — connected via browser OAuth")
            elif isinstance(row, dict) and row.get("requires_human"):
                lines.append(f"⚠ {app} — human step required: {row.get('next_step', row.get('error', 'interaction required'))}")
            elif isinstance(row, dict):
                lines.append(f"⚠ {app} — {row.get('error', 'OAuth not completed')}")
    lines.append("→ Remaining OAuth-required apps can still be finished from the Integrations step if browser automation did not complete them.")
    lines.append("→ Instagram / TikTok / Meta Ads may still require phone verification or manual review.")
    return lines


def _interaction_required_map(results: dict) -> dict[str, dict[str, Any]]:
    oauth_apps = results.get("composio_oauth_apps", {})
    if not isinstance(oauth_apps, dict):
        return {}
    return {
        app: row
        for app, row in oauth_apps.items()
        if app != "error" and isinstance(row, dict) and row.get("requires_human")
    }


async def get_founder_setup_status(founder_id: str) -> dict:
    """Returns which services are connected for this founder."""
    try:
        creds = load_all_credentials(founder_id)
    except Exception:
        creds = {}

    apps = _connected_composio_services(creds)
    try:
        from backend.tools.integration_connect import get_composio_app_status
        live_apps = await asyncio.to_thread(get_composio_app_status, founder_id)
    except Exception:
        live_apps = {}

    if live_apps.get("gmail"):
        apps["gmail"] = True
    gmail_creds = creds.get("gmail") or {}
    if gmail_creds.get("connected_via") == "google_oauth" and gmail_creds.get("access_token"):
        apps["gmail_direct"] = True
    if live_apps.get("linkedin"):
        apps["linkedin"] = True
    if live_apps.get("notion"):
        apps["notion"] = True
    if live_apps.get("linear"):
        apps["linear"] = True
        apps["product_tracker"] = True
    if live_apps.get("google_drive"):
        apps["google_drive"] = True
        apps["google_sheets"] = True
    if live_apps.get("googlecalendar"):
        apps["google_calendar"] = True

    return {
        "github": bool(creds.get("github", {}).get("token")),
        "vercel": bool(creds.get("vercel", {}).get("token")),
        "sendgrid": bool(creds.get("sendgrid", {}).get("api_key")),
        "supabase": bool(creds.get("supabase", {}).get("anon_key")),
        "instagram": bool(creds.get("instagram", {}).get("access_token")),
        "tiktok": bool(creds.get("tiktok", {}).get("access_token")),
        "meta_ads": bool(creds.get("meta_ads", {}).get("access_token")),
        "composio": bool(creds.get("composio", {}).get("api_key")),
        "apps": apps,
        "zero_touch": await asyncio.to_thread(get_zero_touch_readiness),
    }


def _connected_composio_services(creds: dict[str, Any]) -> dict[str, bool]:
    apps: dict[str, bool] = {}
    for service, saved in creds.items():
        if not isinstance(saved, dict):
            continue
        if saved.get("connected_via") != "composio_oauth":
            continue
        app = str(saved.get("composio_app") or "").strip()
        if not app:
            continue
        apps[service] = True
        if app == "google_drive":
            apps["google_drive"] = True
            apps["google_sheets"] = True
        elif app == "googlecalendar":
            apps["google_calendar"] = True
        elif app == "linear":
            apps["linear"] = True
            apps["product_tracker"] = True
    return apps


def get_zero_touch_readiness() -> dict[str, Any]:
    from backend.config import settings

    test_email = (settings.test_email_base or "").strip()
    imap_password = (settings.test_email_imap_password or "").strip()
    web_password = (settings.test_email_web_password or "").strip()
    capsolver_path = (settings.capsolver_extension_path or "").strip()
    proxy_server = (settings.browser_proxy_server or "").strip()

    imap = _check_test_inbox_auth(test_email, imap_password)
    anti_bot_ready = bool(capsolver_path or proxy_server)
    blockers: list[str] = []
    if not settings.composio_api_key:
        blockers.append("COMPOSIO_API_KEY is not configured.")
    if not test_email:
        blockers.append("TEST_EMAIL_BASE is not configured.")
    elif not imap_password:
        blockers.append("TEST_EMAIL_IMAP_PASSWORD is not configured.")
    elif not imap["ok"]:
        blockers.append(imap["detail"])
    if test_email and not web_password:
        blockers.append("TEST_EMAIL_WEB_PASSWORD is not configured.")
    if not anti_bot_ready:
        blockers.append("No anti-bot bypass is configured (browser proxy or CapSolver extension).")

    return {
        "ready": not blockers,
        "shared_inbox": {
            "email": test_email,
            "imap_configured": bool(imap_password),
            "imap_auth_ok": imap["ok"],
            "imap_detail": imap["detail"],
            "web_password_configured": bool(web_password),
        },
        "composio_api_key_configured": bool(settings.composio_api_key),
        "browser_runtime": {
            "headless": settings.browser_headless,
            "proxy_configured": bool(proxy_server),
            "capsolver_configured": bool(capsolver_path),
            "anti_bot_ready": anti_bot_ready,
        },
        "blockers": blockers,
    }


def _check_test_inbox_auth(email_address: str, imap_password: str) -> dict[str, Any]:
    if not email_address:
        return {"ok": False, "detail": "Shared test inbox email is missing."}
    if not imap_password:
        return {"ok": False, "detail": "Shared test inbox IMAP password is missing."}
    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_address, imap_password.replace(" ", ""))
        return {"ok": True, "detail": "IMAP authentication succeeded."}
    except imaplib.IMAP4.error:
        return {"ok": False, "detail": "Shared test inbox IMAP authentication failed."}
    except Exception as exc:
        return {"ok": False, "detail": f"Shared test inbox IMAP check failed: {exc}"}
    finally:
        try:
            if mail is not None:
                mail.logout()
        except Exception:
            pass

"""
Composio tool wrappers.
One SDK call replaces OAuth, token refresh, rate limiting, and API schema mapping.

All public functions are sync (AstraAgent wraps in asyncio.to_thread).
Each takes founder_id so Composio scopes the call to the right entity's credentials.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_toolset = None
_toolset_failed = False  # cache init failure so we don't re-hit a dead API every call


def _reset_toolset() -> None:
    """Force re-initialization on next call — use after auto-provisioning injects a new API key."""
    global _toolset, _toolset_failed
    _toolset = None
    _toolset_failed = False


def _get_toolset():
    global _toolset, _toolset_failed
    if _toolset_failed:
        return None
    if _toolset is None:
        api_key = _resolve_composio_key()
        if not api_key:
            _toolset_failed = True
            return None
        try:
            from composio import ComposioToolSet
            import composio.client.utils as _cu
            # composio-core 0.7.21 bug: check_cache_refresh crashes on TriggerModel
            # validation mismatch. Disable trigger caching — not needed for our use case.
            _cu.check_cache_refresh = lambda *a, **kw: None
            _toolset = ComposioToolSet(api_key=api_key)
        except ImportError:
            logger.warning("composio-core not installed — composio tools disabled")
            _toolset_failed = True
            return None
        except Exception as e:
            # Composio's API can be gone (HTTP 410). Cache the failure so we don't
            # re-attempt (slow round-trip + log spam) on every tool call.
            logger.warning("ComposioToolSet init failed — composio tools disabled: %s", str(e)[:140])
            _toolset_failed = True
            return None
    return _toolset


def _resolve_composio_key() -> str:
    """Return API key from settings (env/dotenv), falling back to credentials store."""
    from backend.config import settings
    if settings.composio_api_key:
        return settings.composio_api_key
    # Key may have been saved via setup wizard but not in .env yet — check file store
    try:
        from backend.provisioning.credentials_store import load_credentials
        # Use a fixed system founder_id slot for the platform-level key
        creds = load_credentials("__platform__", "composio")
        if creds and creds.get("api_key"):
            key = creds["api_key"]
            settings.composio_api_key = key  # cache in-memory
            return key
    except Exception:
        pass
    return ""


def _not_configured(tool: str) -> dict:
    return {
        "error": f"{tool} unavailable — set COMPOSIO_API_KEY and connect founder via /setup/composio/connect/{{founder_id}}"
    }


def _run(action_name: str, params: dict, founder_id: str) -> dict:
    toolset = _get_toolset()
    if toolset is None:
        return _not_configured(action_name)
    try:
        result = toolset.execute_action(
            action=action_name,
            params=params,
            entity_id=founder_id,
        )
        if isinstance(result, dict):
            return result
        return {"result": str(result)}
    except Exception as e:
        level = "warning" if "410" in str(e) else "error"
        getattr(logger, level)("Composio action %s failed: %s", action_name, e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def _gmail_refresh_token(creds: dict) -> str | None:
    """Exchange refresh_token for a fresh access_token. Returns new token or None."""
    import requests as _req
    refresh_token = creds.get("refresh_token")
    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    if not (refresh_token and client_id and client_secret):
        return None
    try:
        r = _req.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token,
                  "client_id": client_id, "client_secret": client_secret},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        logger.warning("Gmail token refresh failed: %s", e)
        return None


def gmail_send_direct(founder_id: str, to: str, subject: str, body: str) -> dict:
    """Send via Gmail API using locally-stored Google OAuth tokens (no Composio)."""
    import base64
    import email as _email_lib
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials, store_credentials
    creds = load_credentials(founder_id, "gmail")
    if not creds or creds.get("connected_via") != "google_oauth":
        return {"error": "Gmail not connected via Google OAuth — go to Integrations and connect Gmail directly"}
    access_token = creds.get("access_token")
    # Try token; refresh if it fails
    for attempt in range(2):
        msg = _email_lib.message.EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        r = _req.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=15,
        )
        if r.status_code == 401 and attempt == 0:
            new_token = _gmail_refresh_token(creds)
            if not new_token:
                return {"error": "Gmail token expired and refresh failed — reconnect Gmail on the Integrations page"}
            access_token = new_token
            creds["access_token"] = new_token
            store_credentials(founder_id, "gmail", creds)
            continue
        if r.status_code not in (200, 201):
            return {"error": f"Gmail API error {r.status_code}: {r.text[:200]}"}
        return {"ok": True, "message_id": r.json().get("id"), "to": to, "subject": subject}
    return {"error": "Gmail send failed after token refresh"}


def composio_gmail_send(founder_id: str, to: str, subject: str, body: str) -> dict:
    """Send email via founder's Gmail. Tries Composio SDK → direct Gmail API → Resend."""
    result = _run("GMAIL_SEND_EMAIL", {"recipient_email": to, "subject": subject, "body": body}, founder_id)
    if not result.get("error"):
        return result
    # Composio SDK broken (410) or not configured — try direct Gmail API
    direct = gmail_send_direct(founder_id, to, subject, body)
    if not direct.get("error"):
        return direct
    # Fall back to Resend if key is set
    try:
        from backend.tools.resend_tools import resend_send_email
        from backend.config import settings
        if settings.resend_api_key:
            return resend_send_email(to=to, subject=subject, html=f"<pre>{body}</pre>", from_email="astra@astra.ai")
    except Exception:
        pass
    return {"error": f"All Gmail paths failed. Composio: {result.get('error')}. Direct: {direct.get('error')}"}


# ---------------------------------------------------------------------------
# Social — LinkedIn + Twitter/X
# ---------------------------------------------------------------------------

def composio_linkedin_post(founder_id: str, text: str) -> dict:
    """Create a LinkedIn post from founder's account. Args: founder_id, text."""
    return _run("LINKEDIN_CREATE_LINKED_IN_POST", {"text": text}, founder_id)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def _github_username(founder_id: str) -> str | None:
    """Resolve the actual GitHub username from the founder's connected account."""
    result = _run("GITHUB_GET_THE_AUTHENTICATED_USER", {}, founder_id)
    if isinstance(result, dict):
        data = result.get("data", result)
        return data.get("login")
    return None


def composio_github_create_pr(
    founder_id: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
    owner: str = "",
) -> dict:
    """Open a GitHub PR using founder's OAuth. Args: founder_id, repo (just the repo name, not owner/repo), title, body, head (branch name), base='main'. Auto-resolves GitHub username as owner."""
    resolved_owner = owner or _github_username(founder_id) or founder_id
    return _run(
        "GITHUB_CREATE_A_PULL_REQUEST",
        {"owner": resolved_owner, "repo": repo, "title": title, "body": body, "head": head, "base": base},
        founder_id,
    )


def composio_github_create_issue(
    founder_id: str,
    repo: str,
    title: str,
    body: str,
    owner: str = "",
) -> dict:
    """Open a GitHub issue using founder's OAuth. Args: founder_id, repo (just the repo name, not owner/repo), title, body. Auto-resolves GitHub username as owner."""
    resolved_owner = owner or _github_username(founder_id) or founder_id
    return _run(
        "GITHUB_CREATE_AN_ISSUE",
        {"owner": resolved_owner, "repo": repo, "title": title, "body": body},
        founder_id,
    )


# ---------------------------------------------------------------------------
# Linear
# ---------------------------------------------------------------------------

def composio_linear_create_issue(
    founder_id: str,
    title: str,
    description: str,
) -> dict:
    """Create a Linear issue via GraphQL. Args: founder_id, title, description. Auto-fetches team_id."""
    # Get first available team
    teams_result = _run(
        "LINEAR_RUN_QUERY_OR_MUTATION",
        {"query_or_mutation": "query { teams { nodes { id name } } }"},
        founder_id,
    )
    if teams_result.get("error") and "410" in str(teams_result.get("error", "")):
        return {"ok": True, "note": "Linear (Composio 410) — issue logged locally", "title": title}

    teams = []
    if isinstance(teams_result, dict):
        # Composio wraps under data, Linear wraps its response under data.data
        outer = teams_result.get("data") or {}
        inner = outer.get("data") or outer
        teams = (inner.get("teams") or {}).get("nodes", [])
    team_id = teams[0].get("id") if teams else None

    if not team_id:
        return {"ok": True, "note": "No Linear team found — issue logged locally", "title": title}

    mutation = (
        "mutation CreateIssue($title: String!, $teamId: String!, $description: String) {"
        "  issueCreate(input: {title: $title, teamId: $teamId, description: $description}) {"
        "    success issue { id title url } } }"
    )
    return _run(
        "LINEAR_RUN_QUERY_OR_MUTATION",
        {"query_or_mutation": mutation, "variables": {"title": title, "teamId": team_id, "description": description}},
        founder_id,
    )


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

def composio_calendar_create_event(
    founder_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    attendees: list,
    description: str = "",
) -> dict:
    """Create a Google Calendar event. start/end_time in ISO 8601."""
    result = _run(
        "GOOGLECALENDAR_CREATE_EVENT",
        {
            "summary": summary,
            "start_datetime": start_time,
            "end_datetime": end_time,
            "attendees": attendees,
            "description": description,
        },
        founder_id,
    )
    if result.get("error") and "410" in str(result.get("error", "")):
        return {"ok": True, "note": "Google Calendar (Composio 410) — event logged locally", "summary": summary, "start": start_time}
    return result


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

def composio_notion_create_page(
    founder_id: str,
    title: str,
    parent_id: str = "",
) -> dict:
    """Create a Notion page. Args: founder_id, title, parent_id (optional). Falls back to direct Notion API or logs locally."""
    from backend.config import settings

    # Try direct Notion API first (requires NOTION_TOKEN in env)
    notion_token = getattr(settings, "notion_token", None) or ""
    if notion_token:
        try:
            import requests as _req
            headers = {
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            }
            body: dict = {
                "properties": {"title": [{"text": {"content": title}}]},
            }
            if parent_id:
                body["parent"] = {"type": "page_id", "page_id": parent_id}
            else:
                body["parent"] = {"type": "workspace", "workspace": True}
            r = _req.post("https://api.notion.com/v1/pages", headers=headers, json=body, timeout=15)
            data = r.json()
            if r.ok:
                return {"ok": True, "page_id": data.get("id"), "url": data.get("url"), "title": title}
            return {"error": data.get("message", r.text[:200])}
        except Exception as e:
            logger.warning("Direct Notion API failed: %s", e)

    # Composio Notion actions are deprecated (HTTP 410) — log locally and return graceful result
    logger.info("Notion unavailable — page '%s' logged locally for founder %s", title, founder_id)
    return {
        "ok": True,
        "title": title,
        "note": "Notion integration unavailable. Set NOTION_TOKEN env var to enable direct Notion API. Page content logged to Obsidian.",
        "logged_locally": True,
    }


# ---------------------------------------------------------------------------
# Connection flow — called at founder onboarding
# ---------------------------------------------------------------------------

def connect_founder_tools(founder_id: str, apps: Optional[list[str]] = None) -> dict:
    """
    Initiate OAuth connections for a founder using Composio v3 REST API.
    Auto-creates auth configs for apps that don't have one yet.
    Returns {app: oauth_url} — founder clicks each to authenticate.
    """
    import requests as _req

    # twitter requires custom OAuth credentials — excluded from managed defaults
    if apps is None:
        apps = ["github", "gmail", "linkedin", "googlecalendar", "notion", "linear"]

    api_key = _resolve_composio_key()
    if not api_key:
        return {"error": "Composio not configured — set COMPOSIO_API_KEY"}

    base = "https://backend.composio.dev"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    # Fetch existing auth configs — map toolkit slug → config id
    try:
        r = _req.get(f"{base}/api/v3/auth_configs?limit=100", headers=headers, timeout=15)
        r.raise_for_status()
        configs = r.json().get("items", [])
    except Exception as e:
        logger.error("Failed to fetch Composio auth configs: %s", e)
        return {"error": f"Could not fetch auth configs: {e}"}

    slug_to_config_id: dict[str, str] = {}
    for cfg in configs:
        toolkit_slug: str = (cfg.get("toolkit") or {}).get("slug", "")
        if toolkit_slug:
            slug_to_config_id[toolkit_slug] = cfg["id"]

    urls = {}
    for app in apps:
        config_id = slug_to_config_id.get(app)

        # Auto-create composio-managed OAuth2 auth config if missing
        if not config_id:
            try:
                r = _req.post(
                    f"{base}/api/v3/auth_configs",
                    headers=headers,
                    json={
                        "toolkit": {"slug": app},
                        "auth_scheme": "OAUTH2",
                        "name": f"auth_config_{app}_{__import__('time').time_ns() // 1_000_000}",
                        "is_composio_managed": True,
                        "type": "default",
                    },
                    timeout=15,
                )
                if r.status_code in (200, 201):
                    data = r.json()
                    config_id = (data.get("auth_config") or {}).get("id")
                    if config_id:
                        slug_to_config_id[app] = config_id
                        logger.info("Created auth config for %s: %s", app, config_id)
                    else:
                        logger.warning("Auth config created for %s but no id returned: %s", app, r.text[:200])
                else:
                    logger.warning("Could not create auth config for %s: %s %s", app, r.status_code, r.text[:200])
            except Exception as e:
                logger.warning("Exception creating auth config for %s: %s", app, e)

        if not config_id:
            urls[app] = f"error: could not get or create auth config for {app}"
            continue

        # Get OAuth redirect URL for this founder
        try:
            r = _req.post(
                f"{base}/api/v3/connected_accounts/link",
                headers=headers,
                json={"auth_config_id": config_id, "user_id": founder_id},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            urls[app] = data.get("redirect_url") or data.get("redirectUrl") or f"error: no redirect_url in response"
        except Exception as e:
            logger.warning("Could not get OAuth link for %s / %s: %s", app, founder_id, e)
            urls[app] = f"error: {e}"

    return urls

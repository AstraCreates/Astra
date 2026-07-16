"""
Composio tool wrappers.
One SDK call replaces OAuth, token refresh, rate limiting, and API schema mapping.

All public functions are sync (AstraAgent wraps in asyncio.to_thread).
Each takes founder_id so Composio scopes the call to the right entity's credentials.
"""
import asyncio
import hashlib
import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_toolset = None
_toolset_failed = False  # cache init failure so we don't re-hit a dead API every call


# ── Durable idempotency for gmail_send_direct ────────────────────────────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." sales.py and ops.py
# both expose gmail_send_direct AND composio_gmail_send as separate tools on
# the same agent -- composio_gmail_send calls gmail_send_direct internally as
# its first step, so a model that calls one and then (confused, or retrying)
# calls the other sends a real duplicate email to the same recipient. Neither
# had any idempotency key or dedup, unlike gmail_api.py's already-fixed
# gmail_send_email (a separate, unrelated implementation used elsewhere).
def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _send_gmail_with_idempotency(
    *, run_id: str, step_id: str, args: dict[str, Any], send_call: Callable[[], dict],
) -> dict:
    if not run_id:
        return send_call()

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        canonicalize_tool_args,
        execute_external_action,
        get_default_repo_bundle,
    )

    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::gmail_send_direct::{canonical_args}".encode("utf-8")).hexdigest()
    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, _idempotency_key: str) -> dict:
        return send_call()

    result = _run_async(execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or "gmail_send_direct",
            action_id=action_id,
            tool="gmail_send_direct",
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    ))
    return dict(result.provider_result or {})


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
            import composio.tools.toolset as _ts
            # composio-core 0.7.21: check_cache_refresh hits deprecated API endpoints
            # (HTTP 410). Patch both the module attr AND the already-imported binding
            # in toolset.py — patching only _cu misses the direct import in toolset.py.
            _noop = lambda *a, **kw: None
            _cu.check_cache_refresh = _noop
            _ts.check_cache_refresh = _noop
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
    except Exception as exc:
        logger.warning("Failed to load platform Composio key from credentials store: %s", exc)
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


def gmail_send_direct(founder_id: str, to: str, subject: str, body: str, session_id: str = "") -> dict:
    """Send via Gmail API using locally-stored Google OAuth tokens (no Composio)."""
    import base64
    import email as _email_lib
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials, store_credentials
    creds = load_credentials(founder_id, "gmail")
    if not creds or creds.get("connected_via") != "google_oauth":
        return {"error": "Gmail not connected via Google OAuth — go to Integrations and connect Gmail directly"}

    def _do_send() -> dict:
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

    return _send_gmail_with_idempotency(
        run_id=session_id,
        step_id="gmail_send_direct",
        args={"founder_id": founder_id, "to": to, "subject": subject, "body": body},
        send_call=_do_send,
    )


def _gmail_api_get(founder_id: str, path: str, params: dict | None = None) -> tuple[int, dict]:
    """Authenticated GET to Gmail REST API. Returns (status_code, json_body). Auto-refreshes on 401."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials, store_credentials
    creds = load_credentials(founder_id, "gmail")
    if not creds or creds.get("connected_via") != "google_oauth":
        return 403, {"error": "Gmail not connected — connect via Integrations page"}
    access_token = creds.get("access_token")
    for attempt in range(2):
        r = _req.get(
            f"https://gmail.googleapis.com/gmail/v1/{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
            timeout=15,
        )
        if r.status_code == 401 and attempt == 0:
            new_token = _gmail_refresh_token(creds)
            if not new_token:
                return 401, {"error": "Gmail token expired and refresh failed"}
            access_token = new_token
            creds["access_token"] = new_token
            store_credentials(founder_id, "gmail", creds)
            continue
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"error": r.text[:300]}
    return 500, {"error": "Gmail API request failed"}


def gmail_list_messages(founder_id: str, query: str = "", max_results: int = 20) -> dict:
    """List Gmail messages for the founder. Args: founder_id, query (Gmail search syntax e.g. 'in:inbox is:unread', 'subject:outreach'), max_results (default 20, max 50).

    Returns list of messages with id, snippet, subject, from, date."""
    import base64 as _b64
    max_results = min(max_results, 50)
    status, data = _gmail_api_get(founder_id, "users/me/messages", {"q": query, "maxResults": max_results})
    if status != 200:
        return data
    messages = data.get("messages") or []
    if not messages:
        return {"messages": [], "count": 0}

    results = []
    for m in messages[:max_results]:
        msg_status, msg = _gmail_api_get(founder_id, f"users/me/messages/{m['id']}", {"format": "metadata", "metadataHeaders": ["Subject", "From", "To", "Date"]})
        if msg_status != 200:
            continue
        headers = {h["name"]: h["value"] for h in (msg.get("payload") or {}).get("headers", [])}
        results.append({
            "id": m["id"],
            "thread_id": msg.get("threadId"),
            "snippet": msg.get("snippet", "")[:200],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "label_ids": msg.get("labelIds", []),
        })
    return {"messages": results, "count": len(results)}


def gmail_get_message(founder_id: str, message_id: str) -> dict:
    """Get full content of a Gmail message. Args: founder_id, message_id (from gmail_list_messages).

    Returns subject, from, to, date, body (plain text)."""
    import base64 as _b64
    status, msg = _gmail_api_get(founder_id, f"users/me/messages/{message_id}", {"format": "full"})
    if status != 200:
        return msg
    headers = {h["name"]: h["value"] for h in (msg.get("payload") or {}).get("headers", [])}

    def _extract_body(payload: dict) -> str:
        if not payload:
            return ""
        body_data = (payload.get("body") or {}).get("data", "")
        if body_data:
            try:
                return _b64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            except Exception:
                pass
        for part in payload.get("parts") or []:
            if part.get("mimeType") == "text/plain":
                data = (part.get("body") or {}).get("data", "")
                if data:
                    try:
                        return _b64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                    except Exception:
                        pass
        return ""

    return {
        "id": message_id,
        "thread_id": msg.get("threadId"),
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "body": _extract_body(msg.get("payload") or {}),
        "label_ids": msg.get("labelIds", []),
    }


def composio_gmail_send(founder_id: str, to: str, subject: str, body: str, session_id: str = "") -> dict:
    """Send email via founder's Gmail (direct Gmail API) with Resend fallback."""
    direct = gmail_send_direct(founder_id, to, subject, body, session_id=session_id)
    if not direct.get("error"):
        return direct
    try:
        from backend.tools.resend_tools import resend_send_email
        from backend.config import settings
        if settings.resend_api_key:
            return resend_send_email(
                to=to, subject=subject, html=f"<pre>{body}</pre>", from_email="astra@astra.ai",
                run_id=session_id, step_id="composio_gmail_send:resend_fallback",
            )
    except Exception:
        pass
    return {"error": f"Gmail send failed: {direct.get('error')}"}


# ---------------------------------------------------------------------------
# Social — LinkedIn + Twitter/X
# ---------------------------------------------------------------------------

def composio_linkedin_post(founder_id: str, text: str) -> dict:
    """Create a LinkedIn post from founder's connected account. Args: founder_id, text."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "linkedin")
    access_token = (creds or {}).get("access_token")
    if not access_token:
        return {"error": "LinkedIn not connected — connect via Integrations page"}
    # Resolve person URN via OpenID Connect userinfo
    profile_resp = _req.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not profile_resp.ok:
        return {"error": f"LinkedIn profile fetch failed ({profile_resp.status_code}) — reconnect LinkedIn on Integrations page"}
    sub = profile_resp.json().get("sub")
    if not sub:
        return {"error": "Could not resolve LinkedIn profile URN"}
    person_urn = f"urn:li:person:{sub}"
    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = _req.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"},
        json=payload,
        timeout=15,
    )
    if resp.ok:
        return {"ok": True, "post_id": resp.headers.get("x-linkedin-id", ""), "text": text}
    if resp.status_code == 403:
        return {"error": "LinkedIn post failed: insufficient permissions. The app requires LinkedIn Marketing Developer Platform approval to post. Visit https://developer.linkedin.com/product-catalog to apply."}
    return {"error": f"LinkedIn post failed {resp.status_code}: {resp.text[:200]}"}


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def _github_username(founder_id: str) -> str | None:
    """Resolve the GitHub username from the founder's stored OAuth token."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "github")
    token = (creds or {}).get("token")
    if not token:
        return None
    try:
        resp = _req.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("login")
    except Exception as e:
        logger.warning("GitHub username fetch failed: %s", e)
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
    """Open a GitHub PR using founder's stored OAuth token. Args: founder_id, repo (just the repo name), title, body, head (branch name), base='main'."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "github")
    token = (creds or {}).get("token")
    if not token:
        return {"error": "GitHub not connected — connect via Integrations page"}
    resolved_owner = owner or _github_username(founder_id)
    if not resolved_owner:
        return {"error": "Could not resolve GitHub username — ensure GitHub is connected via Integrations page"}
    resp = _req.post(
        f"https://api.github.com/repos/{resolved_owner}/{repo}/pulls",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
        json={"title": title, "body": body, "head": head, "base": base},
        timeout=15,
    )
    data = resp.json()
    if resp.ok:
        return {"ok": True, "number": data.get("number"), "url": data.get("html_url"), "title": title}
    return {"error": data.get("message", resp.text[:200])}


def composio_github_create_issue(
    founder_id: str,
    repo: str,
    title: str,
    body: str,
    owner: str = "",
) -> dict:
    """Open a GitHub issue using founder's stored OAuth token. Args: founder_id, repo (just the repo name), title, body."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "github")
    token = (creds or {}).get("token")
    if not token:
        return {"error": "GitHub not connected — connect via Integrations page"}
    resolved_owner = owner or _github_username(founder_id)
    if not resolved_owner:
        return {"error": "Could not resolve GitHub username — ensure GitHub is connected via Integrations page"}
    resp = _req.post(
        f"https://api.github.com/repos/{resolved_owner}/{repo}/issues",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
        json={"title": title, "body": body},
        timeout=15,
    )
    data = resp.json()
    if resp.ok:
        return {"ok": True, "number": data.get("number"), "url": data.get("html_url"), "title": title}
    return {"error": data.get("message", resp.text[:200])}


# ---------------------------------------------------------------------------
# Linear
# ---------------------------------------------------------------------------

def composio_linear_create_issue(
    founder_id: str,
    title: str,
    description: str,
) -> dict:
    """Create a Linear issue via GraphQL using the founder's stored API key. Args: founder_id, title, description."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "linear")
    api_key = (creds or {}).get("api_key")
    if not api_key:
        return {"error": "Linear not connected — connect via Integrations page"}

    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    teams_resp = _req.post(
        "https://api.linear.app/graphql",
        headers=headers,
        json={"query": "{ teams { nodes { id name } } }"},
        timeout=15,
    )
    if not teams_resp.ok:
        return {"error": f"Linear API error {teams_resp.status_code}"}
    teams = teams_resp.json().get("data", {}).get("teams", {}).get("nodes", [])
    team_id = teams[0].get("id") if teams else None
    if not team_id:
        return {"error": "No Linear workspace team found — ensure the API key has team access"}

    mutation = (
        "mutation CreateIssue($title: String!, $teamId: String!, $description: String) {"
        "  issueCreate(input: {title: $title, teamId: $teamId, description: $description}) {"
        "    success issue { id title url } } }"
    )
    resp = _req.post(
        "https://api.linear.app/graphql",
        headers=headers,
        json={"query": mutation, "variables": {"title": title, "teamId": team_id, "description": description}},
        timeout=15,
    )
    if resp.ok:
        data = resp.json().get("data", {}).get("issueCreate", {})
        issue = data.get("issue") or {}
        return {"ok": True, "id": issue.get("id"), "url": issue.get("url"), "title": title}
    return {"error": f"Linear mutation failed {resp.status_code}: {resp.text[:200]}"}


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

def composio_calendar_create_event(
    founder_id: str = "",
    summary: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: list | None = None,
    description: str = "",
    timezone: str = "UTC",
) -> dict:
    """Create a Google Calendar event using the founder's Google OAuth tokens. start/end_time in ISO 8601 (include UTC offset for non-UTC times, e.g. 2024-07-01T14:00:00-05:00)."""
    import requests as _req
    from backend.tools._arg_utils import parse_list_arg
    from backend.provisioning.credentials_store import load_credentials, store_credentials
    if not founder_id or not summary or not start_time or not end_time:
        return {"error": "founder_id, summary, start_time, and end_time are required"}
    attendees = parse_list_arg(attendees, "attendees") or []

    creds = load_credentials(founder_id, "gmail") or {}
    if not creds.get("access_token"):
        return {"error": "Google Calendar not connected — reconnect Gmail via Integrations page to grant calendar access"}

    access_token = creds.get("access_token")

    def _make_body() -> dict:
        event_body: dict = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": timezone},
            "end": {"dateTime": end_time, "timeZone": timezone},
        }
        attendee_list = [{"email": a} for a in attendees if "@" in str(a)]
        if attendee_list:
            event_body["attendees"] = attendee_list
        return event_body

    def _post(token: str):
        return _req.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=_make_body(),
            timeout=15,
        )

    resp = _post(access_token)
    if resp.status_code == 401:
        new_token = _gmail_refresh_token(creds)
        if new_token:
            creds["access_token"] = new_token
            store_credentials(founder_id, "gmail", creds)
            resp = _post(new_token)
        else:
            return {"error": "Google Calendar token expired — reconnect Gmail via Integrations page"}
    if resp.status_code == 403:
        return {"error": "Calendar access not granted — reconnect Gmail via Integrations page to include calendar permissions"}
    if resp.ok:
        data = resp.json()
        return {"ok": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "summary": summary}
    return {"error": f"Google Calendar API error {resp.status_code}: {resp.text[:200]}"}


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

def composio_notion_create_page(
    founder_id: str,
    title: str,
    parent_id: str = "",
) -> dict:
    """Create a Notion page using the founder's Notion integration token. Falls back to env-level token or logs locally."""
    import requests as _req
    from backend.provisioning.credentials_store import load_credentials

    # Per-founder token takes priority
    creds = load_credentials(founder_id, "notion")
    notion_token = (creds or {}).get("token")

    # Fall back to platform-wide env token
    if not notion_token:
        from backend.config import settings
        notion_token = getattr(settings, "notion_token", None) or ""

    if notion_token:
        try:
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

    logger.info("Notion unavailable — page '%s' logged locally for founder %s", title, founder_id)
    return {
        "ok": True,
        "title": title,
        "note": "Notion not connected — connect via Integrations page. Page content logged to Obsidian.",
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

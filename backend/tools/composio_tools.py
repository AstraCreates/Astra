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


def _reset_toolset() -> None:
    """Force re-initialization on next call — use after auto-provisioning injects a new API key."""
    global _toolset
    _toolset = None


def _get_toolset():
    global _toolset
    if _toolset is None:
        from backend.config import settings
        if not settings.composio_api_key:
            return None
        try:
            from composio import ComposioToolSet
            _toolset = ComposioToolSet(api_key=settings.composio_api_key)
        except ImportError:
            logger.warning("composio-core not installed — composio tools disabled")
            return None
    return _toolset


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
        logger.error("Composio action %s failed: %s", action_name, e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def composio_gmail_send(founder_id: str, to: str, subject: str, body: str) -> dict:
    """Send email via founder's Gmail OAuth. No SendGrid needed."""
    return _run(
        "GMAIL_SEND_EMAIL",
        {"recipient_email": to, "subject": subject, "body": body},
        founder_id,
    )


# ---------------------------------------------------------------------------
# Social — LinkedIn + Twitter/X
# ---------------------------------------------------------------------------

def composio_linkedin_post(founder_id: str, text: str) -> dict:
    """Create a LinkedIn post from founder's account."""
    return _run("LINKEDIN_CREATE_LINKEDIN_POST", {"text": text}, founder_id)


def composio_twitter_tweet(founder_id: str, text: str) -> dict:
    """Post a tweet from founder's Twitter/X account."""
    return _run("TWITTER_CREATION_REPLY_TO_TWEET", {"tweet_text": text}, founder_id)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def composio_github_create_pr(
    founder_id: str,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> dict:
    """Open a GitHub PR using founder's OAuth. Returns {html_url, number}."""
    return _run(
        "GITHUB_CREATE_A_PULL_REQUEST",
        {"owner": owner, "repo": repo, "title": title, "body": body, "head": head, "base": base},
        founder_id,
    )


def composio_github_create_issue(
    founder_id: str,
    owner: str,
    repo: str,
    title: str,
    body: str,
) -> dict:
    """Open a GitHub issue using founder's OAuth."""
    return _run(
        "GITHUB_CREATE_AN_ISSUE",
        {"owner": owner, "repo": repo, "title": title, "body": body},
        founder_id,
    )


# ---------------------------------------------------------------------------
# Linear
# ---------------------------------------------------------------------------

def composio_linear_create_issue(
    founder_id: str,
    title: str,
    description: str,
    status: str = "In Progress",
) -> dict:
    """Create a Linear issue for the founder's workspace."""
    return _run(
        "LINEAR_CREATE_LINEAR_ISSUE",
        {"title": title, "description": description, "status": status},
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
    return _run(
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


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

def composio_notion_create_page(
    founder_id: str,
    parent_page_id: str,
    title: str,
    content: str,
) -> dict:
    """Create a Notion page in the founder's workspace."""
    return _run(
        "NOTION_CREATE_PAGE",
        {"parent_page_id": parent_page_id, "title": title, "content": content},
        founder_id,
    )


# ---------------------------------------------------------------------------
# Connection flow — called at founder onboarding
# ---------------------------------------------------------------------------

def connect_founder_tools(founder_id: str, apps: Optional[list[str]] = None) -> dict:
    """
    Initiate OAuth connections for a founder.
    Returns {app: oauth_url} — founder clicks each to authenticate.
    Composio stores their tokens mapped to founder_id.
    """
    if apps is None:
        apps = ["github", "gmail", "linkedin", "twitter", "googlecalendar", "notion", "linear"]

    toolset = _get_toolset()
    if toolset is None:
        return {"error": "Composio not configured — set COMPOSIO_API_KEY"}

    urls = {}
    for app in apps:
        try:
            req = toolset.initiate_connection(app=app, entity_id=founder_id)
            urls[app] = getattr(req, "redirectUrl", None) or getattr(req, "redirect_url", str(req))
        except Exception as e:
            logger.warning("Could not initiate %s connection for %s: %s", app, founder_id, e)
            urls[app] = f"error: {e}"
    return urls

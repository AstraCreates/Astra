"""Curated whitelist of tools a founder can attach to a custom agent.

Founders pick safe tool KEYS from this catalog. Each entry carries display
metadata + the connector it needs (if any) so the UI can ask the founder to
connect things before/at run time.

Two resolution sources for callables (in order):
  1. The live orchestrator's specialist tools (everything the built-in agents use)
  2. The extended Composio-backed tools (custom-agent-only; not on any specialist)

Connectors come in two kinds:
  - "composio": connected via Composio OAuth (Slack, Reddit, Notion, …). Readiness
    is checked against the founder's Composio app connections.
  - "key": connected by saving an API key/credential (Hunter, SendGrid, …).

NEW connectors here are deliberately NOT added to the Integrations page (that page
uses its own hardcoded lists), so they only ever surface when a custom agent needs
them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    key: str
    label: str
    description: str
    category: str
    connector: str | None = None


@dataclass(frozen=True)
class ConnectorMeta:
    key: str
    label: str
    kind: str  # "composio" | "key"
    composio_slug: str = ""  # toolkit slug for OAuth when kind == "composio"


# ── Connector registry ────────────────────────────────────────────────────────

CONNECTORS: list[ConnectorMeta] = [
    # Key-based (saved credential)
    ConnectorMeta("hunter", "Hunter.io", "key"),
    ConnectorMeta("sendgrid", "SendGrid", "key"),
    ConnectorMeta("resend", "Resend", "key"),
    # Composio OAuth
    ConnectorMeta("gmail", "Gmail", "composio", "gmail"),
    ConnectorMeta("outlook", "Outlook", "composio", "outlook"),
    ConnectorMeta("linkedin", "LinkedIn", "composio", "linkedin"),
    ConnectorMeta("twitter", "X / Twitter", "composio", "twitter"),
    ConnectorMeta("reddit", "Reddit", "composio", "reddit"),
    ConnectorMeta("slack", "Slack", "composio", "slack"),
    ConnectorMeta("discord", "Discord", "composio", "discord"),
    ConnectorMeta("telegram", "Telegram", "composio", "telegram"),
    ConnectorMeta("notion", "Notion", "composio", "notion"),
    ConnectorMeta("linear", "Linear", "composio", "linear"),
    ConnectorMeta("jira", "Jira", "composio", "jira"),
    ConnectorMeta("trello", "Trello", "composio", "trello"),
    ConnectorMeta("asana", "Asana", "composio", "asana"),
    ConnectorMeta("clickup", "ClickUp", "composio", "clickup"),
    ConnectorMeta("hubspot", "HubSpot", "composio", "hubspot"),
    ConnectorMeta("mailchimp", "Mailchimp", "composio", "mailchimp"),
    ConnectorMeta("airtable", "Airtable", "composio", "airtable"),
    ConnectorMeta("googlesheets", "Google Sheets", "composio", "googlesheets"),
    ConnectorMeta("googledocs", "Google Docs", "composio", "googledocs"),
    ConnectorMeta("googledrive", "Google Drive", "composio", "googledrive"),
    ConnectorMeta("google_calendar", "Google Calendar", "composio", "googlecalendar"),
    ConnectorMeta("calendly", "Calendly", "composio", "calendly"),
    ConnectorMeta("zoom", "Zoom", "composio", "zoom"),
    ConnectorMeta("dropbox", "Dropbox", "composio", "dropbox"),
    ConnectorMeta("youtube", "YouTube", "composio", "youtube"),
    ConnectorMeta("github", "GitHub", "composio", "github"),
]

CONNECTOR_BY_KEY: dict[str, ConnectorMeta] = {c.key: c for c in CONNECTORS}


# ── Tool catalog ──────────────────────────────────────────────────────────────

CATALOG: list[ToolSpec] = [
    # ── Research & web ───────────────────────────────────────────────────────
    ToolSpec("web_search", "Web search", "Search the web for current information.", "research"),
    ToolSpec("search_and_fetch", "Search & read pages", "Search then read full page content.", "research"),
    ToolSpec("fetch_and_read", "Read a page", "Fetch and extract readable text from a URL.", "research"),
    ToolSpec("news_search", "News search", "Search recent news articles.", "research"),
    ToolSpec("batch_search", "Batch search", "Run several web searches at once.", "research"),
    ToolSpec("research_papers", "Academic papers", "Search academic / research papers.", "research"),
    ToolSpec("patent_search", "Patent search", "Search patents and IP filings.", "research"),
    ToolSpec("youtube_research", "YouTube research", "Mine YouTube for market/product signals.", "research"),
    ToolSpec("youtube_get_transcript", "YouTube transcript", "Get the full transcript of one specific YouTube video by URL.", "research"),
    ToolSpec("tiktok_research", "TikTok research", "Mine TikTok for trends and signals.", "research"),
    ToolSpec("run_research_pipeline", "Deep research pipeline", "Run a structured multi-step research sweep.", "research"),

    # ── Content & docs ───────────────────────────────────────────────────────
    ToolSpec("generate_pdf", "Generate PDF", "Produce a PDF document (report, brief, etc.).", "content"),
    ToolSpec("generate_meta_ad", "Meta ad copy", "Generate Facebook/Instagram ad copy.", "content"),
    ToolSpec("generate_reel_package", "Instagram Reel script", "Generate a Reels script package.", "content"),
    ToolSpec("generate_tiktok_package", "TikTok package", "Generate TikTok video concepts + scripts.", "content"),
    ToolSpec("generate_ad_image", "Ad image", "Generate an advertising image.", "content"),
    ToolSpec("build_email_html", "Email HTML", "Build a formatted HTML email.", "content"),

    # ── Design ───────────────────────────────────────────────────────────────
    ToolSpec("generate_color_palette", "Color palette", "Generate a brand color palette.", "design"),
    ToolSpec("generate_design_spec", "Design spec", "Generate a visual design specification.", "design"),
    ToolSpec("generate_wireframe", "Wireframe", "Generate a page wireframe.", "design"),
    ToolSpec("generate_logo", "Logo", "Generate a logo / wordmark image.", "design"),
    ToolSpec("generate_brand_board", "Brand board", "Generate a brand identity board.", "design"),

    # ── Memory & knowledge ───────────────────────────────────────────────────
    ToolSpec("obsidian_log", "Save to memory", "Persist this run's output to the company vault.", "memory"),
    ToolSpec("obsidian_read", "Read memory", "Read prior notes from the company vault.", "memory"),
    ToolSpec("obsidian_append", "Append to memory", "Append to an existing vault note.", "memory"),
    ToolSpec("company_brain_search", "Search Company Brain", "Search the company knowledge base.", "memory"),
    ToolSpec("company_brain_ask", "Ask Company Brain", "Ask a question against the company knowledge base.", "memory"),

    # ── Dashboard ────────────────────────────────────────────────────────────
    ToolSpec("dashboard_add_element", "Add dashboard tile", "Post a metric/table/list to the founder dashboard.", "dashboard"),

    # ── Leads ────────────────────────────────────────────────────────────────
    ToolSpec("find_leads", "Find leads", "Discover prospects matching an ICP.", "leads", connector="hunter"),
    ToolSpec("hunter_find_email", "Find email", "Find a person's professional email address.", "leads", connector="hunter"),
    ToolSpec("hunter_domain_search", "Domain email search", "Find emails at a company domain.", "leads", connector="hunter"),
    ToolSpec("enrich_lead", "Enrich lead", "Enrich a lead record with more data.", "leads", connector="hunter"),
    ToolSpec("build_outreach_sequence", "Outreach sequence", "Draft a multi-touch outreach sequence.", "leads"),
    ToolSpec("build_crm_contact", "CRM contact record", "Build a CRM-ready contact record.", "leads"),

    # ── Email / send ─────────────────────────────────────────────────────────
    ToolSpec("gmail_send_email", "Send email (Gmail)", "Send an email via the founder's connected Gmail account.", "email", connector="gmail"),
    ToolSpec("composio_outlook_send_email", "Send email (Outlook)", "Send an email via Outlook / Microsoft 365.", "email", connector="outlook"),
    ToolSpec("send_email_campaign", "Email campaign", "Send an email campaign.", "email", connector="sendgrid"),
    ToolSpec("resend_send_email", "Transactional email", "Send a transactional email.", "email", connector="resend"),

    # ── Social posting ───────────────────────────────────────────────────────
    ToolSpec("composio_linkedin_post", "Post to LinkedIn", "Publish a post to LinkedIn.", "social", connector="linkedin"),
    ToolSpec("composio_twitter_post", "Post to X/Twitter", "Publish a post to X (Twitter).", "social", connector="twitter"),
    ToolSpec("composio_reddit_post", "Post to Reddit", "Submit a text post to a subreddit.", "social", connector="reddit"),

    # ── Chat / messaging ─────────────────────────────────────────────────────
    ToolSpec("composio_slack_send_message", "Send Slack message", "Post a message to a Slack channel.", "messaging", connector="slack"),
    ToolSpec("composio_discord_send_message", "Send Discord message", "Send a message to a Discord channel.", "messaging", connector="discord"),
    ToolSpec("composio_telegram_send_message", "Send Telegram message", "Send a Telegram message.", "messaging", connector="telegram"),

    # ── Project & ops ────────────────────────────────────────────────────────
    ToolSpec("composio_notion_create_page", "Create Notion page", "Create a page in Notion.", "ops", connector="notion"),
    ToolSpec("composio_linear_create_issue", "Create Linear issue", "Create an issue in Linear.", "ops", connector="linear"),
    ToolSpec("composio_jira_create_issue", "Create Jira issue", "Create an issue in Jira.", "ops", connector="jira"),
    ToolSpec("composio_trello_create_card", "Create Trello card", "Create a card in Trello.", "ops", connector="trello"),
    ToolSpec("composio_asana_create_task", "Create Asana task", "Create a task in Asana.", "ops", connector="asana"),
    ToolSpec("composio_clickup_create_task", "Create ClickUp task", "Create a task in ClickUp.", "ops", connector="clickup"),
    ToolSpec("composio_calendar_create_event", "Create calendar event", "Create a Google Calendar event.", "ops", connector="google_calendar"),
    ToolSpec("composio_calendly_list_events", "List Calendly events", "List scheduled Calendly events.", "ops", connector="calendly"),
    ToolSpec("composio_zoom_create_meeting", "Create Zoom meeting", "Schedule a Zoom meeting.", "ops", connector="zoom"),

    # ── CRM & marketing ──────────────────────────────────────────────────────
    ToolSpec("composio_hubspot_create_contact", "Create HubSpot contact", "Add a contact to HubSpot.", "crm", connector="hubspot"),
    ToolSpec("composio_mailchimp_add_subscriber", "Add Mailchimp subscriber", "Add a subscriber to a Mailchimp audience.", "crm", connector="mailchimp"),

    # ── Data & files ─────────────────────────────────────────────────────────
    ToolSpec("composio_sheets_append_row", "Append to Google Sheet", "Append a row to a Google Sheet.", "data", connector="googlesheets"),
    ToolSpec("composio_sheets_read", "Read Google Sheet", "Read cells from a Google Sheet.", "data", connector="googlesheets"),
    ToolSpec("composio_airtable_create_record", "Create Airtable record", "Create a record in Airtable.", "data", connector="airtable"),
    ToolSpec("composio_docs_create", "Create Google Doc", "Create a Google Doc.", "data", connector="googledocs"),
    ToolSpec("composio_drive_upload", "Upload to Google Drive", "Create a text file in Google Drive.", "data", connector="googledrive"),
    ToolSpec("composio_dropbox_upload", "Upload to Dropbox", "Upload a text file to Dropbox.", "data", connector="dropbox"),

]

CATALOG_BY_KEY: dict[str, ToolSpec] = {t.key: t for t in CATALOG}
VALID_TOOL_KEYS: frozenset[str] = frozenset(CATALOG_BY_KEY)

ALWAYS_ON_TOOL_KEYS: tuple[str, ...] = ("obsidian_log", "obsidian_read")


def public_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "category": t.category,
            "connector": t.connector,
        }
        for t in CATALOG
    ]


def public_connectors() -> list[dict[str, Any]]:
    return [{"key": c.key, "label": c.label, "kind": c.kind, "composio_slug": c.composio_slug} for c in CONNECTORS]


def connectors_for_tool_keys(tool_keys: list[str]) -> list[str]:
    seen: list[str] = []
    for key in tool_keys:
        spec = CATALOG_BY_KEY.get(key)
        if spec and spec.connector and spec.connector not in seen:
            seen.append(spec.connector)
    return seen


def filter_valid_tool_keys(tool_keys: list[str]) -> tuple[list[str], list[str]]:
    valid = [k for k in tool_keys if k in VALID_TOOL_KEYS]
    unknown = [k for k in tool_keys if k not in VALID_TOOL_KEYS]
    return valid, unknown


def resolve_tools(tool_keys: list[str]) -> tuple[dict[str, Callable], list[str]]:
    """Resolve tool keys to live callables.

    Source order: orchestrator specialist tools, then extended Composio tools,
    then the base composio_tools module. Returns (resolved, unresolved).
    """
    from backend.core.factory import get_orchestrator
    from backend.tools.composio_extended import EXTENDED_TOOLS

    orch = get_orchestrator()
    union: dict[str, Callable] = {}
    for agent in orch.specialists.values():
        for name, fn in agent.tools.items():
            union.setdefault(name, fn)

    # Base composio wrappers (gmail send, linkedin post, notion, linear, calendar…)
    try:
        import backend.tools.composio_tools as _ct
        for name in dir(_ct):
            if name.startswith("composio_"):
                union.setdefault(name, getattr(_ct, name))
    except Exception:
        pass

    # Direct Gmail API (no Composio dependency)
    try:
        from backend.tools.gmail_api import gmail_send_email
        union.setdefault("gmail_send_email", gmail_send_email)
    except Exception:
        pass

    resolved: dict[str, Callable] = {}
    unresolved: list[str] = []
    for key in list(ALWAYS_ON_TOOL_KEYS) + list(tool_keys):
        if key in resolved:
            continue
        fn = union.get(key) or EXTENDED_TOOLS.get(key)
        if fn is not None:
            resolved[key] = fn
        elif key not in ALWAYS_ON_TOOL_KEYS:
            unresolved.append(key)
    return resolved, unresolved

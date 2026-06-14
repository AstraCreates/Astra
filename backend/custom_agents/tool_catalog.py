"""Curated whitelist of tools a founder can attach to a custom agent.

Founders never pick raw callables — they pick safe tool KEYS from this catalog.
Each entry carries display metadata + the connector it needs (if any) so the UI
can show "this agent will need Gmail connected" before the run starts.

Callables are NOT imported here. They're resolved at build time from the live
orchestrator's specialist tools (`resolve_tools`), which guarantees the callable
already exists and is wired exactly the way the built-in agents use it.
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
    connector: str | None = None  # connector key required, or None if always available


# Ordered, grouped catalog. Anything destructive/irreversible (file_llc_live,
# create_product_with_payment_link, raw deploys) is intentionally excluded.
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

    # ── Leads (connector-gated) ──────────────────────────────────────────────
    ToolSpec("find_leads", "Find leads", "Discover prospects matching an ICP.", "leads", connector="hunter"),
    ToolSpec("hunter_find_email", "Find email (Hunter)", "Find a person's email via Hunter.io.", "leads", connector="hunter"),
    ToolSpec("hunter_domain_search", "Domain search (Hunter)", "Find emails at a domain via Hunter.io.", "leads", connector="hunter"),
    ToolSpec("enrich_lead", "Enrich lead", "Enrich a lead record with more data.", "leads", connector="hunter"),
    ToolSpec("build_outreach_sequence", "Outreach sequence", "Draft a multi-touch outreach sequence.", "leads"),
    ToolSpec("build_crm_contact", "CRM contact record", "Build a CRM-ready contact record.", "leads"),

    # ── Outreach / send (connector-gated) ────────────────────────────────────
    ToolSpec("composio_gmail_send", "Send email (Gmail)", "Send an email via the founder's Gmail.", "outreach", connector="gmail"),
    ToolSpec("send_email_campaign", "Email campaign (SendGrid)", "Send an email campaign via SendGrid.", "outreach", connector="sendgrid"),
    ToolSpec("resend_send_email", "Send email (Resend)", "Send an email via Resend.", "outreach", connector="resend"),
    ToolSpec("composio_linkedin_post", "Post to LinkedIn", "Publish a post to LinkedIn.", "outreach", connector="linkedin"),

    # ── Project / ops (connector-gated) ──────────────────────────────────────
    ToolSpec("composio_notion_create_page", "Create Notion page", "Create a page in Notion.", "ops", connector="notion"),
    ToolSpec("composio_linear_create_issue", "Create Linear issue", "Create an issue in Linear.", "ops", connector="linear"),
    ToolSpec("composio_calendar_create_event", "Create calendar event", "Create a Google Calendar event.", "ops", connector="google_calendar"),
]

CATALOG_BY_KEY: dict[str, ToolSpec] = {t.key: t for t in CATALOG}
VALID_TOOL_KEYS: frozenset[str] = frozenset(CATALOG_BY_KEY)

# Tools that are always silently added to every custom agent so it can think,
# remember, and finish cleanly even if the founder forgot to pick them.
ALWAYS_ON_TOOL_KEYS: tuple[str, ...] = ("obsidian_log", "obsidian_read")


def public_catalog() -> list[dict[str, Any]]:
    """Catalog as plain dicts for the API / UI, grouped-friendly."""
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


def connectors_for_tool_keys(tool_keys: list[str]) -> list[str]:
    """Distinct connector keys required by a set of tool keys (order-preserving)."""
    seen: list[str] = []
    for key in tool_keys:
        spec = CATALOG_BY_KEY.get(key)
        if spec and spec.connector and spec.connector not in seen:
            seen.append(spec.connector)
    return seen


def filter_valid_tool_keys(tool_keys: list[str]) -> tuple[list[str], list[str]]:
    """Split requested keys into (valid, unknown)."""
    valid = [k for k in tool_keys if k in VALID_TOOL_KEYS]
    unknown = [k for k in tool_keys if k not in VALID_TOOL_KEYS]
    return valid, unknown


def resolve_tools(tool_keys: list[str]) -> tuple[dict[str, Callable], list[str]]:
    """Resolve tool keys to live callables pulled from the orchestrator's specialists.

    Every catalog tool is already wired into at least one built-in specialist, so
    we union all specialist `.tools` dicts and pick by name. Returns
    (resolved_callables, unresolved_keys).
    """
    from backend.core.factory import get_orchestrator

    orch = get_orchestrator()
    union: dict[str, Callable] = {}
    for agent in orch.specialists.values():
        for name, fn in agent.tools.items():
            union.setdefault(name, fn)

    resolved: dict[str, Callable] = {}
    unresolved: list[str] = []
    # Always include the always-on tools plus the founder's picks.
    for key in list(ALWAYS_ON_TOOL_KEYS) + list(tool_keys):
        if key in resolved:
            continue
        fn = union.get(key)
        if fn is not None:
            resolved[key] = fn
        elif key not in ALWAYS_ON_TOOL_KEYS:
            unresolved.append(key)
    return resolved, unresolved

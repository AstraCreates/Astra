"""Stack readiness checks.

Compares a stack's connector requirements against saved founder/platform
credentials so Astra can show whether a deployable AI department is ready to
operate or needs setup first.
"""
from __future__ import annotations

from typing import Any

from backend.provisioning.credentials_store import load_all_credentials
from backend.stacks.templates import AgentStackTemplate, get_stack_template


_CONNECTOR_SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "github": ("github", "composio"),
    "vercel": ("vercel",),
    "supabase": ("supabase",),
    "clerk": ("clerk",),
    "gmail": ("gmail", "google_workspace", "google", "google_drive", "composio"),
    "google_workspace": ("google_workspace", "google_drive", "google", "composio"),
    "google_drive": ("google_drive", "google_workspace", "google", "composio"),
    "google_sheets": ("google_sheets", "google_workspace", "google_drive", "google", "composio"),
    "google_docs": ("google_docs", "google_workspace", "google_drive", "google", "composio"),
    "google_slides": ("google_slides", "google_workspace", "google_drive", "google", "composio"),
    "google_calendar": ("google_calendar", "google_workspace", "google", "composio"),
    "slack": ("slack", "composio"),
    "discord": ("discord",),
    "notion": ("notion", "composio"),
    "linear": ("linear", "jira", "composio"),
    "crm": ("hubspot", "salesforce", "pipedrive", "crm", "composio"),
    "linkedin": ("linkedin", "composio"),
    "meta_ads": ("meta_ads", "facebook", "composio"),
    "analytics": ("posthog", "google_analytics", "plausible", "analytics"),
    "website_cms": ("vercel", "webflow", "wordpress", "cms"),
    "helpdesk": ("zendesk", "intercom", "helpscout", "helpdesk"),
    "product_tracker": ("linear", "jira", "github", "composio"),
    "figma": ("figma", "composio"),
    "obsidian": ("obsidian",),
    # Ecommerce connectors
    "email_marketing": ("klaviyo", "sendgrid", "resend", "mailchimp"),
    "fulfillment": ("printful", "printify"),
    "digital_sales": ("lemonsqueezy", "gumroad", "stripe"),
    # Local service connectors
    "sms": ("twilio",),
    "pos_payments": ("square", "stripe"),
    "booking": ("square", "acuity", "calendly"),
    "reviews_data": ("yelp",),
}


def _is_connected(founder_credentials: dict[str, Any], connector_key: str) -> tuple[bool, str | None]:
    aliases = _CONNECTOR_SERVICE_ALIASES.get(connector_key, (connector_key,))
    for service in aliases:
        creds = founder_credentials.get(service)
        if isinstance(creds, dict) and creds:
            return True, service
    return False, None


def stack_readiness(founder_id: str, stack_id: str | None = None) -> dict[str, Any]:
    stack: AgentStackTemplate = get_stack_template(stack_id)
    founder_credentials = load_all_credentials(founder_id)
    connectors: list[dict[str, Any]] = []
    missing_required = 0
    connected_required = 0

    for connector in stack.connector_requirements:
        connected, source = _is_connected(founder_credentials, connector.key)
        if connector.required:
            if connected:
                connected_required += 1
            else:
                missing_required += 1
        connectors.append({
            "key": connector.key,
            "label": connector.label,
            "category": connector.category,
            "purpose": connector.purpose,
            "required": connector.required,
            "connected": connected,
            "source": source,
            "status": "connected" if connected else ("missing_required" if connector.required else "optional"),
        })

    required_total = connected_required + missing_required
    readiness_score = 100 if required_total == 0 else round((connected_required / required_total) * 100)
    return {
        "founder_id": founder_id,
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "ready": missing_required == 0,
        "readiness_score": readiness_score,
        "required_total": required_total,
        "connected_required": connected_required,
        "missing_required": missing_required,
        "connectors": connectors,
        "next_actions": [
            f"Connect {connector['label']} for {connector['category']}."
            for connector in connectors
            if connector["status"] == "missing_required"
        ],
    }

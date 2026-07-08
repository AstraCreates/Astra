"""Shared connector field contracts and save-time normalization."""

from __future__ import annotations

from typing import Any


_SERVICE_ALIASES: dict[str, str] = {
    "google": "google_drive",
    "googleworkspace": "google_workspace",
    "google_workspace": "google_workspace",
    "googledrive": "google_drive",
    "googlesheets": "google_sheets",
    "googlecalendar": "google_calendar",
    "googledocs": "google_docs",
    "googleslides": "google_slides",
    "mailchimp_marketing": "mailchimp",
}


CONNECTOR_FIELD_SPECS: dict[str, list[dict[str, Any]]] = {
    "github": [{"key": "token", "label": "GitHub token", "secret": True, "required": True}],
    "vercel": [{"key": "token", "label": "Vercel token", "secret": True, "required": True}],
    "supabase": [
        {"key": "url", "label": "Supabase URL", "secret": False, "required": True},
        {"key": "service_role_key", "label": "Service role key", "secret": True, "required": True},
    ],
    "clerk": [{"key": "secret_key", "label": "Clerk secret key", "secret": True, "required": True}],
    "stripe": [{"key": "access_token", "label": "Stripe access token", "secret": True, "required": True}],
    "resend": [{"key": "api_key", "label": "Resend API key", "secret": True, "required": True}],
    "gmail": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_workspace": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_drive": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_sheets": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_docs": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_slides": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "google_calendar": [{"key": "access_token", "label": "Google OAuth access token", "secret": True, "required": True}],
    "slack": [
        {"key": "bot_token", "label": "Slack bot token", "secret": True, "required": True},
        {"key": "webhook_secret", "label": "Slack signing secret", "secret": True, "required": False},
    ],
    "discord": [
        {"key": "bot_token", "label": "Discord bot token", "secret": True, "required": True},
        {"key": "webhook_secret", "label": "Webhook shared secret", "secret": True, "required": False},
    ],
    "notion": [
        {"key": "token", "label": "Notion integration token", "secret": True, "required": True},
        {"key": "webhook_secret", "label": "Webhook shared secret", "secret": True, "required": False},
    ],
    "linear": [{"key": "api_key", "label": "Linear API key", "secret": True, "required": True}],
    "crm": [{"key": "access_token", "label": "CRM access token", "secret": True, "required": True}],
    "hubspot": [{"key": "access_token", "label": "HubSpot access token", "secret": True, "required": True}],
    "apollo": [{"key": "api_key", "label": "Apollo API key", "secret": True, "required": True}],
    "mailchimp": [{"key": "api_key", "label": "Mailchimp API key", "secret": True, "required": True}],
    "airtable": [{"key": "access_token", "label": "Airtable access token", "secret": True, "required": True}],
    "dropbox": [{"key": "access_token", "label": "Dropbox access token", "secret": True, "required": True}],
    "linkedin": [{"key": "access_token", "label": "LinkedIn access token", "secret": True, "required": True}],
    "meta_ads": [{"key": "access_token", "label": "Meta access token", "secret": True, "required": True}],
    "analytics": [{"key": "api_key", "label": "Analytics API key", "secret": True, "required": True}],
    "website_cms": [{"key": "access_token", "label": "CMS access token", "secret": True, "required": True}],
    "helpdesk": [{"key": "token", "label": "Helpdesk API token", "secret": True, "required": True}],
    "product_tracker": [{"key": "api_key", "label": "Tracker API key", "secret": True, "required": True}],
    "figma": [{"key": "token", "label": "Figma token", "secret": True, "required": True}],
    "obsidian": [{"key": "vault_path", "label": "Vault path", "secret": False, "required": True}],
    "email_marketing": [{"key": "api_key", "label": "Email marketing API key", "secret": True, "required": True}],
    "fulfillment": [{"key": "api_key", "label": "Fulfillment API key", "secret": True, "required": True}],
    "digital_sales": [{"key": "api_key", "label": "Digital sales API key", "secret": True, "required": True}],
    "pos_payments": [{"key": "access_token", "label": "POS access token", "secret": True, "required": True}],
    "sms": [
        {"key": "account_sid", "label": "SMS account SID", "secret": False, "required": True},
        {"key": "auth_token", "label": "SMS auth token", "secret": True, "required": True},
    ],
    "reviews_data": [{"key": "api_key", "label": "Reviews data API key", "secret": True, "required": True}],
    "booking": [{"key": "access_token", "label": "Booking access token", "secret": True, "required": True}],
    "zendesk": [
        {"key": "subdomain", "label": "Zendesk subdomain", "secret": False, "required": True},
        {"key": "email", "label": "Zendesk email", "secret": False, "required": True},
        {"key": "token", "label": "Zendesk API token", "secret": True, "required": True},
    ],
    "confluence": [
        {"key": "base_url", "label": "Confluence base URL", "secret": False, "required": True},
        {"key": "email", "label": "Confluence email", "secret": False, "required": True},
        {"key": "token", "label": "Confluence API token", "secret": True, "required": True},
    ],
    "klaviyo": [{"key": "api_key", "label": "Klaviyo API key", "secret": True, "required": True}],
    "printful": [{"key": "api_key", "label": "Printful API key", "secret": True, "required": True}],
    "lemonsqueezy": [{"key": "api_key", "label": "Lemon Squeezy API key", "secret": True, "required": True}],
    "square": [
        {"key": "access_token", "label": "Square access token", "secret": True, "required": True},
        {"key": "location_id", "label": "Square location ID", "secret": False, "required": False},
    ],
    "yelp": [{"key": "api_key", "label": "Yelp Fusion API key", "secret": True, "required": True}],
    "twilio": [
        {"key": "account_sid", "label": "Twilio account SID", "secret": False, "required": True},
        {"key": "auth_token", "label": "Twilio auth token", "secret": True, "required": True},
    ],
}


def normalize_connector_service(service: str) -> str:
    key = str(service or "").strip().lower().replace("-", "_")
    return _SERVICE_ALIASES.get(key, key)


def connector_field_specs(service: str) -> list[dict[str, Any]]:
    normalized = normalize_connector_service(service)
    return list(CONNECTOR_FIELD_SPECS.get(normalized, [{"key": "token", "label": f"{normalized or 'Connector'} token", "secret": True, "required": True}]))


def prepare_connector_credentials_for_save(
    service: str,
    credentials: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized = normalize_connector_service(service)
    specs = connector_field_specs(normalized)
    existing = existing if isinstance(existing, dict) else {}
    allowed = {str(spec["key"]) for spec in specs}

    cleaned = {
        str(key): str(value).strip()
        for key, value in (credentials or {}).items()
        if isinstance(key, str) and key in allowed and value is not None and str(value).strip()
    }
    merged = {**existing, **cleaned}
    if not cleaned and not merged:
        raise ValueError("At least one supported credential field is required.")
    return normalized, merged

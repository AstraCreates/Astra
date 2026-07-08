"""Registry of integration blocks for the automations canvas.

One NodeType ("integration") covers all of these — the alternative (a
distinct NodeType + hand-written executor branch + hand-written config-panel
JSX per block) doesn't scale past a handful of blocks. Each entry wraps an
EXISTING, already-used tool function (nothing here is a new API integration —
see backend/tools/composio_tools.py, stripe_tools.py, klaviyo_tools.py, etc,
several of which specialist agents already call directly via
backend/core/factory.py). The registry just gives the canvas a uniform way
to list, describe, and invoke them.

Credential scope, stated honestly per block (shown in the UI description):
  - "your connected X account" — genuinely per-founder (Composio OAuth
    entity_id=founder_id, or backend/provisioning/credentials_store.py).
  - "Astra's configured X account" — server-wide credential (backend/config.py
    settings.*). This is a pre-existing characteristic of these six tool
    files (klaviyo/twilio/square/yelp/printful/lemonsqueezy), not something
    introduced here — specialist agents already call them the same way.
    Flagged clearly rather than implied to be per-founder when it isn't.
"""
from __future__ import annotations

from typing import Any, Callable

ParamSpec = dict[str, str]  # {key, label, type: "text"|"textarea"|"number", placeholder?}


class IntegrationBlock:
    def __init__(self, key: str, label: str, category: str, scope: str, params: list[ParamSpec], run: Callable[[dict, str], dict]):
        self.key = key
        self.label = label
        self.category = category
        self.scope = scope  # "founder" | "astra"
        self.params = params
        self.run = run


def _p(key: str, label: str, type_: str = "text", placeholder: str = "") -> ParamSpec:
    return {"key": key, "label": label, "type": type_, "placeholder": placeholder}


def _split_lines(value: str) -> list[str]:
    return [v.strip() for v in (value or "").replace(",", "\n").splitlines() if v.strip()]


# ── Slack ────────────────────────────────────────────────────────────────────

def _run_slack_webhook(params: dict, founder_id: str) -> dict:
    import asyncio
    from backend.tools.automation_graph import _execute_slack_node
    return asyncio.run(_execute_slack_node({}, params))


def _run_slack_bot(params: dict, founder_id: str) -> dict:
    import asyncio
    from backend.tools.automation_graph import _execute_slack_bot_node
    return asyncio.run(_execute_slack_bot_node(params, founder_id))


# ── Email / Gmail ────────────────────────────────────────────────────────────

def _run_sendgrid_send(params: dict, founder_id: str) -> dict:
    import asyncio
    from backend.tools.automation_graph import _execute_email_node
    return asyncio.run(_execute_email_node({}, params, founder_id))


def _run_gmail_send(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_gmail_send
    return composio_gmail_send(founder_id, params.get("to", ""), params.get("subject", ""), params.get("body", ""))


def _run_gmail_list(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import gmail_list_messages
    max_results = int(params.get("max_results") or 20)
    return gmail_list_messages(founder_id, params.get("query", ""), max_results)


def _run_gmail_get(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import gmail_get_message
    return gmail_get_message(founder_id, params.get("message_id", ""))


# ── GitHub / Linear / Notion ─────────────────────────────────────────────────

def _run_github_issue(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_github_create_issue
    return composio_github_create_issue(founder_id, params.get("repo", ""), params.get("title", ""), params.get("body", ""), params.get("owner", ""))


def _run_github_pr(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_github_create_pr
    return composio_github_create_pr(founder_id, params.get("repo", ""), params.get("title", ""), params.get("body", ""), params.get("head", ""), params.get("base") or "main", params.get("owner", ""))


def _run_linear_issue(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_linear_create_issue
    return composio_linear_create_issue(founder_id, params.get("title", ""), params.get("description", ""))


def _run_notion_page(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_notion_create_page
    result = composio_notion_create_page(founder_id, params.get("title", ""), params.get("parent_id", ""))
    if params.get("body") and not result.get("error"):
        result["notes"] = params["body"]
    return result


# ── LinkedIn / Calendar ──────────────────────────────────────────────────────

def _run_linkedin_post(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_linkedin_post
    return composio_linkedin_post(founder_id, params.get("text", ""))


def _run_calendar_event(params: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_calendar_create_event
    return composio_calendar_create_event(
        founder_id, params.get("summary", ""), params.get("start_time", ""),
        params.get("end_time", ""), None, params.get("description", ""),
        params.get("timezone") or "UTC",
    )


def _run_google_calendar_event(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_calendar_create_event
    return google_calendar_create_event(
        founder_id,
        params.get("summary", ""),
        params.get("start_time", ""),
        params.get("end_time", ""),
        params.get("description", ""),
        params.get("timezone") or "UTC",
    )


def _run_google_calendar_list(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_calendar_list_events
    try:
        max_results = int(float(params.get("max_results") or 10))
    except (TypeError, ValueError):
        max_results = 10
    return google_calendar_list_events(founder_id, params.get("time_min", ""), params.get("time_max", ""), max_results)


def _run_google_docs_create(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_docs_create_document
    return google_docs_create_document(founder_id, params.get("title", ""), params.get("text", ""))


def _run_google_docs_append(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_docs_append_text
    return google_docs_append_text(founder_id, params.get("document_id", ""), params.get("text", ""))


def _run_google_docs_read(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_docs_read_document
    return google_docs_read_document(founder_id, params.get("document_id", ""))


def _run_google_sheets_create(params: dict, founder_id: str) -> dict:
    import json as _json
    from backend.tools.google_workspace_tools import google_sheets_create_spreadsheet
    try:
        headers = _json.loads(params.get("headers") or "[]")
        rows = _json.loads(params.get("rows") or "[]")
    except _json.JSONDecodeError:
        return {"error": "headers and rows must be valid JSON arrays"}
    return google_sheets_create_spreadsheet(founder_id, params.get("title", ""), params.get("sheet_name", "Sheet1"), headers, rows)


def _run_google_sheets_append(params: dict, founder_id: str) -> dict:
    import json as _json
    from backend.tools.google_workspace_tools import google_sheets_append_row
    try:
        values = _json.loads(params.get("values") or "[]")
    except _json.JSONDecodeError:
        return {"error": "values must be a valid JSON array"}
    return google_sheets_append_row(founder_id, params.get("spreadsheet_id", ""), params.get("sheet_name", ""), values)


def _run_google_sheets_read(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_sheets_read
    return google_sheets_read(founder_id, params.get("spreadsheet_id", ""), params.get("range_a1", "A1:Z100"))


def _run_google_sheets_update(params: dict, founder_id: str) -> dict:
    import json as _json
    from backend.tools.google_workspace_tools import google_sheets_update_range
    try:
        values = _json.loads(params.get("values") or "[]")
    except _json.JSONDecodeError:
        return {"error": "values must be a valid JSON 2D array"}
    return google_sheets_update_range(founder_id, params.get("spreadsheet_id", ""), params.get("range_a1", ""), values)


def _run_google_slides_create(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_slides_create_presentation
    return google_slides_create_presentation(founder_id, params.get("title", ""))


def _run_google_slides_add(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_slides_add_slide
    return google_slides_add_slide(founder_id, params.get("presentation_id", ""), params.get("title", ""), params.get("body", ""))


def _run_google_drive_list(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_drive_list_files
    try:
        page_size = int(float(params.get("page_size") or 20))
    except (TypeError, ValueError):
        page_size = 20
    return google_drive_list_files(founder_id, params.get("query", ""), page_size)


def _run_google_drive_read(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_drive_read_file
    return google_drive_read_file(founder_id, params.get("file_id", ""))


def _run_google_drive_create(params: dict, founder_id: str) -> dict:
    from backend.tools.google_workspace_tools import google_drive_create_text_file
    return google_drive_create_text_file(founder_id, params.get("name", ""), params.get("content", ""), params.get("mime_type", "text/plain"))


# ── Stripe ───────────────────────────────────────────────────────────────────

def _stripe_access_token(founder_id: str) -> str:
    from backend.provisioning.credentials_store import load_credentials
    creds = load_credentials(founder_id, "stripe") or {}
    return creds.get("access_token") or creds.get("secret_key") or ""


def _run_stripe_payment_link(params: dict, founder_id: str) -> dict:
    from backend.tools.stripe_tools import create_product_with_payment_link
    try:
        amount = int(float(params.get("amount") or 0))
    except (TypeError, ValueError):
        return {"error": "amount must be a number"}
    return create_product_with_payment_link(
        name=params.get("title", ""), description=params.get("description", ""), amount=amount,
        founder_id=founder_id, currency=params.get("currency") or "usd", interval=params.get("interval") or "one_time",
    )


def _run_stripe_list_products(params: dict, founder_id: str) -> dict:
    from backend.tools.stripe_tools import list_stripe_products
    token = _stripe_access_token(founder_id)
    if not token:
        return {"error": "Stripe is not connected — connect it on the Integrations page first."}
    return list_stripe_products(token)


# ── Twilio (Astra-configured account) ───────────────────────────────────────

def _run_twilio_sms(params: dict, founder_id: str) -> dict:
    from backend.tools.twilio_tools import twilio_send_sms
    return twilio_send_sms(params.get("to", ""), params.get("body", ""), params.get("from_number", ""))


def _run_twilio_bulk_sms(params: dict, founder_id: str) -> dict:
    from backend.tools.twilio_tools import twilio_send_bulk_sms
    return twilio_send_bulk_sms(_split_lines(params.get("to_list", "")), params.get("body", ""), params.get("from_number", ""))


def _run_twilio_usage(params: dict, founder_id: str) -> dict:
    from backend.tools.twilio_tools import twilio_get_usage
    return twilio_get_usage()


def _run_twilio_create_messaging_service(params: dict, founder_id: str) -> dict:
    from backend.tools.twilio_tools import twilio_create_messaging_service
    return twilio_create_messaging_service(params.get("name", ""))


# ── Klaviyo (Astra-configured account) ──────────────────────────────────────

def _run_klaviyo_create_list(params: dict, founder_id: str) -> dict:
    from backend.tools.klaviyo_tools import klaviyo_create_list
    return klaviyo_create_list(params.get("name", ""))


def _run_klaviyo_add_to_list(params: dict, founder_id: str) -> dict:
    from backend.tools.klaviyo_tools import klaviyo_add_to_list
    return klaviyo_add_to_list(params.get("list_id", ""), _split_lines(params.get("emails", "")))


def _run_klaviyo_create_campaign(params: dict, founder_id: str) -> dict:
    from backend.tools.klaviyo_tools import klaviyo_create_campaign
    return klaviyo_create_campaign(params.get("name", ""), params.get("subject", ""), params.get("body_html", ""), params.get("list_id", ""))


def _run_klaviyo_metrics(params: dict, founder_id: str) -> dict:
    from backend.tools.klaviyo_tools import klaviyo_get_metrics
    return klaviyo_get_metrics()


# ── Square (Astra-configured account) ───────────────────────────────────────

def _run_square_list_services(params: dict, founder_id: str) -> dict:
    from backend.tools.square_tools import square_list_services
    return square_list_services()


def _run_square_create_service(params: dict, founder_id: str) -> dict:
    from backend.tools.square_tools import square_create_service
    try:
        price_cents = int(float(params.get("price_cents") or 0))
        duration = int(float(params.get("duration_minutes") or 30))
    except (TypeError, ValueError):
        return {"error": "price_cents and duration_minutes must be numbers"}
    return square_create_service(params.get("name", ""), price_cents, duration, params.get("description", ""))


def _run_square_create_booking(params: dict, founder_id: str) -> dict:
    from backend.tools.square_tools import square_create_booking
    return square_create_booking(params.get("service_variation_id", ""), params.get("start_at", ""), params.get("customer_note", ""))


def _run_square_list_bookings(params: dict, founder_id: str) -> dict:
    from backend.tools.square_tools import square_list_bookings
    return square_list_bookings(params.get("start_date", ""), params.get("end_date", ""))


def _run_square_revenue(params: dict, founder_id: str) -> dict:
    from backend.tools.square_tools import square_get_revenue
    return square_get_revenue(params.get("start_date", ""), params.get("end_date", ""))


# ── Yelp (Astra-configured account) ─────────────────────────────────────────

def _run_yelp_search(params: dict, founder_id: str) -> dict:
    from backend.tools.yelp_tools import yelp_search_businesses
    try:
        limit = int(float(params.get("limit") or 10))
    except (TypeError, ValueError):
        limit = 10
    return yelp_search_businesses(params.get("term", ""), params.get("location", ""), limit)


def _run_yelp_business(params: dict, founder_id: str) -> dict:
    from backend.tools.yelp_tools import yelp_get_business
    return yelp_get_business(params.get("business_id", ""))


def _run_yelp_reviews(params: dict, founder_id: str) -> dict:
    from backend.tools.yelp_tools import yelp_get_reviews
    return yelp_get_reviews(params.get("business_id", ""))


def _run_yelp_categories(params: dict, founder_id: str) -> dict:
    from backend.tools.yelp_tools import yelp_search_categories
    try:
        limit = int(float(params.get("limit") or 20))
    except (TypeError, ValueError):
        limit = 20
    return yelp_search_categories(params.get("location", ""), params.get("category", ""), limit)


# ── Printful (Astra-configured account) ─────────────────────────────────────

def _run_printful_products(params: dict, founder_id: str) -> dict:
    from backend.tools.printful_tools import printful_get_products
    try:
        category_id = int(float(params.get("category_id") or 0))
    except (TypeError, ValueError):
        category_id = 0
    return printful_get_products(category_id)


def _run_printful_create_product(params: dict, founder_id: str) -> dict:
    import json as _json
    from backend.tools.printful_tools import printful_create_store_product
    try:
        product_id = int(float(params.get("product_id") or 0))
        variants = _json.loads(params.get("variants") or "[]")
    except (TypeError, ValueError, _json.JSONDecodeError):
        return {"error": "product_id must be a number and variants must be valid JSON, e.g. [{\"variant_id\":1,\"retail_price\":\"19.99\"}]"}
    return printful_create_store_product(product_id, params.get("name", ""), variants)


def _run_printful_create_order(params: dict, founder_id: str) -> dict:
    import json as _json
    from backend.tools.printful_tools import printful_create_order
    try:
        items = _json.loads(params.get("items") or "[]")
        recipient = _json.loads(params.get("recipient") or "{}")
    except _json.JSONDecodeError:
        return {"error": "items and recipient must be valid JSON"}
    return printful_create_order(items, recipient)


def _run_printful_orders(params: dict, founder_id: str) -> dict:
    from backend.tools.printful_tools import printful_get_orders
    return printful_get_orders()


# ── Lemon Squeezy (Astra-configured account) ────────────────────────────────

def _run_ls_create_product(params: dict, founder_id: str) -> dict:
    from backend.tools.lemonsqueezy_tools import ls_create_product
    try:
        price_cents = int(float(params.get("price_cents") or 0))
    except (TypeError, ValueError):
        return {"error": "price_cents must be a number"}
    return ls_create_product(params.get("name", ""), params.get("description", ""), price_cents, params.get("store_id", ""))


def _run_ls_get_sales(params: dict, founder_id: str) -> dict:
    from backend.tools.lemonsqueezy_tools import ls_get_sales
    try:
        limit = int(float(params.get("limit") or 50))
    except (TypeError, ValueError):
        limit = 50
    return ls_get_sales(limit)


def _run_ls_create_discount(params: dict, founder_id: str) -> dict:
    from backend.tools.lemonsqueezy_tools import ls_create_discount
    try:
        percent_off = int(float(params.get("percent_off") or 0))
    except (TypeError, ValueError):
        return {"error": "percent_off must be a number"}
    return ls_create_discount(percent_off, params.get("code", ""), params.get("store_id", ""))


INTEGRATION_BLOCKS: dict[str, IntegrationBlock] = {}


def _register(key: str, label: str, category: str, scope: str, params: list[ParamSpec], run: Callable[[dict, str], dict]) -> None:
    INTEGRATION_BLOCKS[key] = IntegrationBlock(key, label, category, scope, params, run)


_register("slack_webhook_post", "Post via webhook", "Slack", "founder",
           [_p("webhook_url", "Webhook URL", placeholder="https://hooks.slack.com/services/..."), _p("message", "Message", "textarea")],
           _run_slack_webhook)
_register("slack_bot_post", "Post via bot token", "Slack", "founder",
           [_p("channel", "Channel", placeholder="#general"), _p("message", "Message", "textarea")],
           _run_slack_bot)

_register("sendgrid_send", "Send email (SendGrid)", "Email", "founder",
           [_p("to", "To"), _p("subject", "Subject"), _p("body", "Body", "textarea"), _p("from", "From (optional)")],
           _run_sendgrid_send)
_register("gmail_send", "Send email (Gmail)", "Gmail", "founder",
           [_p("to", "To"), _p("subject", "Subject"), _p("body", "Body", "textarea")],
           _run_gmail_send)
_register("gmail_list_messages", "List messages", "Gmail", "founder",
           [_p("query", "Search query", placeholder="in:inbox is:unread"), _p("max_results", "Max results", "number", "20")],
           _run_gmail_list)
_register("gmail_get_message", "Get message", "Gmail", "founder",
           [_p("message_id", "Message ID (from List messages)")],
           _run_gmail_get)

_register("github_create_issue", "Create issue", "GitHub", "founder",
           [_p("repo", "Repository"), _p("title", "Title"), _p("body", "Body", "textarea"), _p("owner", "Owner (optional)")],
           _run_github_issue)
_register("github_create_pr", "Create pull request", "GitHub", "founder",
           [_p("repo", "Repository"), _p("title", "Title"), _p("body", "Body", "textarea"), _p("head", "Head branch"), _p("base", "Base branch", placeholder="main"), _p("owner", "Owner (optional)")],
           _run_github_pr)

_register("linear_create_issue", "Create issue", "Linear", "founder",
           [_p("title", "Title"), _p("description", "Description", "textarea")],
           _run_linear_issue)

_register("notion_create_page", "Create page", "Notion", "founder",
           [_p("title", "Title"), _p("parent_id", "Parent page ID (optional)"), _p("body", "Notes", "textarea")],
           _run_notion_page)

_register("linkedin_post", "Create post", "LinkedIn", "founder",
           [_p("text", "Post text", "textarea")],
           _run_linkedin_post)

_register("calendar_create_event", "Create event", "Calendar", "founder",
           [_p("summary", "Title"), _p("start_time", "Start (ISO 8601)", placeholder="2026-01-01T14:00:00Z"),
            _p("end_time", "End (ISO 8601)", placeholder="2026-01-01T15:00:00Z"), _p("description", "Description", "textarea"),
            _p("timezone", "Timezone", placeholder="UTC")],
           _run_calendar_event)
_register("google_calendar_create_event", "Create Google event", "Google Calendar", "founder",
           [_p("summary", "Title"), _p("start_time", "Start (ISO 8601)", placeholder="2026-01-01T14:00:00Z"),
            _p("end_time", "End (ISO 8601)", placeholder="2026-01-01T15:00:00Z"), _p("description", "Description", "textarea"),
            _p("timezone", "Timezone", placeholder="UTC")],
           _run_google_calendar_event)
_register("google_calendar_list_events", "List Google events", "Google Calendar", "founder",
           [_p("time_min", "Time min (ISO 8601, optional)"), _p("time_max", "Time max (ISO 8601, optional)"), _p("max_results", "Max results", "number", "10")],
           _run_google_calendar_list)
_register("google_docs_create", "Create Google Doc", "Google Docs", "founder",
           [_p("title", "Title"), _p("text", "Initial text", "textarea")], _run_google_docs_create)
_register("google_docs_append", "Append Google Doc", "Google Docs", "founder",
           [_p("document_id", "Document ID"), _p("text", "Text", "textarea")], _run_google_docs_append)
_register("google_docs_read", "Read Google Doc", "Google Docs", "founder",
           [_p("document_id", "Document ID")], _run_google_docs_read)
_register("google_sheets_create", "Create Google Sheet", "Google Sheets", "founder",
           [_p("title", "Title"), _p("sheet_name", "Sheet name"), _p("headers", "Headers (JSON array)", "textarea", '["Name","Email"]'),
            _p("rows", "Rows (JSON 2D array)", "textarea", '[["Ada","ada@example.com"]]')], _run_google_sheets_create)
_register("google_sheets_append", "Append Google Sheet row", "Google Sheets", "founder",
           [_p("spreadsheet_id", "Spreadsheet ID"), _p("sheet_name", "Sheet name"), _p("values", "Values (JSON array)", "textarea", '["Ada","ada@example.com"]')],
           _run_google_sheets_append)
_register("google_sheets_read", "Read Google Sheet", "Google Sheets", "founder",
           [_p("spreadsheet_id", "Spreadsheet ID"), _p("range_a1", "Range A1", placeholder="Sheet1!A1:Z100")], _run_google_sheets_read)
_register("google_sheets_update", "Update Google Sheet range", "Google Sheets", "founder",
           [_p("spreadsheet_id", "Spreadsheet ID"), _p("range_a1", "Range A1"), _p("values", "Values (JSON 2D array)", "textarea", '[["Done"]]')],
           _run_google_sheets_update)
_register("google_slides_create", "Create Google Slides", "Google Slides", "founder",
           [_p("title", "Title")], _run_google_slides_create)
_register("google_slides_add_slide", "Add Google Slide", "Google Slides", "founder",
           [_p("presentation_id", "Presentation ID"), _p("title", "Slide title"), _p("body", "Slide body", "textarea")], _run_google_slides_add)
_register("google_drive_list_files", "List Google Drive files", "Google Drive", "founder",
           [_p("query", "Drive query", placeholder="name contains 'proposal'"), _p("page_size", "Page size", "number", "20")], _run_google_drive_list)
_register("google_drive_read_file", "Read Google Drive file", "Google Drive", "founder",
           [_p("file_id", "File ID")], _run_google_drive_read)
_register("google_drive_create_file", "Create Google Drive text file", "Google Drive", "founder",
           [_p("name", "File name"), _p("content", "Content", "textarea"), _p("mime_type", "MIME type", placeholder="text/plain")], _run_google_drive_create)

_register("stripe_payment_link", "Create payment link", "Stripe", "founder",
           [_p("title", "Product name"), _p("description", "Description", "textarea"), _p("amount", "Amount (cents)", "number"),
            _p("currency", "Currency", placeholder="usd"), _p("interval", "Interval", placeholder="one_time")],
           _run_stripe_payment_link)
_register("stripe_list_products", "List products", "Stripe", "founder", [], _run_stripe_list_products)

_register("twilio_send_sms", "Send SMS", "Twilio", "astra",
           [_p("to", "To (E.164)", placeholder="+15551234567"), _p("body", "Message", "textarea"), _p("from_number", "From number (optional)")],
           _run_twilio_sms)
_register("twilio_send_bulk_sms", "Send bulk SMS", "Twilio", "astra",
           [_p("to_list", "To numbers (one per line)", "textarea"), _p("body", "Message", "textarea"), _p("from_number", "From number (optional)")],
           _run_twilio_bulk_sms)
_register("twilio_usage", "Get usage", "Twilio", "astra", [], _run_twilio_usage)
_register("twilio_create_messaging_service", "Create messaging service", "Twilio", "astra",
           [_p("name", "Service name")], _run_twilio_create_messaging_service)

_register("klaviyo_create_list", "Create list", "Klaviyo", "astra", [_p("name", "List name")], _run_klaviyo_create_list)
_register("klaviyo_add_to_list", "Add contacts to list", "Klaviyo", "astra",
           [_p("list_id", "List ID"), _p("emails", "Emails (one per line)", "textarea")], _run_klaviyo_add_to_list)
_register("klaviyo_create_campaign", "Create campaign", "Klaviyo", "astra",
           [_p("name", "Campaign name"), _p("subject", "Subject"), _p("body_html", "Body (HTML)", "textarea"), _p("list_id", "List ID")],
           _run_klaviyo_create_campaign)
_register("klaviyo_metrics", "Get metrics", "Klaviyo", "astra", [], _run_klaviyo_metrics)

_register("square_list_services", "List services", "Square", "astra", [], _run_square_list_services)
_register("square_create_service", "Create service", "Square", "astra",
           [_p("name", "Service name"), _p("price_cents", "Price (cents)", "number"), _p("duration_minutes", "Duration (min)", "number"), _p("description", "Description", "textarea")],
           _run_square_create_service)
_register("square_create_booking", "Create booking", "Square", "astra",
           [_p("service_variation_id", "Service variation ID"), _p("start_at", "Start (ISO 8601)"), _p("customer_note", "Note", "textarea")],
           _run_square_create_booking)
_register("square_list_bookings", "List bookings", "Square", "astra",
           [_p("start_date", "Start date (optional)"), _p("end_date", "End date (optional)")], _run_square_list_bookings)
_register("square_revenue", "Get revenue", "Square", "astra",
           [_p("start_date", "Start date (optional)"), _p("end_date", "End date (optional)")], _run_square_revenue)

_register("yelp_search", "Search businesses", "Yelp", "astra",
           [_p("term", "Search term"), _p("location", "Location"), _p("limit", "Limit", "number", "10")], _run_yelp_search)
_register("yelp_business", "Get business", "Yelp", "astra", [_p("business_id", "Business ID")], _run_yelp_business)
_register("yelp_reviews", "Get reviews", "Yelp", "astra", [_p("business_id", "Business ID")], _run_yelp_reviews)
_register("yelp_categories", "Search by category", "Yelp", "astra",
           [_p("location", "Location"), _p("category", "Category"), _p("limit", "Limit", "number", "20")], _run_yelp_categories)

_register("printful_products", "List products", "Printful", "astra", [_p("category_id", "Category ID (optional)", "number")], _run_printful_products)
_register("printful_create_product", "Create store product", "Printful", "astra",
           [_p("product_id", "Catalog product ID", "number"), _p("name", "Product name"),
            _p("variants", "Variants (JSON)", "textarea", '[{"variant_id":1,"retail_price":"19.99"}]')],
           _run_printful_create_product)
_register("printful_orders", "List orders", "Printful", "astra", [], _run_printful_orders)
_register("printful_create_order", "Create order", "Printful", "astra",
           [_p("items", "Items (JSON)", "textarea", '[{"variant_id":1,"quantity":1}]'),
            _p("recipient", "Recipient (JSON)", "textarea", '{"name":"...","address1":"...","city":"...","country_code":"US"}')],
           _run_printful_create_order)

_register("lemonsqueezy_create_product", "Create product", "Lemon Squeezy", "astra",
           [_p("name", "Product name"), _p("description", "Description", "textarea"), _p("price_cents", "Price (cents)", "number"), _p("store_id", "Store ID (optional)")],
           _run_ls_create_product)
_register("lemonsqueezy_sales", "Get sales", "Lemon Squeezy", "astra", [_p("limit", "Limit", "number", "50")], _run_ls_get_sales)
_register("lemonsqueezy_create_discount", "Create discount", "Lemon Squeezy", "astra",
           [_p("percent_off", "Percent off", "number"), _p("code", "Discount code"), _p("store_id", "Store ID (optional)")],
           _run_ls_create_discount)


def catalog() -> list[dict]:
    return [
        {"key": b.key, "label": b.label, "category": b.category, "scope": b.scope, "params": b.params}
        for b in INTEGRATION_BLOCKS.values()
    ]

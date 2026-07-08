"""Extended Composio-backed tools for custom agents.

Every tool here routes through `composio_tools._run(action, params, founder_id)`,
which executes a Composio action against the founder's connected account. That
means adding a new third-party capability is just a thin wrapper — Composio owns
the OAuth, tokens, and API calls per app.

These are intentionally NOT wired into the built-in specialists or shown on the
Integrations page. They surface only when a custom agent picks a tool that needs
them (see custom_agents/tool_catalog.py + connector_readiness).

NOTE: Composio occasionally renames actions. If a specific wrapper's action slug
is stale it returns an {"error": ...} (the agent surfaces it, no crash), and the
generic `composio_run_action` can reach any action by name as a fallback.
"""
from __future__ import annotations

from typing import Any

from backend.tools.composio_tools import _run
from backend.tools.google_workspace_tools import (
    google_calendar_create_event,
    google_calendar_list_events,
    google_docs_append_text,
    google_docs_create_document,
    google_docs_read_document,
    google_drive_create_text_file,
    google_drive_list_files,
    google_drive_read_file,
    google_sheets_update_range,
    google_sheets_append_row,
    google_sheets_create_spreadsheet,
    google_sheets_read,
    google_slides_add_slide,
    google_slides_create_presentation,
)


# ── Generic escape hatch ──────────────────────────────────────────────────────

def composio_run_action(founder_id: str, action: str, params: dict | None = None) -> dict:
    """Run ANY Composio action by name. action=Composio action slug (e.g. 'SLACK_SENDS_A_MESSAGE'), params=dict of its arguments."""
    return _run(action, params or {}, founder_id)


# ── Slack ─────────────────────────────────────────────────────────────────────

def composio_slack_send_message(founder_id: str, channel: str, text: str) -> dict:
    """Post a message to a Slack channel. Args: channel (name or id), text."""
    return _run("SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL", {"channel": channel, "text": text}, founder_id)


# ── Discord ───────────────────────────────────────────────────────────────────

def composio_discord_send_message(founder_id: str, channel_id: str, content: str) -> dict:
    """Send a message to a Discord channel. Args: channel_id, content."""
    return _run("DISCORD_SEND_MESSAGE", {"channel_id": channel_id, "content": content}, founder_id)


# ── Twitter / X ───────────────────────────────────────────────────────────────

def composio_twitter_post(founder_id: str, text: str) -> dict:
    """Publish a post (tweet) to X/Twitter. Args: text."""
    return _run("TWITTER_CREATION_OF_A_POST", {"text": text}, founder_id)


# ── Reddit ────────────────────────────────────────────────────────────────────

def composio_reddit_post(founder_id: str, subreddit: str, title: str, text: str = "") -> dict:
    """Submit a text post to a subreddit. Args: subreddit (no r/ prefix), title, text."""
    return _run("REDDIT_CREATE_REDDIT_POST", {"subreddit": subreddit, "title": title, "text": text}, founder_id)


# ── Telegram ──────────────────────────────────────────────────────────────────

def composio_telegram_send_message(founder_id: str, chat_id: str, text: str) -> dict:
    """Send a Telegram message. Args: chat_id, text."""
    return _run("TELEGRAM_SEND_MESSAGE", {"chat_id": chat_id, "text": text}, founder_id)


# ── Gmail (read) ──────────────────────────────────────────────────────────────

def composio_gmail_fetch(founder_id: str, query: str = "", max_results: int = 10) -> dict:
    """Fetch recent emails from the founder's Gmail. Args: query (Gmail search), max_results."""
    return _run("GMAIL_FETCH_EMAILS", {"query": query, "max_results": max_results}, founder_id)


# ── Google Sheets ─────────────────────────────────────────────────────────────

def composio_sheets_append_row(founder_id: str, spreadsheet_id: str, sheet_name: str, values: list) -> dict:
    """Append a row to a Google Sheet. Args: spreadsheet_id, sheet_name, values (list of cell values)."""
    return _run(
        "GOOGLESHEETS_BATCH_UPDATE",
        {"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name, "values": [values]},
        founder_id,
    )


def composio_sheets_read(founder_id: str, spreadsheet_id: str, range: str = "A1:Z100") -> dict:
    """Read cells from a Google Sheet. Args: spreadsheet_id, range (A1 notation)."""
    return _run("GOOGLESHEETS_BATCH_GET", {"spreadsheet_id": spreadsheet_id, "ranges": [range]}, founder_id)


# ── Google Docs ───────────────────────────────────────────────────────────────

def composio_docs_create(founder_id: str, title: str, text: str = "") -> dict:
    """Create a Google Doc. Args: title, text (initial body)."""
    return _run("GOOGLEDOCS_CREATE_DOCUMENT", {"title": title, "text": text}, founder_id)


# ── Google Drive ──────────────────────────────────────────────────────────────

def composio_drive_upload(founder_id: str, file_name: str, content: str) -> dict:
    """Create a text file in Google Drive. Args: file_name, content."""
    return _run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {"file_name": file_name, "text_content": content}, founder_id)


# ── Airtable ──────────────────────────────────────────────────────────────────

def composio_airtable_create_record(founder_id: str, base_id: str, table_name: str, fields: dict) -> dict:
    """Create a record in Airtable. Args: base_id, table_name, fields (dict of column->value)."""
    return _run("AIRTABLE_CREATE_RECORD", {"base_id": base_id, "table_name": table_name, "fields": fields}, founder_id)


# ── Trello ────────────────────────────────────────────────────────────────────

def composio_trello_create_card(founder_id: str, list_id: str, name: str, desc: str = "") -> dict:
    """Create a Trello card. Args: list_id, name, desc."""
    return _run("TRELLO_CREATE_CARD", {"idList": list_id, "name": name, "desc": desc}, founder_id)


# ── Asana ─────────────────────────────────────────────────────────────────────

def composio_asana_create_task(founder_id: str, project_id: str, name: str, notes: str = "") -> dict:
    """Create an Asana task. Args: project_id, name, notes."""
    return _run("ASANA_CREATE_TASK", {"project": project_id, "name": name, "notes": notes}, founder_id)


# ── ClickUp ───────────────────────────────────────────────────────────────────

def composio_clickup_create_task(founder_id: str, list_id: str, name: str, description: str = "") -> dict:
    """Create a ClickUp task. Args: list_id, name, description."""
    return _run("CLICKUP_CREATE_TASK", {"list_id": list_id, "name": name, "description": description}, founder_id)


# ── Jira ──────────────────────────────────────────────────────────────────────

def composio_jira_create_issue(founder_id: str, project_key: str, summary: str, description: str = "") -> dict:
    """Create a Jira issue. Args: project_key, summary, description."""
    return _run(
        "JIRA_CREATE_ISSUE",
        {"project_key": project_key, "summary": summary, "description": description},
        founder_id,
    )


# ── HubSpot ───────────────────────────────────────────────────────────────────

def composio_hubspot_create_contact(founder_id: str, email: str, firstname: str = "", lastname: str = "") -> dict:
    """Create a HubSpot contact. Args: email, firstname, lastname."""
    return _run(
        "HUBSPOT_CREATE_CONTACT",
        {"email": email, "firstname": firstname, "lastname": lastname},
        founder_id,
    )


# ── Mailchimp ─────────────────────────────────────────────────────────────────

def composio_mailchimp_add_subscriber(founder_id: str, list_id: str, email: str) -> dict:
    """Add a subscriber to a Mailchimp audience. Args: list_id, email."""
    return _run("MAILCHIMP_ADD_MEMBER_TO_LIST", {"list_id": list_id, "email_address": email}, founder_id)


# ── Calendly ──────────────────────────────────────────────────────────────────

def composio_calendly_list_events(founder_id: str) -> dict:
    """List the founder's scheduled Calendly events."""
    return _run("CALENDLY_LIST_EVENTS", {}, founder_id)


# ── Zoom ──────────────────────────────────────────────────────────────────────

def composio_zoom_create_meeting(founder_id: str, topic: str, start_time: str = "") -> dict:
    """Create a Zoom meeting. Args: topic, start_time (ISO-8601, optional)."""
    return _run("ZOOM_CREATE_MEETING", {"topic": topic, "start_time": start_time}, founder_id)


# ── Dropbox ───────────────────────────────────────────────────────────────────

def composio_dropbox_upload(founder_id: str, path: str, content: str) -> dict:
    """Upload a text file to Dropbox. Args: path (e.g. /reports/x.txt), content."""
    return _run("DROPBOX_UPLOAD_FILE", {"path": path, "content": content}, founder_id)


# ── YouTube (data) ────────────────────────────────────────────────────────────

def composio_youtube_search(founder_id: str, query: str, max_results: int = 10) -> dict:
    """Search YouTube videos via the founder's account. Args: query, max_results."""
    return _run("YOUTUBE_SEARCH", {"q": query, "max_results": max_results}, founder_id)


# ── Outlook ───────────────────────────────────────────────────────────────────

def composio_outlook_send_email(founder_id: str, to: str, subject: str, body: str) -> dict:
    """Send an email via Outlook/Microsoft 365. Args: to, subject, body."""
    return _run("OUTLOOK_SEND_EMAIL", {"to": to, "subject": subject, "body": body}, founder_id)


# Map of every extended tool key -> callable, for direct resolution.
EXTENDED_TOOLS: dict[str, Any] = {
    "composio_run_action": composio_run_action,
    "composio_slack_send_message": composio_slack_send_message,
    "composio_discord_send_message": composio_discord_send_message,
    "composio_twitter_post": composio_twitter_post,
    "composio_reddit_post": composio_reddit_post,
    "composio_telegram_send_message": composio_telegram_send_message,
    "composio_gmail_fetch": composio_gmail_fetch,
    "composio_sheets_append_row": composio_sheets_append_row,
    "composio_sheets_read": composio_sheets_read,
    "composio_docs_create": composio_docs_create,
    "composio_drive_upload": composio_drive_upload,
    "google_docs_create_document": google_docs_create_document,
    "google_docs_append_text": google_docs_append_text,
    "google_docs_read_document": google_docs_read_document,
    "google_sheets_create_spreadsheet": google_sheets_create_spreadsheet,
    "google_sheets_append_row": google_sheets_append_row,
    "google_sheets_read": google_sheets_read,
    "google_sheets_update_range": google_sheets_update_range,
    "google_slides_create_presentation": google_slides_create_presentation,
    "google_slides_add_slide": google_slides_add_slide,
    "google_drive_list_files": google_drive_list_files,
    "google_drive_read_file": google_drive_read_file,
    "google_drive_create_text_file": google_drive_create_text_file,
    "google_calendar_create_event": google_calendar_create_event,
    "google_calendar_list_events": google_calendar_list_events,
    "composio_airtable_create_record": composio_airtable_create_record,
    "composio_trello_create_card": composio_trello_create_card,
    "composio_asana_create_task": composio_asana_create_task,
    "composio_clickup_create_task": composio_clickup_create_task,
    "composio_jira_create_issue": composio_jira_create_issue,
    "composio_hubspot_create_contact": composio_hubspot_create_contact,
    "composio_mailchimp_add_subscriber": composio_mailchimp_add_subscriber,
    "composio_calendly_list_events": composio_calendly_list_events,
    "composio_zoom_create_meeting": composio_zoom_create_meeting,
    "composio_dropbox_upload": composio_dropbox_upload,
    "composio_youtube_search": composio_youtube_search,
    "composio_outlook_send_email": composio_outlook_send_email,
    # Reuse existing composio wrappers from composio_tools too.
}

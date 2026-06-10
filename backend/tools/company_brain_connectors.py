"""Provider import adapters for the company brain.

These adapters are intentionally thin and deterministic: they pull a bounded
snapshot from connected tools, normalize the payload into company-brain records,
and let backend.tools.company_brain own storage, graphing, and maintenance.
"""
from __future__ import annotations

import base64
import logging
import re
from pathlib import Path
from typing import Any

import requests

from backend.provisioning.credentials_store import load_credentials
from backend.tools.company_brain import ingest_company_brain_records

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20


def _token(founder_id: str, service: str, *keys: str) -> str:
    creds = load_credentials(founder_id, service) or {}
    for key in keys or ("token", "api_key", "access_token"):
        value = creds.get(key)
        if value:
            return str(value)
    return ""


def _safe_get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    resp = requests.get(url, headers=headers, params=params or {}, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _safe_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
    resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _github_headers(founder_id: str) -> dict[str, str] | None:
    token = _token(founder_id, "github", "token", "access_token")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def import_github(
    founder_id: str,
    limit: int = 12,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import GitHub repos, recent issues, pull requests, and READMEs."""
    headers = _github_headers(founder_id)
    if headers is None:
        return {"ok": False, "source": "github", "error": "GitHub token not configured"}

    records: list[dict[str, Any]] = []
    cursor = _connector_cursor(founder_id, "github")
    max_seen = cursor
    try:
        repos = _safe_get(
            "https://api.github.com/user/repos",
            headers,
            {"sort": "updated", "direction": "desc", "per_page": max(1, min(limit, 50))},
        )
        if not isinstance(repos, list):
            repos = []
        for repo in repos:
            repo_updated = str(repo.get("updated_at") or "")
            max_seen = _max_cursor(max_seen, repo_updated)
            if cursor and repo_updated and repo_updated <= cursor:
                continue
            full_name = repo.get("full_name") or repo.get("name") or "repo"
            description = repo.get("description") or ""
            records.append({
                "title": f"Repository: {full_name}",
                "content": f"{description}\nLanguage: {repo.get('language') or 'unknown'}\nDefault branch: {repo.get('default_branch') or 'main'}",
                "url": repo.get("html_url") or "",
                "kind": "repository",
                "canonical": True,
                "domain": "architecture",
                "repo": full_name,
                "updated_at": repo.get("updated_at"),
            })

            owner, name = (full_name.split("/", 1) + [""])[:2]
            if owner and name:
                activity, activity_cursor = _github_repo_activity(headers, owner, name, full_name, cursor)
                max_seen = _max_cursor(max_seen, activity_cursor)
                records.extend(activity)
    except Exception as exc:
        logger.warning("GitHub import failed: %s", exc)
        return {"ok": False, "source": "github", "error": str(exc)}

    result = ingest_company_brain_records(founder_id, "github", records, company_id)
    return {**result, "ok": True, "source": "github", "cursor": max_seen}


def _github_repo_activity(headers: dict[str, str], owner: str, repo: str, full_name: str, cursor: str = "") -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    max_seen = cursor
    base = f"https://api.github.com/repos/{owner}/{repo}"
    if not cursor:
        try:
            readme = _safe_get(f"{base}/readme", headers)
            if isinstance(readme, dict) and readme.get("content"):
                raw = base64.b64decode(str(readme["content"]).replace("\n", "")).decode("utf-8", errors="replace")
                records.append({
                    "title": f"README: {full_name}",
                    "content": raw[:8000],
                    "url": readme.get("html_url") or "",
                    "kind": "readme",
                    "canonical": True,
                    "domain": "architecture",
                    "repo": full_name,
                })
        except Exception:
            pass

    for endpoint, kind in (("issues", "issue"), ("pulls", "pull_request")):
        try:
            items = _safe_get(f"{base}/{endpoint}", headers, {"state": "all", "per_page": 10, "sort": "updated", "direction": "desc"})
            if not isinstance(items, list):
                continue
            for item in items[:10]:
                if kind == "issue" and item.get("pull_request"):
                    continue
                updated_at = str(item.get("updated_at") or "")
                max_seen = _max_cursor(max_seen, updated_at)
                if cursor and updated_at and updated_at <= cursor:
                    continue
                body = item.get("body") or ""
                records.append({
                    "title": f"{kind.replace('_', ' ').title()} #{item.get('number')}: {item.get('title')}",
                    "content": f"State: {item.get('state')}\n{body}",
                    "url": item.get("html_url") or "",
                    "kind": kind,
                    "canonical": False,
                    "stale_risk": "medium" if item.get("state") == "open" else "high",
                    "domain": "architecture" if kind == "pull_request" else "product",
                    "repo": full_name,
                    "state": item.get("state"),
                    "updated_at": updated_at,
                })
        except Exception:
            continue
    return records, max_seen


def _connector_cursor(founder_id: str, source: str) -> str:
    try:
        from backend.connector_sync_ledger import get_connector_cursor
        return get_connector_cursor(founder_id, source)
    except Exception:
        return ""


def _max_cursor(current: str, candidate: str) -> str:
    if not candidate:
        return current or ""
    if not current or candidate > current:
        return candidate
    return current


def import_slack(
    founder_id: str,
    limit: int = 8,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import recent Slack public-channel messages using a bot token."""
    token = _token(founder_id, "slack", "bot_token", "token", "access_token")
    if not token:
        return {"ok": False, "source": "slack", "error": "Slack bot token not configured"}
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict[str, Any]] = []
    cursor = _connector_cursor(founder_id, "slack")
    max_seen = cursor
    try:
        channels = _safe_get(
            "https://slack.com/api/conversations.list",
            headers,
            {"types": "public_channel,private_channel", "limit": max(1, min(limit, 50))},
        )
        if not isinstance(channels, dict) or not channels.get("ok"):
            return {"ok": False, "source": "slack", "error": str(channels)}
        for channel in (channels.get("channels") or [])[:limit]:
            channel_id = channel.get("id")
            channel_name = channel.get("name") or channel_id
            history_params: dict[str, Any] = {"channel": channel_id, "limit": 20}
            if cursor:
                history_params["oldest"] = cursor
                history_params["inclusive"] = False
            history = _safe_get(
                "https://slack.com/api/conversations.history",
                headers,
                history_params,
            )
            if not isinstance(history, dict) or not history.get("ok"):
                continue
            for msg in history.get("messages", [])[:20]:
                text = msg.get("text") or ""
                if not text.strip():
                    continue
                msg_ts = str(msg.get("ts") or "")
                max_seen = _max_cursor(max_seen, msg_ts)
                if cursor and msg_ts and msg_ts <= cursor:
                    continue
                thread_ts = msg.get("thread_ts") or msg.get("ts")
                reply_text, reply_cursor = _slack_thread_text(headers, channel_id, thread_ts, msg.get("ts"), cursor)
                max_seen = _max_cursor(max_seen, reply_cursor)
                content = text if not reply_text else f"{text}\n\nThread replies:\n{reply_text}"
                records.append({
                    "title": f"Slack #{channel_name} {msg.get('ts')}",
                    "content": content,
                    "kind": "message",
                    "canonical": False,
                    "stale_risk": "medium",
                    "domain": "operations",
                    "channel": channel_name,
                    "thread_ts": thread_ts,
                    "author": msg.get("user") or msg.get("bot_id") or "",
                    "external_id": msg_ts,
                    "updated_at": msg_ts,
                })
    except Exception as exc:
        logger.warning("Slack import failed: %s", exc)
        return {"ok": False, "source": "slack", "error": str(exc)}
    result = ingest_company_brain_records(founder_id, "slack", records, company_id)
    return {**result, "ok": True, "source": "slack", "cursor": max_seen}


def _slack_thread_text(headers: dict[str, str], channel_id: str, thread_ts: str | None, root_ts: str | None, cursor: str = "") -> tuple[str, str]:
    if not channel_id or not thread_ts:
        return "", cursor
    try:
        replies = _safe_get(
            "https://slack.com/api/conversations.replies",
            headers,
            {"channel": channel_id, "ts": thread_ts, "limit": 20},
        )
    except Exception:
        return "", cursor
    if not isinstance(replies, dict) or not replies.get("ok"):
        return "", cursor
    lines = []
    max_seen = cursor
    for reply in replies.get("messages", [])[1:]:
        text = reply.get("text") or ""
        reply_ts = str(reply.get("ts") or "")
        max_seen = _max_cursor(max_seen, reply_ts)
        if cursor and reply_ts and reply_ts <= cursor:
            continue
        if text.strip():
            lines.append(f"- {reply.get('user') or reply.get('bot_id') or 'unknown'}: {text}")
    return "\n".join(lines), max_seen


def import_discord(
    founder_id: str,
    limit: int = 8,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import recent Discord text-channel messages using a bot token."""
    token = _token(founder_id, "discord", "bot_token", "token")
    if not token:
        return {"ok": False, "source": "discord", "error": "Discord bot token not configured"}
    headers = {"Authorization": f"Bot {token}"}
    records: list[dict[str, Any]] = []
    cursor = _connector_cursor(founder_id, "discord")
    max_seen = cursor
    try:
        guilds = _safe_get("https://discord.com/api/v10/users/@me/guilds", headers, {"limit": max(1, min(limit, 100))})
        if not isinstance(guilds, list):
            return {"ok": False, "source": "discord", "error": str(guilds)}
        for guild in guilds[:limit]:
            guild_id = guild.get("id")
            guild_name = guild.get("name") or guild_id or "Discord server"
            if not guild_id:
                continue
            channels = _safe_get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers)
            if not isinstance(channels, list):
                continue
            text_channels = [channel for channel in channels if channel.get("type") == 0]
            for channel in text_channels[: max(1, min(limit, 10))]:
                channel_id = channel.get("id")
                channel_name = channel.get("name") or channel_id or "channel"
                if not channel_id:
                    continue
                try:
                    message_params: dict[str, Any] = {"limit": 20}
                    if cursor:
                        message_params["after"] = cursor
                    messages = _safe_get(
                        f"https://discord.com/api/v10/channels/{channel_id}/messages",
                        headers,
                        message_params,
                    )
                except Exception:
                    continue
                if not isinstance(messages, list):
                    continue
                for msg in messages[:20]:
                    msg_id = str(msg.get("id") or "")
                    max_seen = _max_cursor(max_seen, msg_id)
                    if cursor and msg_id and msg_id <= cursor:
                        continue
                    text = msg.get("content") or ""
                    attachments = msg.get("attachments") or []
                    embeds = msg.get("embeds") or []
                    if not text.strip() and not attachments and not embeds:
                        continue
                    author = msg.get("author") or {}
                    attachment_lines = [a.get("url") for a in attachments if a.get("url")]
                    embed_lines = [e.get("title") or e.get("description") for e in embeds if e.get("title") or e.get("description")]
                    extra = "\n".join([*attachment_lines, *embed_lines])
                    records.append({
                        "title": f"Discord #{channel_name} {msg.get('id')}",
                        "content": text if not extra else f"{text}\n\n{extra}".strip(),
                        "kind": "message",
                        "canonical": False,
                        "stale_risk": "medium",
                        "domain": "operations",
                        "server": guild_name,
                        "channel": channel_name,
                        "author": author.get("username") or author.get("id") or "",
                        "external_id": msg_id,
                        "updated_at": msg.get("edited_timestamp") or msg.get("timestamp"),
                    })
    except Exception as exc:
        logger.warning("Discord import failed: %s", exc)
        return {"ok": False, "source": "discord", "error": str(exc)}
    result = ingest_company_brain_records(founder_id, "discord", records, company_id)
    return {**result, "ok": True, "source": "discord", "cursor": max_seen}


def import_notion(
    founder_id: str,
    limit: int = 20,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import Notion pages/databases visible to a saved integration token."""
    token = _token(founder_id, "notion", "token", "api_key", "access_token")
    if not token:
        try:
            from backend.config import settings
            token = getattr(settings, "notion_token", "") or ""
        except Exception:
            token = ""
    if not token:
        return {"ok": False, "source": "notion", "error": "Notion token not configured"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    records: list[dict[str, Any]] = []
    cursor = _connector_cursor(founder_id, "notion")
    max_seen = cursor
    try:
        payload: dict[str, Any] = {
            "page_size": max(1, min(limit, 100)),
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        resp = requests.post(
            "https://api.notion.com/v1/search",
            headers=headers,
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("results", [])[:limit]:
            edited_at = str(item.get("last_edited_time") or "")
            max_seen = _max_cursor(max_seen, edited_at)
            if cursor and edited_at and edited_at <= cursor:
                continue
            title = _notion_title(item) or item.get("id", "Notion page")
            content = title
            if item.get("object") == "page":
                content = _notion_page_text(headers, item.get("id")) or title
            records.append({
                "title": title,
                "content": content,
                "url": item.get("url") or "",
                "kind": item.get("object") or "page",
                "canonical": True,
                "stale_risk": "low",
                "domain": "operations",
                "external_id": item.get("id"),
                "updated_at": edited_at,
            })
    except Exception as exc:
        logger.warning("Notion import failed: %s", exc)
        return {"ok": False, "source": "notion", "error": str(exc)}
    result = ingest_company_brain_records(founder_id, "notion", records, company_id)
    return {**result, "ok": True, "source": "notion", "cursor": max_seen}


def _notion_title(item: dict[str, Any]) -> str:
    props = item.get("properties") or {}
    for value in props.values():
        if value.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in value.get("title", [])).strip()
    return item.get("title", "")


def _notion_page_text(headers: dict[str, str], page_id: str | None) -> str:
    if not page_id:
        return ""
    try:
        data = _safe_get(f"https://api.notion.com/v1/blocks/{page_id}/children", headers, {"page_size": 50})
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    lines: list[str] = []
    for block in data.get("results", []):
        block_type = block.get("type")
        rich = (block.get(block_type) or {}).get("rich_text") or []
        text = "".join(part.get("plain_text", "") for part in rich).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def import_google_drive(
    founder_id: str,
    limit: int = 20,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import Google Drive file metadata and Google Docs/Sheets/Slides export text."""
    token = _token(founder_id, "google_drive", "token", "access_token") or _token(founder_id, "google", "token", "access_token")
    if not token:
        return {"ok": False, "source": "google_drive", "error": "Google Drive access token not configured"}
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict[str, Any]] = []
    cursor = _connector_cursor(founder_id, "google_drive")
    max_seen = cursor
    try:
        params: dict[str, Any] = {
            "pageSize": max(1, min(limit, 100)),
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime,description)",
            "orderBy": "modifiedTime desc",
        }
        if cursor:
            params["q"] = f"modifiedTime > '{cursor}'"
        data = _safe_get(
            "https://www.googleapis.com/drive/v3/files",
            headers,
            params,
        )
        if not isinstance(data, dict):
            data = {}
        for item in data.get("files", [])[:limit]:
            modified_time = str(item.get("modifiedTime") or "")
            max_seen = _max_cursor(max_seen, modified_time)
            if cursor and modified_time and modified_time <= cursor:
                continue
            mime_type = str(item.get("mimeType") or "")
            exported = _google_export_text(headers, item.get("id"), mime_type)
            records.append({
                "title": item.get("name") or item.get("id") or "Drive file",
                "content": exported or item.get("description") or f"Google Drive file: {item.get('name')} ({item.get('mimeType')})",
                "url": item.get("webViewLink") or "",
                "kind": "file",
                "canonical": bool(exported) or "document" in mime_type,
                "stale_risk": "medium",
                "domain": "operations",
                "external_id": item.get("id"),
                "updated_at": modified_time,
            })
    except Exception as exc:
        logger.warning("Google Drive import failed: %s", exc)
        return {"ok": False, "source": "google_drive", "error": str(exc)}
    result = ingest_company_brain_records(founder_id, "google_drive", records, company_id)
    return {**result, "ok": True, "source": "google_drive", "cursor": max_seen}


def _google_export_text(headers: dict[str, str], file_id: str | None, mime_type: str) -> str:
    if not file_id or not mime_type.startswith("application/vnd.google-apps."):
        return ""
    export_mime = "text/plain"
    if mime_type.endswith(".spreadsheet"):
        export_mime = "text/csv"
    elif mime_type.endswith(".presentation"):
        export_mime = "text/plain"
    try:
        resp = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
            headers=headers,
            params={"mimeType": export_mime},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text[:8000]
    except Exception:
        return ""


def import_gmail(
    founder_id: str,
    limit: int = 20,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import Gmail message metadata and snippets."""
    token = _token(founder_id, "gmail", "token", "access_token") or _token(founder_id, "google", "token", "access_token")
    if not token:
        return {"ok": False, "source": "gmail", "error": "Gmail access token not configured"}
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict[str, Any]] = []
    try:
        listing = _safe_get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers,
            {"maxResults": max(1, min(limit, 100))},
        )
        if not isinstance(listing, dict):
            listing = {}
        for msg in listing.get("messages", [])[:limit]:
            detail = _safe_get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg.get('id')}",
                headers,
                {"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            )
            if not isinstance(detail, dict):
                continue
            headers_list = (detail.get("payload") or {}).get("headers") or []
            header_map = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}
            subject = header_map.get("subject") or detail.get("id") or "Gmail message"
            records.append({
                "title": f"Email: {subject}",
                "content": detail.get("snippet") or subject,
                "kind": "email",
                "canonical": False,
                "stale_risk": "medium",
                "domain": "operations",
                "external_id": detail.get("id"),
                "author": header_map.get("from"),
                "updated_at": header_map.get("date"),
            })
    except Exception as exc:
        logger.warning("Gmail import failed: %s", exc)
        return {"ok": False, "source": "gmail", "error": str(exc)}
    result = ingest_company_brain_records(founder_id, "gmail", records, company_id)
    return {**result, "ok": True, "source": "gmail"}


def import_obsidian(
    founder_id: str,
    limit: int = 80,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import Markdown notes from a configured local Obsidian vault path."""
    creds = load_credentials(founder_id, "obsidian") or {}
    vault_path = str(creds.get("vault_path") or creds.get("path") or "").strip()
    if not vault_path:
        return {"ok": False, "source": "obsidian", "error": "Obsidian vault_path not configured"}
    root = Path(vault_path).expanduser()
    if not root.exists() or not root.is_dir():
        return {"ok": False, "source": "obsidian", "error": f"Obsidian vault path not found: {root}"}

    records: list[dict[str, Any]] = []
    try:
        note_files = sorted(root.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[: max(1, min(limit, 300))]
        for note_file in note_files:
            text = note_file.read_text(errors="replace").strip()
            if not text:
                continue
            rel = note_file.relative_to(root)
            title = note_file.stem.replace("_", " ").strip() or str(rel)
            frontmatter: dict[str, Any] = {}
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    text = parts[2].strip()
                    for line in parts[1].splitlines():
                        if ":" in line:
                            key, value = line.split(":", 1)
                            frontmatter[key.strip()] = value.strip().strip('"')
            records.append({
                "title": title,
                "content": text[:8000],
                "url": str(note_file),
                "kind": frontmatter.get("kind") or "note",
                "canonical": str(frontmatter.get("canonical", "")).lower() in {"true", "yes", "1"},
                "stale_risk": frontmatter.get("stale_risk") or "medium",
                "domain": frontmatter.get("domain") or "operations",
                "external_id": str(rel),
                "updated_at": note_file.stat().st_mtime,
                "visibility": frontmatter.get("visibility") or "team",
            })
    except Exception as exc:
        logger.warning("Obsidian import failed: %s", exc)
        return {"ok": False, "source": "obsidian", "error": str(exc)}

    result = ingest_company_brain_records(founder_id, "obsidian", records, company_id)
    return {**result, "ok": True, "source": "obsidian"}


def import_linear(
    founder_id: str,
    limit: int = 30,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import recent Linear issues from a saved API token."""
    token = _token(founder_id, "linear", "token", "api_key", "access_token")
    if not token:
        return {"ok": False, "source": "linear", "error": "Linear token not configured"}
    headers = {"Authorization": token, "Content-Type": "application/json"}
    query = """
    query ImportIssues($first: Int!) {
      issues(first: $first, orderBy: updatedAt) {
        nodes {
          id identifier title description url priority updatedAt
          state { name type }
          assignee { name email }
          team { name key }
        }
      }
    }
    """
    try:
        data = _safe_post("https://api.linear.app/graphql", headers, {"query": query, "variables": {"first": max(1, min(limit, 100))}})
        issues = (((data or {}).get("data") or {}).get("issues") or {}).get("nodes", []) if isinstance(data, dict) else []
    except Exception as exc:
        logger.warning("Linear import failed: %s", exc)
        return {"ok": False, "source": "linear", "error": str(exc)}
    records = []
    for issue in issues:
        state = (issue.get("state") or {}).get("name", "")
        team = (issue.get("team") or {}).get("name", "")
        assignee = (issue.get("assignee") or {}).get("name", "")
        records.append({
            "title": f"{issue.get('identifier')}: {issue.get('title')}",
            "content": f"State: {state}\nTeam: {team}\nAssignee: {assignee}\nPriority: {issue.get('priority')}\n\n{issue.get('description') or ''}",
            "url": issue.get("url") or "",
            "kind": "issue",
            "canonical": False,
            "stale_risk": "medium" if state.lower() not in {"done", "canceled", "cancelled"} else "high",
            "domain": "product",
            "external_id": issue.get("id"),
            "state": state,
            "updated_at": issue.get("updatedAt"),
        })
    result = ingest_company_brain_records(founder_id, "linear", records, company_id)
    return {**result, "ok": True, "source": "linear"}


def import_zendesk(
    founder_id: str,
    limit: int = 30,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import recent Zendesk tickets using subdomain/email/token credentials."""
    creds = load_credentials(founder_id, "zendesk") or {}
    subdomain = creds.get("subdomain")
    email = creds.get("email")
    token = creds.get("token") or creds.get("api_token")
    if not (subdomain and email and token):
        return {"ok": False, "source": "zendesk", "error": "Zendesk subdomain/email/token not configured"}
    auth = (f"{email}/token", token)
    try:
        resp = requests.get(
            f"https://{subdomain}.zendesk.com/api/v2/tickets.json",
            auth=auth,
            params={"sort_by": "updated_at", "sort_order": "desc", "per_page": max(1, min(limit, 100))},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        tickets = resp.json().get("tickets", [])
    except Exception as exc:
        logger.warning("Zendesk import failed: %s", exc)
        return {"ok": False, "source": "zendesk", "error": str(exc)}
    records = []
    for ticket in tickets:
        records.append({
            "title": f"Ticket #{ticket.get('id')}: {ticket.get('subject')}",
            "content": f"Status: {ticket.get('status')}\nPriority: {ticket.get('priority')}\n\n{ticket.get('description') or ''}",
            "url": f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}",
            "kind": "ticket",
            "canonical": False,
            "stale_risk": "medium" if ticket.get("status") not in {"closed", "solved"} else "high",
            "domain": "support",
            "external_id": ticket.get("id"),
            "state": ticket.get("status"),
            "updated_at": ticket.get("updated_at"),
        })
    result = ingest_company_brain_records(founder_id, "zendesk", records, company_id)
    return {**result, "ok": True, "source": "zendesk"}


def import_confluence(
    founder_id: str,
    limit: int = 30,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import recent Confluence pages using cloud/base URL credentials."""
    creds = load_credentials(founder_id, "confluence") or {}
    base_url = str(creds.get("base_url") or "").rstrip("/")
    email = creds.get("email")
    token = creds.get("token") or creds.get("api_token")
    if not (base_url and email and token):
        return {"ok": False, "source": "confluence", "error": "Confluence base_url/email/token not configured"}
    try:
        resp = requests.get(
            f"{base_url}/wiki/rest/api/content",
            auth=(email, token),
            params={
                "type": "page",
                "limit": max(1, min(limit, 100)),
                "expand": "body.storage,version,space",
                "orderby": "modified",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])
    except Exception as exc:
        logger.warning("Confluence import failed: %s", exc)
        return {"ok": False, "source": "confluence", "error": str(exc)}
    records = []
    for page in pages:
        html = (((page.get("body") or {}).get("storage") or {}).get("value") or "")
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        links = page.get("_links") or {}
        url = f"{base_url}{links.get('webui', '')}" if links.get("webui") else base_url
        records.append({
            "title": page.get("title") or page.get("id") or "Confluence page",
            "content": text or page.get("title") or "",
            "url": url,
            "kind": "page",
            "canonical": True,
            "stale_risk": "low",
            "domain": "operations",
            "external_id": page.get("id"),
            "updated_at": ((page.get("version") or {}).get("when")),
        })
    result = ingest_company_brain_records(founder_id, "confluence", records, company_id)
    return {**result, "ok": True, "source": "confluence"}


IMPORTERS = {
    "github": import_github,
    "slack": import_slack,
    "discord": import_discord,
    "notion": import_notion,
    "linear": import_linear,
    "google_drive": import_google_drive,
    "google_workspace": import_google_drive,
    "gmail": import_gmail,
    "obsidian": import_obsidian,
    "zendesk": import_zendesk,
    "confluence": import_confluence,
}


def import_company_brain_source(
    founder_id: str,
    source: str,
    limit: int = 20,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import one source into the company brain."""
    importer = IMPORTERS.get(source)
    if importer is None:
        result = {"ok": False, "source": source, "error": f"No importer implemented for {source}"}
        _record_import_ledger(founder_id, source, result)
        return result
    if not company_id or company_id == founder_id:
        result = importer(founder_id, limit=limit)
    else:
        result = importer(founder_id, limit=limit, company_id=company_id)
    _record_import_ledger(founder_id, source, result)
    return result


def import_company_brain_sources(
    founder_id: str,
    sources: list[str] | None = None,
    limit: int = 20,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Import multiple connected sources into the company brain."""
    selected = sources or list(IMPORTERS)
    results = [
        import_company_brain_source(
            founder_id,
            source,
            limit=limit,
            company_id=company_id,
        )
        for source in selected
    ]
    return {
        "ok": any(result.get("ok") for result in results),
        "founder_id": founder_id,
        "company_id": company_id or founder_id,
        "results": results,
        "imported_sources": [r["source"] for r in results if r.get("ok")],
        "failed_sources": [r["source"] for r in results if not r.get("ok")],
    }


def _record_import_ledger(founder_id: str, source: str, result: dict[str, Any]) -> None:
    try:
        from backend.connector_sync_ledger import record_connector_sync
        imported = int(result.get("ingested") or result.get("record_count") or result.get("changed_records") or 0)
        record_connector_sync(
            founder_id,
            source,
            status="ok" if result.get("ok") else "error",
            imported=imported,
            changed_records=int(result.get("changed_records") or 0),
            cursor=str(result.get("cursor") or result.get("next_cursor") or ""),
            error=str(result.get("error") or ""),
            mode="import",
        )
    except Exception:
        pass

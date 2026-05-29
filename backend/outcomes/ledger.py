"""Outcome Ledger helpers.

Transforms raw agent/tool outputs into measurable business progress events.
This is intentionally conservative: it records obvious, material outputs rather
than trying to infer fuzzy value from arbitrary text.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any


_URL_KEYS = (
    "url",
    "preview_url",
    "deployment_url",
    "deploy_url",
    "project_url",
    "landing_page_url",
    "github_url",
)


def _clean_preview(value: Any, max_len: int = 180) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return text[:max_len]


def _list_len(result: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _first_text(result: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = result.get(key)
        if value:
            return _clean_preview(value)
    return ""


def _event(
    *,
    agent_name: str,
    task: Mapping[str, Any] | None,
    metric: str,
    label: str,
    value: int,
    unit: str,
    preview: str = "",
) -> dict[str, Any] | None:
    if value <= 0:
        return None
    return {
        "id": f"out_{uuid.uuid4().hex[:10]}",
        "agent": agent_name,
        "task_id": (task or {}).get("id", ""),
        "metric": metric,
        "label": label,
        "value": value,
        "unit": unit,
        "source": "agent_result",
        "preview": preview,
    }


def build_outcome_events(agent_name: str, result: Any, task: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build compact, UI-safe Outcome Ledger events from a completed task result."""
    if not isinstance(result, Mapping):
        return []

    events: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        event = _event(agent_name=agent_name, task=task, **kwargs)
        if event:
            events.append(event)

    add(
        metric="leads_found",
        label="Leads found",
        value=_list_len(result, "leads", "prospects", "contacts"),
        unit="leads",
        preview=_first_text(result, "lead_summary", "summary", "output_summary"),
    )
    add(
        metric="outreach_sequences",
        label="Outreach sequences created",
        value=_list_len(result, "sequences", "campaigns", "outreach_sequences"),
        unit="sequences",
        preview=_first_text(result, "sequence_summary", "summary", "output_summary"),
    )
    add(
        metric="emails_drafted",
        label="Emails drafted",
        value=_list_len(result, "sequence", "emails", "email_drafts"),
        unit="emails",
        preview=_first_text(result, "email_summary", "summary", "output_summary"),
    )
    add(
        metric="crm_records_prepared",
        label="CRM records prepared",
        value=_list_len(result, "crm_contacts", "crm_records"),
        unit="records",
        preview=_first_text(result, "crm_summary", "summary", "output_summary"),
    )
    add(
        metric="sources_reviewed",
        label="Sources reviewed",
        value=_list_len(result, "sources", "urls", "visited_urls", "citations"),
        unit="sources",
        preview=_first_text(result, "research_summary", "summary", "report", "formatted_text"),
    )
    add(
        metric="commits_created",
        label="Commits created",
        value=_list_len(result, "commits"),
        unit="commits",
        preview=_first_text(result, "repo_url", "github_url", "summary", "output_summary"),
    )
    add(
        metric="documents_created",
        label="Documents created",
        value=_list_len(result, "documents", "pdfs", "files"),
        unit="documents",
        preview=_first_text(result, "document_summary", "path", "filename", "summary", "output_summary"),
    )
    add(
        metric="ad_creatives_created",
        label="Ad creatives created",
        value=_list_len(result, "ad_images", "creatives", "assets"),
        unit="creatives",
        preview=_first_text(result, "creative_summary", "summary", "output_summary"),
    )

    files_in_repo = result.get("files_in_repo")
    if isinstance(files_in_repo, int):
        add(
            metric="files_created",
            label="Files created",
            value=files_in_repo,
            unit="files",
            preview=_first_text(result, "repo_url", "github_url", "summary", "output_summary"),
        )

    if any(isinstance(result.get(key), str) and str(result.get(key)).startswith(("http://", "https://")) for key in _URL_KEYS):
        add(
            metric="pages_deployed",
            label="Live URLs produced",
            value=1,
            unit="url",
            preview=_first_text(result, *_URL_KEYS),
        )

    if isinstance(result.get("repo_url"), str) or isinstance(result.get("github_url"), str):
        add(
            metric="repos_created",
            label="Repos created",
            value=1,
            unit="repo",
            preview=_first_text(result, "repo_url", "github_url"),
        )

    if any(result.get(key) for key in ("reel_package", "tiktok_package", "meta_ad", "social_content")):
        add(
            metric="marketing_assets_created",
            label="Marketing assets created",
            value=1,
            unit="asset set",
            preview=_first_text(result, "reel_package", "tiktok_package", "meta_ad", "summary", "output_summary"),
        )

    return events[:8]

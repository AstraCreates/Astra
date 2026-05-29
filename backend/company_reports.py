"""Founder-level reports from Company Brain records."""

from __future__ import annotations

import time
from typing import Any

from backend.tools.company_brain import add_company_brain_record, get_company_brain


TEAM_AGENT_ALIASES: dict[str, set[str]] = {
    "engineering": {"technical", "web", "design"},
    "product": {"technical", "design", "research", "ops"},
    "growth": {"marketing", "sales", "web", "research"},
    "sales": {"sales", "research", "marketing"},
    "marketing": {"marketing", "design", "web", "research"},
    "support": {"ops", "technical", "research", "support"},
    "ops": {"ops", "legal", "research"},
    "legal": {"legal", "ops"},
}


def _epoch_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def _clip(value: Any, limit: int = 260) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _team_agents(team: str) -> set[str]:
    normalized = team.lower().strip().replace(" team", "").replace(" subteam", "")
    return TEAM_AGENT_ALIASES.get(normalized, {normalized})


def _record_matches_agents(record: dict[str, Any], agents: set[str]) -> bool:
    metadata = record.get("metadata") or {}
    agent = str(metadata.get("agent") or "").lower()
    if agent in agents:
        return True
    hay = f"{record.get('title', '')} {record.get('content', '')} {record.get('kind', '')} {record.get('domain', '')}".lower()
    return any(token in hay for token in agents)


def build_company_subteam_report(founder_id: str, team: str = "engineering", days: int = 7) -> dict[str, Any]:
    """Report what a functional subteam did across persisted company memory."""
    data = get_company_brain(founder_id)
    agents = _team_agents(team)
    bounded_days = max(1, min(int(days or 7), 365))
    cutoff = time.time() - bounded_days * 86400
    records: list[dict[str, Any]] = []

    for record in data.get("records", []):
        updated = _epoch_from_iso(record.get("updated_at"))
        if updated is not None and updated < cutoff:
            continue
        if _record_matches_agents(record, agents):
            records.append(record)

    records.sort(key=lambda rec: rec.get("updated_at", ""), reverse=True)
    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    sessions: set[str] = set()
    highlights: list[dict[str, Any]] = []
    for record in records[:20]:
        kind = str(record.get("kind") or "note")
        source = str(record.get("source") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        session_id = (record.get("metadata") or {}).get("session_id")
        if session_id:
            sessions.add(str(session_id))
        highlights.append({
            "id": record.get("id"),
            "title": record.get("title"),
            "source": source,
            "kind": kind,
            "updated_at": record.get("updated_at"),
            "snippet": _clip(record.get("snippet") or record.get("content")),
            "canonical": bool(record.get("canonical")),
        })

    next_actions: list[str] = []
    if not records:
        next_actions.append(f"No {team} records found in Company Brain for the last {bounded_days} days; sync connectors or run a stack first.")
    else:
        next_actions.append(f"Review {len(highlights)} recent {team} records and promote authoritative outputs to canonical memory.")
        if any(item["kind"] == "operating_plan" for item in highlights):
            next_actions.append("Compare the current operating plan against completed records.")
        if any(item["kind"] == "run_digest" for item in highlights):
            next_actions.append("Use run digests to choose the next continuation run.")

    return {
        "founder_id": founder_id,
        "team": team,
        "agents": sorted(agents),
        "window_days": bounded_days,
        "record_count": len(records),
        "session_count": len(sessions),
        "by_kind": by_kind,
        "by_source": by_source,
        "highlights": highlights,
        "summary": (
            f"{team.title()} has {len(records)} company-brain records in the last {bounded_days} days "
            f"across {len(sessions)} sessions."
        ),
        "next_actions": next_actions[:5],
    }


def persist_company_subteam_report(report: dict[str, Any]) -> None:
    """Persist a generated report as memory for future company questions."""
    import json

    founder_id = str(report.get("founder_id") or "")
    if not founder_id:
        return
    team = str(report.get("team") or "team")
    days = int(report.get("window_days") or 7)
    add_company_brain_record(
        founder_id=founder_id,
        source="astra",
        title=f"{team.title()} Subteam Report - Last {days} Days",
        content=json.dumps(report, indent=2),
        kind="subteam_report",
        canonical=False,
        stale_risk="low",
    )

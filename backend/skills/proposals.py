"""Tenant-scoped, review-required organizational learning proposals."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.skills.store import create_skill, get_skill, update_skill

_lock = threading.Lock()
_SECRET_RE = re.compile(r"(?:sk-|token|secret|password|api[_-]?key)", re.I)
_ALLOWED = {"draft", "approved", "rejected", "active", "archived"}


def _path(founder_id: str) -> Path:
    root = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")) / "skills" / founder_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "proposals.json"


def _load(founder_id: str) -> dict[str, Any]:
    path = _path(founder_id)
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _save(founder_id: str, rows: dict[str, Any]) -> None:
    _path(founder_id).write_text(json.dumps(rows, indent=2, sort_keys=True))


def create_proposal(
    *, founder_id: str, specialist: str, source_session: str, evidence: str,
    proposed_change: str, risk_level: str = "low", reviewer: str = "agent",
    skill_id: str | None = None,
) -> dict[str, Any]:
    if _SECRET_RE.search(evidence + proposed_change):
        raise ValueError("Proposal appears to contain credentials or secrets")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    proposal_id = f"sp_{uuid.uuid4().hex[:16]}"
    proposal = {
        "id": proposal_id, "founder_id": founder_id, "specialist": specialist,
        "source_session": source_session, "evidence": evidence[:6000],
        "proposed_change": proposed_change[:20_000], "risk_level": risk_level,
        "reviewer": reviewer, "version": 1, "status": "draft",
        "skill_id": skill_id, "created_at": now, "resolved_at": None,
    }
    with _lock:
        rows = _load(founder_id)
        rows[proposal_id] = proposal
        _save(founder_id, rows)
    return proposal


def list_proposals(founder_id: str, status: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_load(founder_id).values())
    rows = [row for row in rows if status is None or row.get("status") == status]
    return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)


def resolve_proposal(founder_id: str, proposal_id: str, status: str, reviewer: str) -> dict[str, Any] | None:
    if status not in {"approved", "rejected", "archived"}:
        raise ValueError("Invalid proposal resolution")
    with _lock:
        rows = _load(founder_id)
        row = rows.get(proposal_id)
        if not row:
            return None
        row.update(status=status, reviewer=reviewer, resolved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        rows[proposal_id] = row
        _save(founder_id, rows)
    return row


def activate_proposal(founder_id: str, proposal_id: str, reviewer: str) -> dict[str, Any] | None:
    with _lock:
        rows = _load(founder_id)
        row = rows.get(proposal_id)
        if not row or row.get("status") != "approved":
            return None
        skill_id = row.get("skill_id")
        existing = get_skill(founder_id, skill_id) if skill_id else None
        if existing:
            history = list(existing.get("version_history") or [])
            history.append({"version": existing.get("version", 1), "content": existing.get("content", "")})
            skill = update_skill(founder_id, skill_id, content=row["proposed_change"])
            if skill:
                skill = update_skill(
                    founder_id, skill_id,
                    version=int(existing.get("version", 1)) + 1,
                    version_history=history,
                )
        else:
            skill = create_skill(
                founder_id, f"{row['specialist']} learned workflow",
                description=f"Approved from session {row['source_session']}",
                content=row["proposed_change"], agent_keys=[row["specialist"]],
            )
            skill_id = skill["id"]
        row.update(status="active", reviewer=reviewer, skill_id=skill_id,
                   resolved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        rows[proposal_id] = row
        _save(founder_id, rows)
    return {"proposal": row, "skill": skill}


def rollback_skill(founder_id: str, skill_id: str) -> dict[str, Any] | None:
    existing = get_skill(founder_id, skill_id)
    if not existing:
        return None
    history = list(existing.get("version_history") or [])
    if not history:
        return None
    previous = history.pop()
    return update_skill(
        founder_id, skill_id,
        content=str(previous.get("content", "")),
        version=int(previous.get("version", 1)),
        version_history=history,
    )

"""Durable approval workflow ledger.

SafeRun gates need more than a transient "approved/skipped" event. This module
stores approval requests, approver role requirements, decision history, and
timestamps so sensitive actions can be audited after a backend restart.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

FINAL_APPROVAL_STATUSES = {"approved", "skipped", "rejected", "expired"}
ALLOWED_APPROVAL_DECISIONS = {"approved", "skipped", "rejected"}
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


def _root() -> Path:
    root = Path(".astra/approvals")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", session_id)[:120] or "session"
    return _root() / f"{safe}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load(session_id: str) -> dict[str, Any]:
    path = _path(session_id)
    if not path.exists():
        return {"session_id": session_id, "requests": [], "updated_at": _now()}
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {"session_id": session_id, "requests": [], "updated_at": _now()}
    data.setdefault("session_id", session_id)
    data.setdefault("requests", [])
    data.setdefault("updated_at", _now())
    return data


def _save(session_id: str, data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = _now()
    _path(session_id).write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("approval_workflows", session_id, data)
    except Exception:
        pass
    return data


def create_approval_request(
    session_id: str,
    gate_key: str,
    *,
    title: str = "",
    reason: str = "",
    action_id: str = "",
    tool: str = "",
    agent: str = "",
    risk_level: str = "medium",
    required_role: str = "owner",
    expires_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or refresh a pending approval request."""
    data = _load(session_id)
    request_id = f"{gate_key}:{action_id or tool or agent or 'request'}"
    existing = next((item for item in data["requests"] if item.get("id") == request_id), None)
    metadata = dict(metadata or {})
    existing_metadata = dict(existing.get("metadata") or {}) if existing else {}
    payload = {
        "id": request_id,
        "session_id": session_id,
        "gate_key": gate_key,
        "title": title or gate_key.replace("_", " ").title(),
        "reason": reason,
        "action_id": action_id,
        "tool": tool,
        "agent": agent,
        "risk_level": risk_level,
        "required_role": required_role,
        "expires_at": existing.get("expires_at") if existing else expires_at,
        "status": existing.get("status", "pending") if existing else "pending",
        "created_at": existing.get("created_at") if existing else _now(),
        "updated_at": _now(),
        "history": list(existing.get("history", [])) if existing else [],
        **existing_metadata,
        **metadata,
    }
    if metadata:
        payload["metadata"] = metadata
    if existing:
        data["requests"] = [payload if item.get("id") == request_id else item for item in data["requests"]]
    else:
        payload["history"].append({"at": _now(), "event": "requested", "actor": agent or "astra"})
        data["requests"].append(payload)
    _save(session_id, data)
    return payload


def decide_approval_request(
    session_id: str,
    gate_key: str,
    decision: str,
    *,
    request_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str = "owner",
    note: str | None = None,
) -> dict[str, Any]:
    """Record an approval decision against all pending requests for a gate."""
    data = _load(session_id)
    decision = decision.lower().strip()
    if decision not in ALLOWED_APPROVAL_DECISIONS:
        return {
            "ok": False,
            "session_id": session_id,
            "gate_key": gate_key,
            "decision": decision,
            "error": f"decision must be one of {sorted(ALLOWED_APPROVAL_DECISIONS)}",
            "requests": [],
        }
    changed: list[dict[str, Any]] = []
    for request in data.get("requests", []):
        if request.get("gate_key") != gate_key:
            continue
        if request_id and request.get("id") != request_id:
            continue
        if request.get("status") in FINAL_APPROVAL_STATUSES:
            continue
        required_role = request.get("required_role") or "owner"
        if not _role_allows(actor_role, required_role):
            request.setdefault("history", []).append({
                "at": _now(),
                "event": "decision_rejected",
                "actor": actor_id or "unknown",
                "role": actor_role,
                "note": f"requires {required_role}",
            })
            changed.append(request)
            continue
        request["status"] = decision
        request["decision"] = decision
        request["decided_by"] = actor_id
        request["decided_at"] = _now()
        request["note"] = note or ""
        request["updated_at"] = _now()
        request.setdefault("history", []).append({
            "at": _now(),
            "event": decision,
            "actor": actor_id or "founder",
            "role": actor_role,
            "note": note or "",
        })
        changed.append(request)
    _save(session_id, data)
    return {"ok": True, "session_id": session_id, "gate_key": gate_key, "decision": decision, "requests": changed}


def expire_approval_requests(session_id: str, *, now: str | None = None) -> dict[str, Any]:
    """Mark pending requests expired when their expires_at timestamp has passed."""
    data = _load(session_id)
    now_value = now or _now()
    expired: list[dict[str, Any]] = []
    for request in data.get("requests", []):
        if request.get("status") in FINAL_APPROVAL_STATUSES:
            continue
        expires_at = str(request.get("expires_at") or "")
        if not expires_at or expires_at > now_value:
            continue
        request["status"] = "expired"
        request["updated_at"] = now_value
        request.setdefault("history", []).append({
            "at": now_value,
            "event": "expired",
            "actor": "astra",
            "note": f"Approval expired at {expires_at}",
        })
        expired.append(request)
    if expired:
        _save(session_id, data)
    return {"ok": True, "session_id": session_id, "expired": expired, "expired_count": len(expired), "requests": data.get("requests", [])}


def get_approval_workflow(session_id: str) -> dict[str, Any]:
    """Return the durable approval workflow ledger for a session."""
    expire_approval_requests(session_id)
    return _load(session_id)


def _role_allows(actor_role: str, required_role: str) -> bool:
    return ROLE_RANK.get(actor_role, -1) >= ROLE_RANK.get(required_role, ROLE_RANK["owner"])

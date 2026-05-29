"""Durable run ledger for operational visibility.

The Redis/event stream is optimized for live UI replay. This ledger keeps a
small, restart-safe summary per run so production operators can answer: what is
running, what failed, what shipped, and how long did it take?
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _root() -> Path:
    root = Path(__file__).parent.parent / ".astra" / "run_ledger"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path() -> Path:
    return _root() / "index.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return {"sessions": {}}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data.get("sessions"), dict):
            data["sessions"] = {}
        return data
    except Exception:
        return {"sessions": {}}


def _save(data: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("run_ledgers", "index", data)
    except Exception:
        pass


def _default(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": "running",
        "goal": "",
        "founder_id": "",
        "company_name": "",
        "stack_id": "",
        "stack_name": "",
        "started_at": "",
        "ended_at": "",
        "updated_at": "",
        "duration_seconds": None,
        "last_event_id": 0,
        "event_count": 0,
        "agents": {},
        "agent_count": 0,
        "done_agents": 0,
        "running_agents": 0,
        "error_agents": 0,
        "artifact_count": 0,
        "outcome_count": 0,
        "approval_count": 0,
        "pending_approval_count": 0,
        "saferun_action_count": 0,
        "errors": [],
        "last_event_type": "",
    }


def record_run_event(session_id: str, event_id: int, event: dict[str, Any]) -> dict[str, Any]:
    data = _load()
    sessions = data.setdefault("sessions", {})
    row = {**_default(session_id), **(sessions.get(session_id) or {})}
    event_type = str(event.get("type") or "")
    now = str(event.get("ts_iso") or _now_iso())

    row["updated_at"] = now
    row["last_event_id"] = max(int(row.get("last_event_id") or 0), int(event_id))
    row["event_count"] = int(row.get("event_count") or 0) + 1
    row["last_event_type"] = event_type

    if event_type == "goal_start":
        row["status"] = "running"
        row["goal"] = str(event.get("goal") or row.get("goal") or "")
        row["founder_id"] = str(event.get("founder_id") or row.get("founder_id") or "")
        row["started_at"] = str(row.get("started_at") or now)
    elif event_type == "company_name":
        row["company_name"] = str(event.get("name") or row.get("company_name") or "")
    elif event_type == "stack_selected":
        stack = event.get("stack") or {}
        if isinstance(stack, dict):
            row["stack_id"] = str(stack.get("stack_id") or stack.get("id") or row.get("stack_id") or "")
            row["stack_name"] = str(stack.get("name") or row.get("stack_name") or "")
    elif event_type == "agent_start":
        _set_agent(row, event, "running")
    elif event_type == "agent_done":
        _set_agent(row, event, "done")
    elif event_type == "agent_error":
        _set_agent(row, event, "error")
        _add_error(row, event)
    elif event_type == "stack_artifact":
        row["artifact_count"] = int(row.get("artifact_count") or 0) + 1
    elif event_type == "outcome_recorded":
        row["outcome_count"] = int(row.get("outcome_count") or 0) + 1
    elif event_type in {"approval_request", "stack_approval_queue"}:
        row["approval_count"] = int(row.get("approval_count") or 0) + _approval_delta(event)
        row["pending_approval_count"] = int(row.get("pending_approval_count") or 0) + _approval_delta(event)
    elif event_type == "stack_approval_decision":
        row["pending_approval_count"] = max(0, int(row.get("pending_approval_count") or 0) - 1)
    elif event_type == "saferun_action":
        row["saferun_action_count"] = int(row.get("saferun_action_count") or 0) + 1
    elif event_type == "goal_done":
        row["status"] = "done"
        row["ended_at"] = now
    elif event_type == "goal_error":
        row["status"] = "error"
        row["ended_at"] = now
        _add_error(row, event)

    _recount_agents(row)
    _set_duration(row)
    sessions[session_id] = row
    data["updated_at"] = now
    _save(data)
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("runs", session_id, row)
    except Exception:
        pass
    return row


def get_run(session_id: str) -> dict[str, Any] | None:
    return _load().get("sessions", {}).get(session_id)


def list_runs(limit: int = 50, founder_id: str = "", status: str = "") -> list[dict[str, Any]]:
    rows = list((_load().get("sessions") or {}).values())
    if founder_id:
        rows = [row for row in rows if row.get("founder_id") == founder_id]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    rows.sort(key=lambda row: row.get("updated_at") or row.get("started_at") or "", reverse=True)
    return rows[: max(1, min(limit, 500))]


def ledger_metrics() -> dict[str, Any]:
    rows = list((_load().get("sessions") or {}).values())
    return {
        "runs_total": len(rows),
        "runs_running": sum(1 for row in rows if row.get("status") == "running"),
        "runs_done": sum(1 for row in rows if row.get("status") == "done"),
        "runs_error": sum(1 for row in rows if row.get("status") == "error"),
        "artifact_count": sum(int(row.get("artifact_count") or 0) for row in rows),
        "outcome_count": sum(int(row.get("outcome_count") or 0) for row in rows),
    }


def _set_agent(row: dict[str, Any], event: dict[str, Any], status: str) -> None:
    agent = str(event.get("agent") or "")
    if not agent:
        return
    agents = row.setdefault("agents", {})
    current = agents.get(agent) or {}
    agents[agent] = {
        **current,
        "agent": agent,
        "status": status,
        "task_id": event.get("task_id") or current.get("task_id") or "",
        "updated_at": event.get("ts_iso") or _now_iso(),
    }


def _add_error(row: dict[str, Any], event: dict[str, Any]) -> None:
    errors = list(row.get("errors") or [])
    errors.insert(0, {
        "at": event.get("ts_iso") or _now_iso(),
        "type": event.get("type") or "",
        "agent": event.get("agent") or "",
        "message": str(event.get("error") or event.get("message") or "")[:600],
    })
    row["errors"] = errors[:25]


def _approval_delta(event: dict[str, Any]) -> int:
    if event.get("type") == "stack_approval_queue":
        return len(event.get("approval_queue") or [])
    return 1


def _recount_agents(row: dict[str, Any]) -> None:
    agents = row.get("agents") or {}
    statuses = [agent.get("status") for agent in agents.values() if isinstance(agent, dict)]
    row["agent_count"] = len(statuses)
    row["done_agents"] = statuses.count("done")
    row["running_agents"] = statuses.count("running")
    row["error_agents"] = statuses.count("error")


def _set_duration(row: dict[str, Any]) -> None:
    if not row.get("started_at") or not row.get("ended_at"):
        return
    try:
        from datetime import datetime

        start = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(row["ended_at"]).replace("Z", "+00:00"))
        row["duration_seconds"] = max(0, int((end - start).total_seconds()))
    except Exception:
        row["duration_seconds"] = None

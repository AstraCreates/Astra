"""Founder-level continuous company operating goal storage."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _root() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "missions" / "company_goals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _goal_path(founder_id: str) -> Path:
    safe = "".join(ch for ch in founder_id if ch.isalnum() or ch in {"_", "-", "."})[:120] or "founder"
    return _root() / f"{safe}.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_company_goal(founder_id: str) -> dict[str, Any] | None:
    with _lock:
        path = _goal_path(founder_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("company_goal: failed to read %s: %s", path, exc)
            return None


def upsert_company_goal(
    founder_id: str,
    *,
    north_star: str,
    company_goal: str,
    source_session_id: str,
    status: str = "operating",
    kpis: list[dict[str, Any]] | None = None,
    notion_database_id: str | None = None,
    notion_url: str | None = None,
) -> dict[str, Any]:
    with _lock:
        path = _goal_path(founder_id)
        if path.exists():
            try:
                current = json.loads(path.read_text())
            except Exception:
                current = {"founder_id": founder_id, "created_at": _now_iso()}
        else:
            current = {"founder_id": founder_id, "created_at": _now_iso()}
        current.update(
            {
                "founder_id": founder_id,
                "north_star": north_star,
                "company_goal": company_goal,
                "source_session_id": source_session_id,
                "status": status,
                "kpis": list(kpis or []),
                "updated_at": _now_iso(),
            }
        )
        if notion_database_id is not None:
            current["notion_database_id"] = notion_database_id
        if notion_url is not None:
            current["notion_url"] = notion_url
        # Preserve the operating substructure across upserts.
        current.setdefault("root_session_id", "")
        current.setdefault("tasks", [])
        current.setdefault("operating_sessions", [])
        current.setdefault("budget", {"max_runs_per_day": 3, "max_cost_usd_per_run": 1.0})
        current.setdefault("approval_policy", "require_approval")
        path.write_text(json.dumps(current, indent=2, sort_keys=True))
        return current


# ── Internal write helper ───────────────────────────────────────────────────────

def _save(goal: dict[str, Any]) -> dict[str, Any]:
    goal["updated_at"] = _now_iso()
    _goal_path(goal["founder_id"]).write_text(json.dumps(goal, indent=2, sort_keys=True))
    return goal


def _read(founder_id: str) -> dict[str, Any] | None:
    path = _goal_path(founder_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ── Root session + child operating runs ─────────────────────────────────────────

def set_root_session(founder_id: str, session_id: str) -> None:
    """Record the parent launch session every operating run continues from."""
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            return
        # Only set once — the first launch session is the durable parent.
        if not goal.get("root_session_id"):
            goal["root_session_id"] = session_id
            _save(goal)


def add_operating_session(founder_id: str, session_id: str, summary: str = "") -> None:
    """Append a child operating-run record (traceable back to root_session_id)."""
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            return
        runs = goal.setdefault("operating_sessions", [])
        runs.append({
            "session_id": session_id,
            "started_at": _now_iso(),
            "status": "running",
            "summary": summary,
        })
        goal["operating_sessions"] = runs[-50:]
        _save(goal)


def update_operating_session(founder_id: str, session_id: str, **fields: Any) -> None:
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            return
        for rec in goal.get("operating_sessions", []):
            if rec.get("session_id") == session_id:
                rec.update(fields)
                rec["updated_at"] = _now_iso()
                break
        _save(goal)


# ── Unified company task list (milestones the whole team works on) ───────────────

_TASK_OPEN = {"pending", "in_progress", "blocked"}


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    tid = str(task.get("id") or uuid.uuid4())
    return {
        "id": tid,
        "title": str(task.get("title") or tid)[:200],
        "status": str(task.get("status") or "pending"),
        "notes": str(task.get("notes") or "")[:1000],
        "created_at": str(task.get("created_at") or now),
        "updated_at": now,
        "last_run_id": task.get("last_run_id"),
        "approval": task.get("approval"),
    }


def get_tasks(founder_id: str) -> list[dict[str, Any]]:
    goal = _read(founder_id)
    return list(goal.get("tasks") or []) if goal else []


def set_tasks(founder_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            return []
        goal["tasks"] = [_normalize_task(t) for t in tasks]
        _save(goal)
        return goal["tasks"]


def upsert_tasks(founder_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge tasks by id (add new, update existing). Returns the full task list."""
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            return []
        existing = {str(t.get("id")): dict(t) for t in goal.get("tasks") or [] if t.get("id")}
        for task in tasks:
            tid = str(task.get("id") or uuid.uuid4())
            merged = {**existing.get(tid, {}), **task, "id": tid}
            existing[tid] = _normalize_task(merged)
        goal["tasks"] = list(existing.values())
        _save(goal)
        return goal["tasks"]


def update_task(founder_id: str, task_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        goal = _read(founder_id)
        if goal is None:
            raise KeyError(f"No company goal for {founder_id}")
        for idx, t in enumerate(goal.get("tasks") or []):
            if str(t.get("id")) == str(task_id):
                goal["tasks"][idx] = _normalize_task({**t, **fields, "id": str(task_id)})
                _save(goal)
                return goal["tasks"][idx]
        raise KeyError(f"Task not found: {task_id}")


def decide_task(founder_id: str, task_id: str, approved: bool, note: str = "") -> dict[str, Any]:
    """Founder sign-off on a milestone marked awaiting_approval.
    approved → done; rejected → in_progress with the note as feedback."""
    decision = {"approved": approved, "note": note, "at": _now_iso()}
    fields: dict[str, Any] = {"status": "done" if approved else "in_progress", "approval": decision}
    if note:
        verb = "Approved" if approved else "Revisions requested"
        for t in get_tasks(founder_id):
            if str(t.get("id")) == str(task_id):
                fields["notes"] = (t.get("notes", "") + f"\n[{verb}]: {note}").strip()[:1000]
                break
    return update_task(founder_id, task_id, **fields)


def list_company_goals() -> list[dict[str, Any]]:
    """Every founder's company goal (one file each)."""
    out: list[dict[str, Any]] = []
    for path in _root().glob("*.json"):
        try:
            out.append(json.loads(path.read_text()))
        except Exception:
            continue
    return out


def _runs_today(goal: dict[str, Any]) -> int:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(1 for r in goal.get("operating_sessions") or [] if str(r.get("started_at", "")).startswith(today))


def budget_allows(goal: dict[str, Any]) -> bool:
    max_runs = int((goal.get("budget") or {}).get("max_runs_per_day") or 3)
    return _runs_today(goal) < max_runs


def is_due(goal: dict[str, Any], min_interval_seconds: int) -> bool:
    """True if enough time has passed since the last operating run started."""
    runs = goal.get("operating_sessions") or []
    if not runs:
        return True
    last = str(runs[-1].get("started_at") or "")
    try:
        epoch = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except Exception:
        return True
    return (time.time() - epoch) >= min_interval_seconds


def has_open_work(founder_id: str) -> bool:
    return any(str(t.get("status")) in _TASK_OPEN for t in get_tasks(founder_id))


def pending_approvals(founder_id: str) -> list[dict[str, Any]]:
    return [t for t in get_tasks(founder_id) if str(t.get("status")) == "awaiting_approval"]

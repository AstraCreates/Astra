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
        current.setdefault("goals", [])
        current.setdefault("current_goal_id", "")
        current.setdefault("tasks", [])
        current.setdefault("operating_sessions", [])
        current.setdefault("budget", {"max_runs_per_day": 12, "max_cost_usd_per_run": 1.0})
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


# ── Sequential goals (each goal = overall objective + per-workstream major tasks) ──
# A company works one goal at a time. Tasks are owned by specific agents and tick to
# "done" as those agents finish (event-driven, not on a timer). When all non-postponed
# tasks of the current goal are done, the goal is complete → the planner makes the next.

def _new_goal_task(title: str, owner_agents: list[str], notes: str = "") -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(uuid.uuid4()),
        "title": str(title)[:200],
        "status": "pending",
        "owner_agents": [str(a) for a in (owner_agents or [])],
        "done_agents": [],
        "postponed": False,
        "notes": str(notes or "")[:600],
        "created_at": now,
        "updated_at": now,
        "last_run_id": None,
    }


def reset_for_new_launch(founder_id: str, session_id: str, north_star: str, company_goal: str) -> dict[str, Any]:
    """A fresh launch run = a new company → wipe the prior goal/runs and start clean,
    so the /goals view tracks the LATEST session, not a stale earlier one."""
    with _lock:
        data = _read(founder_id) or {"founder_id": founder_id, "created_at": _now_iso()}
        data.update({
            "founder_id": founder_id,
            "north_star": north_star,
            "company_goal": company_goal,
            "source_session_id": session_id,
            "root_session_id": session_id,
            "status": "operating",
            "goals": [],
            "current_goal_id": "",
            "operating_sessions": [],
            "kpis": data.get("kpis") or [],
        })
        data.setdefault("budget", {"max_runs_per_day": 12, "max_cost_usd_per_run": 1.0})
        _save(data)
        return data


def current_goal(founder_id: str) -> dict[str, Any] | None:
    g = _read(founder_id)
    if not g:
        return None
    cid = g.get("current_goal_id")
    for go in g.get("goals") or []:
        if go.get("id") == cid:
            return go
    return None


def get_goals(founder_id: str) -> list[dict[str, Any]]:
    g = _read(founder_id)
    return list(g.get("goals") or []) if g else []


def start_goal(founder_id: str, title: str, tasks: list[dict[str, Any]], kind: str = "planner") -> dict[str, Any] | None:
    """Create a new active goal (marking the prior current goal done) and make it current.
    ``tasks`` items: {title, owner_agents:[...], notes}."""
    with _lock:
        g = _read(founder_id)
        if g is None:
            return None
        for go in g.get("goals") or []:
            if go.get("id") == g.get("current_goal_id") and go.get("status") != "done":
                go["status"] = "done"
                go["completed_at"] = _now_iso()
        goal = {
            "id": str(uuid.uuid4()),
            "title": str(title)[:200],
            "status": "active",
            "kind": kind,
            "tasks": [_new_goal_task(t.get("title", "Task"), t.get("owner_agents") or [], t.get("notes", "")) for t in tasks],
            "created_at": _now_iso(),
            "completed_at": None,
        }
        g.setdefault("goals", []).append(goal)
        g["current_goal_id"] = goal["id"]
        _save(g)
        return goal


def _goal_is_complete(goal: dict[str, Any] | None) -> bool:
    if not goal:
        return False
    actionable = [t for t in goal.get("tasks") or [] if not t.get("postponed")]
    return bool(actionable) and all(t.get("status") == "done" for t in actionable)


def goal_is_complete(founder_id: str) -> bool:
    return _goal_is_complete(current_goal(founder_id))


def complete_agent_workstream(founder_id: str, agent: str, run_id: str = "", summary: str = "") -> dict[str, Any]:
    """Mark ``agent`` as having delivered on the current goal's tasks it owns. A task
    is done once ALL its owner agents have delivered. Returns {changed, goal_complete}."""
    with _lock:
        g = _read(founder_id)
        if g is None:
            return {"changed": False, "goal_complete": False}
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None or cg.get("status") == "done":
            return {"changed": False, "goal_complete": False}
        changed = False
        for t in cg.get("tasks") or []:
            if t.get("postponed"):
                continue
            owners = t.get("owner_agents") or []
            if agent in owners and agent not in t.get("done_agents", []):
                t.setdefault("done_agents", []).append(agent)
                t["updated_at"] = _now_iso()
                t["last_run_id"] = run_id
                if summary:
                    t["notes"] = (t.get("notes", "") + f"\n[{agent}] {summary}").strip()[:1000]
                changed = True
                if all(o in t["done_agents"] for o in owners):
                    t["status"] = "done"
                elif t.get("status") == "pending":
                    t["status"] = "in_progress"
        complete = _goal_is_complete(cg)
        if complete and cg.get("status") != "done":
            cg["status"] = "done"
            cg["completed_at"] = _now_iso()
        if changed:
            _save(g)
        return {"changed": changed, "goal_complete": complete}


def mark_workstream_running(founder_id: str, agent: str) -> bool:
    """An owner agent started → flip its current-goal task(s) pending → in_progress
    so the goal reads as 'running' the moment a run starts. Returns True if changed."""
    with _lock:
        g = _read(founder_id)
        if g is None:
            return False
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None or cg.get("status") == "done":
            return False
        changed = False
        for t in cg.get("tasks") or []:
            if t.get("postponed") or t.get("status") != "pending":
                continue
            if agent in (t.get("owner_agents") or []):
                t["status"] = "in_progress"
                t["updated_at"] = _now_iso()
                changed = True
        if changed:
            _save(g)
        return changed


def postpone_task(founder_id: str, task_id: str, postponed: bool = True) -> dict[str, Any]:
    with _lock:
        g = _read(founder_id)
        if g is None:
            raise KeyError("no company goal")
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None:
            raise KeyError("no current goal")
        for t in cg.get("tasks") or []:
            if str(t.get("id")) == str(task_id):
                t["postponed"] = bool(postponed)
                t["updated_at"] = _now_iso()
                # Postponing the last blocker can complete the goal.
                if _goal_is_complete(cg) and cg.get("status") != "done":
                    cg["status"] = "done"
                    cg["completed_at"] = _now_iso()
                _save(g)
                return t
        raise KeyError(f"task not found: {task_id}")


def set_goal_task_status(founder_id: str, task_id: str, status: str) -> dict[str, Any]:
    with _lock:
        g = _read(founder_id)
        if g is None:
            raise KeyError("no company goal")
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None:
            raise KeyError("no current goal")
        for t in cg.get("tasks") or []:
            if str(t.get("id")) == str(task_id):
                t["status"] = status
                t["updated_at"] = _now_iso()
                if status == "done":
                    t["done_agents"] = list(t.get("owner_agents") or [])
                if _goal_is_complete(cg) and cg.get("status") != "done":
                    cg["status"] = "done"
                    cg["completed_at"] = _now_iso()
                _save(g)
                return t
        raise KeyError(f"task not found: {task_id}")


def delete_company_goal(founder_id: str) -> bool:
    with _lock:
        path = _goal_path(founder_id)
        if path.exists():
            path.unlink()
            logger.info("company_goal: deleted goal for %s", founder_id)
            return True
        return False


def handle_session_deleted(session_id: str) -> dict[str, Any]:
    """When a session is deleted, clean up company goals tied to it.

    - If the session is a company goal's launch/source/root session, the whole goal
      is removed (the company it spawned is gone).
    - Otherwise, drop any operating-run record that points at the deleted session.
    Returns a small summary of what changed."""
    if not session_id:
        return {"deleted_goals": 0, "detached_runs": 0}
    deleted = 0
    detached = 0
    for goal in list_company_goals():
        founder_id = goal.get("founder_id")
        if not founder_id:
            continue
        if session_id in (goal.get("root_session_id"), goal.get("source_session_id")):
            if delete_company_goal(founder_id):
                deleted += 1
            continue
        runs = goal.get("operating_sessions") or []
        kept = [r for r in runs if r.get("session_id") != session_id]
        if len(kept) != len(runs):
            with _lock:
                g = _read(founder_id)
                if g is not None:
                    g["operating_sessions"] = [r for r in (g.get("operating_sessions") or []) if r.get("session_id") != session_id]
                    _save(g)
                    detached += 1
    return {"deleted_goals": deleted, "detached_runs": detached}


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
    budget = goal.get("budget") or {}
    max_runs_raw = budget["max_runs_per_day"] if "max_runs_per_day" in budget else 12
    max_runs = max(0, int(max_runs_raw))
    return _runs_today(goal) < max_runs


def chained_goals_today(goal: dict[str, Any]) -> int:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(1 for g in goal.get("goals") or []
               if g.get("kind") == "planner" and str(g.get("created_at", "")).startswith(today))


def chain_allowed(goal: dict[str, Any]) -> bool:
    """Goal completion → chain to the next goal is genuine progress, not a retry, so it
    is gated separately from the per-run budget. Cap chained goals/runs/cost to bound cost."""
    budget = goal.get("budget") or {}
    daily_cap = int(budget["max_chained_goals_per_day"] if "max_chained_goals_per_day" in budget else os.environ.get("ASTRA_MAX_CHAINED_GOALS_PER_DAY", "8"))
    root_cap = int(budget["max_chained_runs_per_root_session"] if "max_chained_runs_per_root_session" in budget else os.environ.get("ASTRA_MAX_CHAINED_RUNS_PER_ROOT_SESSION", "20"))
    cost_cap = float(budget["max_cost_usd_per_run"] if "max_cost_usd_per_run" in budget else os.environ.get("ASTRA_MAX_CHAINED_COST_USD_PER_RUN", "1.0"))
    estimated_cost = float(budget.get("estimated_next_run_cost_usd") or 0.0)
    if chained_goals_today(goal) >= daily_cap:
        return False
    if len(goal.get("operating_sessions") or []) >= root_cap:
        return False
    if estimated_cost and estimated_cost > cost_cap:
        return False
    return True


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

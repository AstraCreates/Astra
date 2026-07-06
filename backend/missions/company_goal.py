"""Company-scoped continuous operating goal storage."""

from __future__ import annotations

import json
import logging
import os
import calendar
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Per-(founder, company) lock — was a single global lock serializing goal/task
# writes for every founder on the platform at once. RLock because a few
# entrypoints call another lock-guarded entrypoint for the same founder while
# already holding it (e.g. handle_session_deleted -> delete_company_goal).
_goal_locks: dict[str, threading.RLock] = {}
_goal_locks_guard = threading.Lock()


def _goal_lock(founder_id: str, company_id: str | None = None) -> threading.RLock:
    key = f"{founder_id}::{company_id}" if company_id and company_id != founder_id else founder_id
    lock = _goal_locks.get(key)
    if lock is None:
        with _goal_locks_guard:
            lock = _goal_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                _goal_locks[key] = lock
    return lock


def _root() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "missions" / "company_goals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: str, fallback: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", "."})[:120] or fallback


def _goal_path(founder_id: str, company_id: str | None = None) -> Path:
    safe_founder = _safe_id(founder_id, "founder")
    resolved_company = company_id or founder_id
    if resolved_company == founder_id:
        return _root() / f"{safe_founder}.json"
    company_dir = _root() / safe_founder
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"{_safe_id(resolved_company, 'company')}.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_company_goal(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    with _goal_lock(founder_id, company_id):
        return _read(founder_id, company_id)


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
    company_id: str | None = None,
) -> dict[str, Any]:
    resolved_company_id = company_id or founder_id
    with _goal_lock(founder_id, company_id):
        path = _goal_path(founder_id, resolved_company_id)
        current = _read(founder_id, resolved_company_id) or {
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "created_at": _now_iso(),
        }
        current.update(
            {
                "founder_id": founder_id,
                "company_id": resolved_company_id,
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
    goal.setdefault("company_id", goal.get("founder_id", ""))
    goal["updated_at"] = _now_iso()
    _goal_path(goal["founder_id"], goal["company_id"]).write_text(json.dumps(goal, indent=2, sort_keys=True))
    return goal


def _read(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    resolved_company_id = company_id or founder_id
    path = _goal_path(founder_id, resolved_company_id)
    if not path.exists():
        return None
    try:
        goal = json.loads(path.read_text())
        goal.setdefault("company_id", resolved_company_id)
        return goal
    except Exception as exc:
        logger.warning("company_goal: failed to read %s: %s", path, exc)
        return None


# ── Root session + child operating runs ─────────────────────────────────────────

def set_root_session(founder_id: str, session_id: str, company_id: str | None = None) -> None:
    """Record the parent launch session every operating run continues from."""
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return
        # Only set once — the first launch session is the durable parent.
        if not goal.get("root_session_id"):
            goal["root_session_id"] = session_id
            _save(goal)


def get_company_name(founder_id: str, company_id: str | None = None) -> str:
    """The company's pinned display name, or '' if none set yet."""
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        return str((goal or {}).get("company_name") or "")


def set_company_name(founder_id: str, company_id: str | None = None, company_name: str = "") -> None:
    """Pin the company's name the FIRST time one is established. Every later run
    reuses it so child/operating runs can't rename the company (the amay → alex →
    WellSync drift). First-write-wins."""
    company_name = (company_name or "").strip()
    if not company_name:
        return
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return
        if not goal.get("company_name"):
            goal["company_name"] = company_name
            _save(goal)


def get_company_repo(founder_id: str, company_id: str | None = None) -> str:
    """The company's pinned product repo_url, or '' if none built yet."""
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        return str((goal or {}).get("repo_url") or "")


def set_company_repo(founder_id: str, company_id: str | None = None, repo_url: str = "") -> None:
    """Pin the company's product repo_url the FIRST time a build produces one.

    Every later build reuses this repo instead of creating a new one, so the
    product is extended in place rather than rebuilt from scratch under a new
    name each run."""
    repo_url = (repo_url or "").strip()
    if not repo_url:
        return
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return
        if not goal.get("repo_url"):
            goal["repo_url"] = repo_url
            _save(goal)


def add_operating_session(
    founder_id: str,
    session_id: str,
    summary: str = "",
    goal_id: str = "",
    company_id: str | None = None,
) -> None:
    """Append a child operating-run record (traceable back to root_session_id).
    ``goal_id`` ties the run to the goal it was dispatched for so the UI can group
    every sub-run under its goal instead of showing a flat, confusing list."""
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return
        runs = goal.setdefault("operating_sessions", [])
        runs.append({
            "session_id": session_id,
            "started_at": _now_iso(),
            "status": "running",
            "summary": summary,
            "goal_id": goal_id or goal.get("current_goal_id", ""),
        })
        goal["operating_sessions"] = runs[-50:]
        _save(goal)


def update_operating_session(
    founder_id: str,
    session_id: str,
    company_id: str | None = None,
    **fields: Any,
) -> None:
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return
        for rec in goal.get("operating_sessions", []):
            if rec.get("session_id") == session_id:
                rec.update(fields)
                rec["updated_at"] = _now_iso()
                break
        _save(goal)


def reconcile_operating_sessions(founder_id: str, company_id: str | None = None) -> int:
    """Flip operating-run records stuck at "running" to a terminal state when the
    underlying session is no longer running (a backend restart killed the run
    mid-dispatch before update_operating_session fired). Returns count fixed."""
    import calendar as _cal
    import os as _os
    import time as _time
    from backend.core.session_store import get_session_meta
    stale_seconds = int(_os.environ.get("ASTRA_RUN_STALE_SECONDS", "14400"))
    now = _time.time()
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return 0
        fixed = 0
        for rec in goal.get("operating_sessions") or []:
            if rec.get("status") != "running":
                continue
            meta = get_session_meta(rec.get("session_id")) or {}
            st = meta.get("status")
            if st in ("done", "error", "killed", "stalled") or not meta:
                rec["status"] = "done" if st == "done" else "error"
                rec["updated_at"] = _now_iso()
                fixed += 1
            elif st == "running":
                # Session index also shows "running" — check if it's a stale zombie.
                # has_active_run() already ignores sessions older than stale_seconds, so
                # if the session index says "running" but the session is past the stale
                # window, the scheduler will dispatch a new run while this record stays
                # "running". Flip it to "error" so the scheduler's done-check works correctly.
                ts = meta.get("created_at") or rec.get("started_at") or ""
                try:
                    epoch = _cal.timegm(_time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
                except Exception:
                    continue
                if (now - epoch) >= stale_seconds:
                    rec["status"] = "error"
                    rec["updated_at"] = _now_iso()
                    fixed += 1
        if fixed:
            _save(goal)
        return fixed


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


def get_tasks(founder_id: str, company_id: str | None = None) -> list[dict[str, Any]]:
    goal = _read(founder_id, company_id)
    return list(goal.get("tasks") or []) if goal else []


def set_tasks(
    founder_id: str,
    tasks: list[dict[str, Any]],
    company_id: str | None = None,
) -> list[dict[str, Any]]:
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            return []
        goal["tasks"] = [_normalize_task(t) for t in tasks]
        _save(goal)
        return goal["tasks"]


def upsert_tasks(
    founder_id: str,
    tasks: list[dict[str, Any]],
    company_id: str | None = None,
) -> list[dict[str, Any]]:
    """Merge tasks by id (add new, update existing). Returns the full task list."""
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
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


def update_task(
    founder_id: str,
    task_id: str,
    company_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    with _goal_lock(founder_id, company_id):
        goal = _read(founder_id, company_id)
        if goal is None:
            raise KeyError(f"No company goal for {founder_id}")
        for idx, t in enumerate(goal.get("tasks") or []):
            if str(t.get("id")) == str(task_id):
                goal["tasks"][idx] = _normalize_task({**t, **fields, "id": str(task_id)})
                _save(goal)
                return goal["tasks"][idx]
        raise KeyError(f"Task not found: {task_id}")


def decide_task(
    founder_id: str,
    task_id: str,
    approved: bool,
    note: str = "",
    company_id: str | None = None,
) -> dict[str, Any]:
    """Founder sign-off on a milestone marked awaiting_approval.
    approved → done; rejected → in_progress with the note as feedback."""
    decision = {"approved": approved, "note": note, "at": _now_iso()}
    fields: dict[str, Any] = {"status": "done" if approved else "in_progress", "approval": decision}
    if note:
        verb = "Approved" if approved else "Revisions requested"
        for t in get_tasks(founder_id, company_id):
            if str(t.get("id")) == str(task_id):
                fields["notes"] = (t.get("notes", "") + f"\n[{verb}]: {note}").strip()[:1000]
                break
    return update_task(founder_id, task_id, company_id=company_id, **fields)


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


def reset_for_new_launch(
    founder_id: str,
    session_id: str,
    north_star: str,
    company_goal: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """A fresh launch run = a new company → wipe the prior goal/runs and start clean,
    so the /goals view tracks the LATEST session, not a stale earlier one."""
    with _goal_lock(founder_id, company_id):
        resolved_company_id = company_id or founder_id
        data = _read(founder_id, resolved_company_id) or {
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "created_at": _now_iso(),
        }
        data.update({
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "north_star": north_star,
            "company_goal": company_goal,
            "source_session_id": session_id,
            "root_session_id": session_id,
            "status": "operating",
            "goals": [],
            "current_goal_id": "",
            "operating_sessions": [],
            "kpis": data.get("kpis") or [],
            # Fresh launch = new company → clear the pinned identity so it re-pins
            # from THIS launch (don't inherit the prior company's name/repo).
            "company_name": "",
            "repo_url": "",
        })
        data.setdefault("budget", {"max_runs_per_day": 12, "max_cost_usd_per_run": 1.0})
        _save(data)
        return data


def current_goal(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    g = _read(founder_id, company_id)
    if not g:
        return None
    cid = g.get("current_goal_id")
    for go in g.get("goals") or []:
        if go.get("id") == cid:
            return go
    return None


def get_goals(founder_id: str, company_id: str | None = None) -> list[dict[str, Any]]:
    g = _read(founder_id, company_id)
    return list(g.get("goals") or []) if g else []


def start_goal(
    founder_id: str,
    title: str,
    tasks: list[dict[str, Any]],
    kind: str = "planner",
    status: str = "active",
    company_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a new goal (marking the prior current goal done) and make it current.
    ``tasks`` items: {title, owner_agents:[...], notes}. ``status`` is "active" for the
    launch goal (runs immediately) or "proposed" for planner-chained goals (the founder
    must approve before the team works it — goals need human sign-off)."""
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
        if g is None:
            return None
        for go in g.get("goals") or []:
            if go.get("id") == g.get("current_goal_id") and go.get("status") not in ("done", "proposed"):
                go["status"] = "done"
                go["completed_at"] = _now_iso()
                # Settle any tasks that weren't explicitly completed — goal is advancing,
                # so open tasks are auto-closed so the checklist doesn't show them as pending.
                for t in go.get("tasks") or []:
                    if not t.get("postponed") and t.get("status") != "done":
                        t["status"] = "done"
                        t.setdefault("done_agents", list(t.get("owner_agents") or []))
                        t["updated_at"] = _now_iso()
        goal = {
            "id": str(uuid.uuid4()),
            "title": str(title)[:200],
            "status": status,
            "kind": kind,
            "tasks": [_new_goal_task(t.get("title", "Task"), t.get("owner_agents") or [], t.get("notes", "")) for t in tasks],
            "created_at": _now_iso(),
            "completed_at": None,
        }
        g.setdefault("goals", []).append(goal)
        g["current_goal_id"] = goal["id"]
        _save(g)
        return goal


def approve_current_goal(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    """Founder sign-off on a proposed next goal → flip it active so it can be dispatched.
    Returns the now-active goal, or None if there's nothing proposed."""
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
        if g is None:
            return None
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None or cg.get("status") != "proposed":
            return None
        cg["status"] = "active"
        cg["approved_at"] = _now_iso()
        _save(g)
        return cg


def reject_current_goal(founder_id: str, company_id: str | None = None) -> bool:
    """Founder rejects the proposed next goal → drop it; the planner can propose another.
    Restores the most recent done goal as current so the view isn't empty."""
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
        if g is None:
            return False
        goals = g.get("goals") or []
        cg = next((go for go in goals if go.get("id") == g.get("current_goal_id")), None)
        if cg is None or cg.get("status") != "proposed":
            return False
        g["goals"] = [go for go in goals if go.get("id") != cg.get("id")]
        done = [go for go in g["goals"] if go.get("status") == "done"]
        g["current_goal_id"] = done[-1]["id"] if done else ""
        _save(g)
        return True


def _goal_is_complete(goal: dict[str, Any] | None) -> bool:
    if not goal:
        return False
    all_tasks = goal.get("tasks") or []
    if not all_tasks:
        return False
    # A goal is complete when every task is settled: done or postponed.
    # Requiring at least one "done" task caused deadlocks when the safety-net
    # auto-postponed tasks that needed unattainable evidence (e.g. signup_url).
    return all(t.get("status") == "done" or t.get("postponed") for t in all_tasks)


def goal_is_complete(founder_id: str, company_id: str | None = None) -> bool:
    return _goal_is_complete(current_goal(founder_id, company_id))


def complete_agent_workstream(
    founder_id: str,
    agent: str,
    run_id: str = "",
    summary: str = "",
    company_id: str | None = None,
    task_ids: "set[str] | None" = None,
) -> dict[str, Any]:
    """Mark ``agent`` as having delivered on the current goal's tasks it owns. A task
    is done once ALL its owner agents have delivered. Returns {changed, goal_complete}.
    ``task_ids``: if provided, only process these task IDs (for per-task evidence gating)."""
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
        if g is None:
            return {"changed": False, "goal_complete": False}
        cg = next((go for go in g.get("goals") or [] if go.get("id") == g.get("current_goal_id")), None)
        if cg is None or cg.get("status") == "done":
            return {"changed": False, "goal_complete": False}
        changed = False
        for t in cg.get("tasks") or []:
            if t.get("postponed"):
                continue
            if task_ids is not None and str(t.get("id", "")) not in task_ids:
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


def mark_workstream_running(
    founder_id: str,
    agent: str,
    company_id: str | None = None,
) -> bool:
    """An owner agent started → flip its current-goal task(s) pending → in_progress
    so the goal reads as 'running' the moment a run starts. Returns True if changed."""
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
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


def postpone_task(
    founder_id: str,
    task_id: str,
    postponed: bool = True,
    company_id: str | None = None,
) -> dict[str, Any]:
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
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


def set_goal_task_status(
    founder_id: str,
    task_id: str,
    status: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    with _goal_lock(founder_id, company_id):
        g = _read(founder_id, company_id)
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


def delete_company_goal(founder_id: str, company_id: str | None = None) -> bool:
    with _goal_lock(founder_id, company_id):
        path = _goal_path(founder_id, company_id)
        if path.exists():
            path.unlink()
            logger.info("company_goal: deleted goal for %s company=%s", founder_id, company_id or founder_id)
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
        company_id = goal.get("company_id") or founder_id
        if not founder_id:
            continue
        if session_id in (goal.get("root_session_id"), goal.get("source_session_id")):
            if delete_company_goal(founder_id, company_id):
                deleted += 1
            continue
        runs = goal.get("operating_sessions") or []
        deleted_run = next((r for r in runs if r.get("session_id") == session_id), None)
        kept = [r for r in runs if r.get("session_id") != session_id]
        if len(kept) != len(runs):
            with _goal_lock(founder_id, company_id):
                g = _read(founder_id, company_id)
                if g is not None:
                    g["operating_sessions"] = [r for r in (g.get("operating_sessions") or []) if r.get("session_id") != session_id]
                    # Reset any tasks that are stuck "in_progress" for the deleted run's
                    # goal back to "pending" — the agent ran but the session is gone,
                    # so those tasks would otherwise be frozen forever and the checklist
                    # would never update.
                    goal_id = (deleted_run or {}).get("goal_id", "")
                    cg = next((go for go in g.get("goals") or [] if go.get("id") == goal_id), None) if goal_id else None
                    if cg and cg.get("status") not in ("done",):
                        changed_tasks = False
                        for t in cg.get("tasks") or []:
                            if t.get("status") == "in_progress" and not t.get("done_agents"):
                                t["status"] = "pending"
                                changed_tasks = True
                    _save(g)
                    detached += 1
    # Purge brain records and vault notes written during this session
    try:
        from backend.tools.company_brain import purge_session_records
        from backend.tools.obsidian_logger import delete_session_notes
        # Best-effort: try each founder that had a goal tied to this session
        seen_founders: set[str] = set()
        for goal in list_company_goals():
            fid = goal.get("founder_id")
            if fid and fid not in seen_founders:
                purge_session_records(fid, session_id)
                seen_founders.add(fid)
        delete_session_notes(session_id)
    except Exception as _ce:
        import logging as _log
        _log.getLogger(__name__).warning("brain/vault cleanup failed session=%s: %s", session_id, _ce)

    return {"deleted_goals": deleted, "detached_runs": detached}


def sweep_stale_tasks(founder_id: str, company_id: str | None = None) -> bool:
    """Reset tasks stuck "in_progress" with no done_agents back to "pending" when no
    operating session is actively running for that goal. Called on each GET so the
    checklist/GoalPanel self-heal after sessions terminate without delivering.
    Returns True if any tasks were reset."""
    from backend.core.session_store import get_session_meta
    g = _read(founder_id, company_id)
    if g is None:
        return False
    cid = g.get("current_goal_id", "")
    cg = next((go for go in g.get("goals") or [] if go.get("id") == cid), None)
    if not cg or cg.get("status") in ("done", "proposed"):
        return False
    # Check if any operating session for this goal is actively running.
    running_sids = set()
    for r in g.get("operating_sessions") or []:
        if r.get("goal_id") != cid:
            continue
        sid = r.get("session_id", "")
        if not sid:
            continue
        meta = get_session_meta(sid) or {}
        if meta.get("status") not in ("done", "error", "killed", "stalled"):
            running_sids.add(sid)
    if running_sids:
        return False  # active session running — don't touch tasks
    changed = False
    with _goal_lock(founder_id, company_id):
        g2 = _read(founder_id, company_id)
        if g2 is None:
            return False
        cg2 = next((go for go in g2.get("goals") or [] if go.get("id") == cid), None)
        if not cg2 or cg2.get("status") in ("done", "proposed"):
            return False
        for t in cg2.get("tasks") or []:
            if t.get("status") == "in_progress":
                # Reset to pending regardless of done_agents — keeps done_agents intact so
                # already-completed sub-agents don't re-run on the next dispatch.
                t["status"] = "pending"
                changed = True
        if changed:
            _save(g2)
    return changed


def goal_credits(founder_id: str, company_id: str | None = None) -> dict[str, int]:
    """Credits spent per goal: sum each goal's sessions' durable credit tallies. A
    planner goal's spend = its operating sub-runs; the launch goal also counts the root
    (launch) session it ran in. Returns {goal_id: credits}."""
    from backend.core.session_store import get_session_credits
    g = _read(founder_id, company_id)
    if not g:
        return {}
    out: dict[str, int] = {}
    runs_by_goal: dict[str, list[str]] = {}
    for r in g.get("operating_sessions") or []:
        gid = r.get("goal_id")
        if gid and r.get("session_id"):
            runs_by_goal.setdefault(gid, []).append(r["session_id"])
    root = g.get("root_session_id") or ""
    for go in g.get("goals") or []:
        gid = go.get("id")
        total = sum(get_session_credits(sid) for sid in runs_by_goal.get(gid, []))
        if go.get("kind") == "launch" and root:
            total += get_session_credits(root)
        out[gid] = total
    return out


def list_company_goals() -> list[dict[str, Any]]:
    """Every company goal, including legacy founder-default records."""
    out: list[dict[str, Any]] = []
    for path in _root().rglob("*.json"):
        try:
            out.append(json.loads(path.read_text()))
        except Exception:
            continue
    return out


def _runs_today(goal: dict[str, Any]) -> int:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(1 for r in goal.get("operating_sessions") or [] if str(r.get("started_at", "")).startswith(today))


def _parse_iso_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(calendar.timegm(time.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None


def _current_root_window_start(goal: dict[str, Any]) -> float | None:
    root_sid = str(goal.get("root_session_id") or goal.get("source_session_id") or "")
    if root_sid:
        try:
            from backend.core.session_store import get_session_meta
            root_meta = get_session_meta(root_sid) or {}
            parsed = _parse_iso_epoch(root_meta.get("created_at"))
            if parsed is not None:
                return parsed
        except Exception:
            pass
    launch_times = [
        parsed for parsed in (
            _parse_iso_epoch(g.get("created_at"))
            for g in (goal.get("goals") or [])
            if g.get("kind") == "launch"
        )
        if parsed is not None
    ]
    if launch_times:
        return max(launch_times)
    return _parse_iso_epoch(goal.get("created_at"))


def _runs_in_current_root_window(goal: dict[str, Any]) -> int:
    """Count retained operating runs that belong to the current launch/root window.

    Older records can survive migrations or partial resets. They should not wedge a
    fresh company forever, but malformed timestamps are counted conservatively.
    """
    runs = goal.get("operating_sessions") or []
    window_start = _current_root_window_start(goal)
    if window_start is None:
        return len(runs)
    scoped = 0
    for rec in runs:
        started = _parse_iso_epoch(rec.get("started_at"))
        if started is None or started >= window_start:
            scoped += 1
    return scoped


def budget_allows(goal: dict[str, Any]) -> bool:
    budget = goal.get("budget") or {}
    max_runs_raw = budget["max_runs_per_day"] if "max_runs_per_day" in budget else 12
    max_runs = max(0, int(max_runs_raw))
    if _runs_today(goal) >= max_runs:
        return False
    root_cap_raw = budget.get("max_chained_runs_per_root_session")
    if root_cap_raw is not None and _runs_in_current_root_window(goal) >= max(0, int(root_cap_raw)):
        return False
    return True


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
    if _runs_in_current_root_window(goal) >= root_cap:
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


def has_open_work(founder_id: str, company_id: str | None = None) -> bool:
    return any(str(t.get("status")) in _TASK_OPEN for t in get_tasks(founder_id, company_id))


def pending_approvals(founder_id: str, company_id: str | None = None) -> list[dict[str, Any]]:
    return [
        task
        for task in get_tasks(founder_id, company_id)
        if str(task.get("status")) == "awaiting_approval"
    ]

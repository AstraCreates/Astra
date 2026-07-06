"""Durable mission store.

Every mission gets a file in the persistent Docker volume:
  /data/astra_docs/missions/{founder_id}/{mission_id}.json

A global index is maintained at:
  /data/astra_docs/missions/index.json

Missions survive backend restarts indefinitely (no TTL, no cap).
All reads and writes are protected by per-founder RLocks instead of one global
lock, so unrelated founders do not serialize through the same mutex.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_mission_locks: dict[str, threading.RLock] = {}
_mission_locks_guard = threading.Lock()


def _mission_lock(founder_id: str) -> threading.RLock:
    lock = _mission_locks.get(founder_id)
    if lock is None:
        with _mission_locks_guard:
            lock = _mission_locks.get(founder_id)
            if lock is None:
                lock = threading.RLock()
                _mission_locks[founder_id] = lock
    return lock

DepartmentType = Literal["research", "marketing", "sales", "technical", "legal", "ops", "finance"]
StatusType = Literal["active", "paused", "completed"]
ApprovalPolicyType = Literal["auto", "require_approval"]
# "awaiting_approval": the agent finished the work and is waiting for the founder
# to sign off before it counts as "done". Goals/milestones are not complete until a
# human approves them.
TaskStatusType = Literal["pending", "in_progress", "awaiting_approval", "done", "blocked"]


# ── Paths ──────────────────────────────────────────────────────────────────────

def _root() -> Path:
    """Return the missions root directory, creating it if needed."""
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "missions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mission_dir(founder_id: str) -> Path:
    """Return the per-founder directory, creating it if needed."""
    d = _root() / founder_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mission_path(founder_id: str, mission_id: str) -> Path:
    """Absolute path to a mission's JSON file."""
    return _mission_dir(founder_id) / f"{mission_id}.json"


def _index_path() -> Path:
    """Absolute path to the global mission index."""
    return _root() / "index.json"


# ── Index helpers ──────────────────────────────────────────────────────────────

def _load_index() -> dict[str, Any]:
    """Load the global index from disk. Returns empty dict on any error."""
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_index(index: dict[str, Any]) -> None:
    """Persist the global index to disk."""
    _index_path().write_text(json.dumps(index, indent=2, sort_keys=True))


def _index_entry(mission: dict) -> dict:
    """Extract the lightweight fields stored in the index."""
    return {
        "id": mission["id"],
        "founder_id": mission["founder_id"],
        "company_id": mission.get("company_id") or mission["founder_id"],
        "department": mission["department"],
        "name": mission["name"],
        "status": mission["status"],
        "created_at": mission["created_at"],
        "last_run_at": mission["last_run_at"],
        "run_count": mission["run_count"],
    }


def _mission_founder_id(mission_id: str) -> str | None:
    entry = _load_index().get(mission_id)
    if not entry:
        return None
    return entry.get("founder_id")


# ── Mission file helpers ───────────────────────────────────────────────────────

def _load_mission_file(founder_id: str, mission_id: str) -> dict | None:
    """Read a mission JSON file. Returns None if not found or unreadable."""
    p = _mission_path(founder_id, mission_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        logger.warning("missions.store: failed to read %s: %s", p, exc)
        return None


def _save_mission_file(mission: dict) -> None:
    """Write a mission dict to its JSON file."""
    p = _mission_path(mission["founder_id"], mission["id"])
    p.write_text(json.dumps(mission, indent=2))


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Public API ─────────────────────────────────────────────────────────────────

def create_mission(
    founder_id: str,
    department: DepartmentType,
    name: str,
    goal: str,
    primary_metric: str,
    objectives: list[str],
    budget: dict[str, Any],
    approval_policy: ApprovalPolicyType,
    company_id: str | None = None,
) -> dict:
    """Create a new mission and persist it.

    Args:
        founder_id: The ID of the user who owns this mission.
        department: One of research|marketing|sales|technical|legal|ops|finance.
        name: Human-readable mission name.
        goal: High-level goal statement for the mission agent.
        primary_metric: The KPI the mission is trying to move (e.g. "MRR").
        objectives: Ordered list of sub-objectives the agent should pursue.
        budget: Dict with keys ``max_runs_per_day`` (int) and
            ``max_cost_usd_per_run`` (float).
        approval_policy: ``"auto"`` to run without human sign-off, or
            ``"require_approval"`` to gate each run.

    Returns:
        The newly created mission dict.
    """
    mission: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "founder_id": founder_id,
        "company_id": company_id or founder_id,
        "department": department,
        "name": name,
        "goal": goal,
        "primary_metric": primary_metric,
        "objectives": objectives,
        "budget": budget,
        "approval_policy": approval_policy,
        "status": "active",
        "created_at": _now_iso(),
        "last_run_at": None,
        "run_count": 0,
        "total_cost_usd": 0.0,
        "progress_notes": [],
        "tasks": [],
        "company_goal_id": None,
        "notion_page_id": None,
        "notion_page_url": None,
    }
    with _mission_lock(founder_id):
        _save_mission_file(mission)
        index = _load_index()
        index[mission["id"]] = _index_entry(mission)
        _save_index(index)
    logger.info("missions.store: created mission %s for founder %s", mission["id"], founder_id)
    return mission


def get_mission(mission_id: str) -> dict | None:
    """Fetch a single mission by ID.

    Looks up the founder from the index so callers don't need to supply it.

    Args:
        mission_id: UUID of the mission.

    Returns:
        The full mission dict, or ``None`` if not found.
    """
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        return None
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            return None
        return _load_mission_file(entry["founder_id"], mission_id)


def list_missions(founder_id: str, company_id: str | None = None) -> list[dict]:
    """Return all missions belonging to a founder, newest first.

    Args:
        founder_id: The owner's user ID.

    Returns:
        List of full mission dicts sorted by ``created_at`` descending.
    """
    with _mission_lock(founder_id):
        index = _load_index()
        entries = [e for e in index.values() if e.get("founder_id") == founder_id]

    missions: list[dict] = []
    for entry in entries:
        m = _load_mission_file(founder_id, entry["id"])
        if m is not None and (
            company_id is None
            or str(m.get("company_id") or founder_id) == company_id
        ):
            m.setdefault("company_id", founder_id)
            missions.append(m)

    missions.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return missions


def find_mission(
    founder_id: str,
    department: str,
    name: str,
    company_id: str | None = None,
) -> dict | None:
    normalized_name = (name or "").strip().lower()
    for mission in list_missions(founder_id, company_id):
        if mission.get("department") == department and str(mission.get("name", "")).strip().lower() == normalized_name:
            return mission
    return None


def update_mission(mission_id: str, **fields: Any) -> dict:
    """Update arbitrary top-level fields on a mission.

    Protected fields (``id``, ``founder_id``, ``created_at``) are silently
    ignored to prevent accidental corruption.

    Args:
        mission_id: UUID of the mission to update.
        **fields: Keyword arguments whose keys map to mission fields.

    Returns:
        The updated mission dict.

    Raises:
        KeyError: If the mission is not found.
    """
    _PROTECTED = {"id", "founder_id", "created_at"}
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        for key, value in fields.items():
            if key not in _PROTECTED:
                mission[key] = value
        _save_mission_file(mission)
        index[mission_id] = _index_entry(mission)
        _save_index(index)
    return mission


def _task_now() -> str:
    return _now_iso()


def _normalize_task(task: dict[str, Any], mission: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    timestamp = now or _task_now()
    task_id = str(task.get("id") or uuid.uuid4())
    return {
        "id": task_id,
        "title": str(task.get("title") or task_id),
        "status": str(task.get("status") or "pending"),
        "parent_id": task.get("parent_id"),
        "notes": str(task.get("notes") or ""),
        "owner_agent": str(task.get("owner_agent") or mission.get("department") or ""),
        "created_at": str(task.get("created_at") or timestamp),
        "updated_at": str(task.get("updated_at") or timestamp),
        "last_run_id": task.get("last_run_id"),
        "notion_page_id": task.get("notion_page_id"),
        "notion_page_url": task.get("notion_page_url"),
    }


def list_tasks(mission_id: str) -> list[dict[str, Any]]:
    mission = get_mission(mission_id)
    if mission is None:
        raise KeyError(f"Mission not found: {mission_id}")
    tasks = mission.get("tasks") or []
    return [dict(task) for task in tasks]


def bulk_upsert_tasks(mission_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        existing = {str(task.get("id")): dict(task) for task in mission.get("tasks") or [] if task.get("id")}
        now = _task_now()
        for task in tasks:
            task_id = str(task.get("id") or uuid.uuid4())
            merged = {**existing.get(task_id, {}), **task, "id": task_id}
            if "created_at" not in merged:
                merged["created_at"] = now
            merged["updated_at"] = now
            existing[task_id] = _normalize_task(merged, mission, now)
        mission["tasks"] = list(existing.values())
        _save_mission_file(mission)
        return [dict(task) for task in mission["tasks"]]


def add_task(mission_id: str, task: dict[str, Any]) -> dict[str, Any]:
    created = bulk_upsert_tasks(mission_id, [task])
    target_id = str(task.get("id") or created[-1].get("id"))
    return next(item for item in created if str(item.get("id")) == target_id)


def update_task(mission_id: str, task_id: str, **fields: Any) -> dict[str, Any]:
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        tasks = list(mission.get("tasks") or [])
        now = _task_now()
        for idx, task in enumerate(tasks):
            if str(task.get("id")) != str(task_id):
                continue
            merged = {**task, **fields, "id": str(task_id), "updated_at": now}
            tasks[idx] = _normalize_task(merged, mission, now)
            mission["tasks"] = tasks
            _save_mission_file(mission)
            return dict(tasks[idx])
        raise KeyError(f"Task not found: {task_id}")


def delete_mission(mission_id: str) -> bool:
    """Delete a mission and remove it from the index.

    Args:
        mission_id: UUID of the mission to delete.

    Returns:
        ``True`` if the mission was deleted, ``False`` if it was not found.
    """
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        return False
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            return False
        p = _mission_path(entry["founder_id"], mission_id)
        if p.exists():
            p.unlink()
        del index[mission_id]
        _save_index(index)
    logger.info("missions.store: deleted mission %s", mission_id)
    return True


def append_progress_note(mission_id: str, note: str, run_id: str) -> None:
    """Append a timestamped progress note to a mission.

    Args:
        mission_id: UUID of the target mission.
        note: Free-text note written by the mission agent.
        run_id: Identifier of the agent run that produced this note.

    Raises:
        KeyError: If the mission is not found.
    """
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        mission.setdefault("progress_notes", []).append(
            {"timestamp": _now_iso(), "note": note, "run_id": run_id}
        )
        _save_mission_file(mission)


def decide_task(mission_id: str, task_id: str, approved: bool, note: str = "", decided_by: str = "founder") -> dict[str, Any]:
    """Human decision on a milestone the agent marked awaiting_approval.

    approved=True  → status "done" (the goal/milestone counts as complete).
    approved=False → status "in_progress" with the founder's note as feedback, so
                     the next mission run reworks it.
    """
    now = _task_now()
    decision = {"approved": approved, "note": note, "by": decided_by, "at": now}
    fields = {
        "status": "done" if approved else "in_progress",
        "approval": decision,
    }
    if note:
        verb = "Approved" if approved else "Revisions requested"
        existing_note = ""
        try:
            for t in list_tasks(mission_id):
                if str(t.get("id")) == str(task_id):
                    existing_note = t.get("notes", "")
                    break
        except Exception:
            pass
        fields["notes"] = (existing_note + f"\n[{verb} by {decided_by}]: {note}").strip()
    return update_task(mission_id, task_id, **fields)


def pending_approvals(
    founder_id: str,
    company_id: str | None = None,
) -> list[dict[str, Any]]:
    """Every milestone across the founder's missions that is awaiting human sign-off."""
    out: list[dict[str, Any]] = []
    for mission in list_missions(founder_id, company_id):
        for task in mission.get("tasks") or []:
            if task.get("status") == "awaiting_approval":
                out.append({
                    "mission_id": mission["id"],
                    "mission_name": mission.get("name"),
                    "department": mission.get("department"),
                    "task": dict(task),
                })
    return out


def mission_progress(mission: dict[str, Any]) -> dict[str, int]:
    """Count tasks by status for a mission (UI + completion checks)."""
    counts = {"pending": 0, "in_progress": 0, "awaiting_approval": 0, "done": 0, "blocked": 0}
    for task in mission.get("tasks") or []:
        s = str(task.get("status") or "pending")
        counts[s] = counts.get(s, 0) + 1
    counts["total"] = sum(v for k, v in counts.items() if k != "total")
    return counts


def update_mission_status(mission_id: str, status: StatusType) -> None:
    """Update the status of a mission.

    Args:
        mission_id: UUID of the target mission.
        status: One of ``"active"``, ``"paused"``, or ``"completed"``.

    Raises:
        KeyError: If the mission is not found.
    """
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        mission["status"] = status
        _save_mission_file(mission)
        index[mission_id]["status"] = status
        _save_index(index)


def increment_run_count(mission_id: str, cost_usd: float) -> None:
    """Record that a run completed, updating counters and timestamps.

    Args:
        mission_id: UUID of the target mission.
        cost_usd: Dollar cost of the completed run.

    Raises:
        KeyError: If the mission is not found.
    """
    founder_id = _mission_founder_id(mission_id)
    if not founder_id:
        raise KeyError(f"Mission not found: {mission_id}")
    with _mission_lock(founder_id):
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            raise KeyError(f"Mission not found: {mission_id}")
        mission = _load_mission_file(entry["founder_id"], mission_id)
        if mission is None:
            raise KeyError(f"Mission file missing for: {mission_id}")
        now = _now_iso()
        mission["run_count"] = mission.get("run_count", 0) + 1
        mission["total_cost_usd"] = round(mission.get("total_cost_usd", 0.0) + cost_usd, 6)
        mission["last_run_at"] = now
        _save_mission_file(mission)
        index[mission_id]["run_count"] = mission["run_count"]
        index[mission_id]["last_run_at"] = now
        _save_index(index)


def get_missions_due_for_run() -> list[dict]:
    """Return active missions eligible to run now.

    A mission is due when:
    - ``status == "active"``
    - ``last_run_at`` is ``None``  **or**  older than the minimum re-run interval.

    The interval defaults to 1 hour (``ASTRA_MISSION_MIN_INTERVAL_SECONDS``) so a
    mission can run several times a day up to its ``budget.max_runs_per_day`` cap —
    the budget, not a hard 24h gate, is the real limiter. (The old 24h gate fired
    before the budget ever could, capping every mission at one run/day and making the
    continuous-operating loop barely move.)

    Returns:
        List of full mission dicts that are eligible to be run now.
    """
    min_interval = max(60, int(os.environ.get("ASTRA_MISSION_MIN_INTERVAL_SECONDS", "3600")))
    cutoff_epoch = time.time() - min_interval

    def _parse_epoch(iso: str | None) -> float:
        """Convert an ISO-8601 UTC string to a POSIX timestamp."""
        if iso is None:
            return 0.0
        try:
            t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            return float(time.mktime(t)) - time.timezone
        except Exception:
            return 0.0

    index = _load_index()
    candidates = [
        e for e in index.values()
        if e.get("status") == "active"
        and _parse_epoch(e.get("last_run_at")) <= cutoff_epoch
    ]

    due: list[dict] = []
    for entry in candidates:
        founder_id = entry["founder_id"]
        with _mission_lock(founder_id):
            m = _load_mission_file(founder_id, entry["id"])
        if m is not None and m.get("status") == "active":
            due.append(m)

    return due

"""Durable mission store.

Every mission gets a file in the persistent Docker volume:
  /data/astra_docs/missions/{founder_id}/{mission_id}.json

A global index is maintained at:
  /data/astra_docs/missions/index.json

Missions survive backend restarts indefinitely (no TTL, no cap).
All reads and writes are protected by a single module-level threading.Lock().
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

_lock = threading.Lock()

DepartmentType = Literal["research", "marketing", "sales", "technical", "legal", "ops", "finance"]
StatusType = Literal["active", "paused", "completed"]
ApprovalPolicyType = Literal["auto", "require_approval"]


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
        "department": mission["department"],
        "name": mission["name"],
        "status": mission["status"],
        "created_at": mission["created_at"],
        "last_run_at": mission["last_run_at"],
        "run_count": mission["run_count"],
    }


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
    }
    with _lock:
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
    with _lock:
        index = _load_index()
        entry = index.get(mission_id)
        if not entry:
            return None
        return _load_mission_file(entry["founder_id"], mission_id)


def list_missions(founder_id: str) -> list[dict]:
    """Return all missions belonging to a founder, newest first.

    Args:
        founder_id: The owner's user ID.

    Returns:
        List of full mission dicts sorted by ``created_at`` descending.
    """
    with _lock:
        index = _load_index()
        entries = [e for e in index.values() if e.get("founder_id") == founder_id]

    missions: list[dict] = []
    for entry in entries:
        m = _load_mission_file(founder_id, entry["id"])
        if m is not None:
            missions.append(m)

    missions.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return missions


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
    with _lock:
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


def delete_mission(mission_id: str) -> bool:
    """Delete a mission and remove it from the index.

    Args:
        mission_id: UUID of the mission to delete.

    Returns:
        ``True`` if the mission was deleted, ``False`` if it was not found.
    """
    with _lock:
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
    with _lock:
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


def update_mission_status(mission_id: str, status: StatusType) -> None:
    """Update the status of a mission.

    Args:
        mission_id: UUID of the target mission.
        status: One of ``"active"``, ``"paused"``, or ``"completed"``.

    Raises:
        KeyError: If the mission is not found.
    """
    with _lock:
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
    with _lock:
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
    """Return active missions that have not been run in the last 24 hours.

    A mission is considered due when:
    - ``status == "active"``
    - ``last_run_at`` is ``None``  **or**  more than 86 400 seconds ago.

    Returns:
        List of full mission dicts that are eligible to be run now.
    """
    cutoff_epoch = time.time() - 86_400  # 24 hours ago

    def _parse_epoch(iso: str | None) -> float:
        """Convert an ISO-8601 UTC string to a POSIX timestamp."""
        if iso is None:
            return 0.0
        try:
            t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            return float(time.mktime(t)) - time.timezone
        except Exception:
            return 0.0

    with _lock:
        index = _load_index()
        candidates = [
            e for e in index.values()
            if e.get("status") == "active"
            and _parse_epoch(e.get("last_run_at")) <= cutoff_epoch
        ]

    due: list[dict] = []
    for entry in candidates:
        m = _load_mission_file(entry["founder_id"], entry["id"])
        if m is not None and m.get("status") == "active":
            due.append(m)

    return due

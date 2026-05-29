"""Durable workflow state snapshots.

The event stream is the source of truth while a run is active. This module
condenses that stream into a compact state document that can be persisted and
restored after completion or backend restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.session_digest import build_session_digest
from backend.workboard import build_session_workboard


def _state_root() -> Path:
    root = Path(".astra/workflows")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-", "."})[:120] or "session"
    return _state_root() / f"{safe}.json"


def build_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    event_dicts = [event for _, event in events]
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None)
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    )
    manifest = next(
        (event.get("manifest") for event in reversed(event_dicts) if event.get("type") == "stack_manifest"),
        None,
    )
    genome = next((event.get("genome") for event in reversed(event_dicts) if event.get("type") == "company_genome"), None)
    approvals: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    saferun: dict[str, dict[str, Any]] = {}
    final_status = "running"

    for event in event_dicts:
        event_type = event.get("type")
        if event_type == "stack_approval_queue":
            for item in event.get("approval_queue", []):
                approvals[item.get("key", "")] = item
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            approvals[key] = {**approvals.get(key, {"key": key}), "status": event.get("decision"), "note": event.get("note")}
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            artifacts[artifact.get("key", "")] = artifact
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcomes.append(event["outcome"])
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            saferun[action.get("id", "")] = action
        elif event_type == "saferun_result":
            action_id = event.get("action_id", "")
            saferun[action_id] = {**saferun.get(action_id, {"id": action_id}), **event}
        elif event_type == "goal_done":
            final_status = "done"
        elif event_type == "goal_error":
            final_status = "error"

    return {
        "session_id": session_id,
        "status": final_status,
        "event_count": len(events),
        "last_event_id": events[-1][0] if events else 0,
        "stack": stack,
        "operating_plan": operating_plan,
        "manifest": manifest,
        "company_genome": genome,
        "digest": build_session_digest(session_id, events) if events else None,
        "workboard": build_session_workboard(session_id, events) if events else None,
        "approvals": list(approvals.values()),
        "artifacts": list(artifacts.values()),
        "outcomes": outcomes[-50:],
        "saferun_actions": list(saferun.values())[-50:],
    }


def save_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    state = build_session_state(session_id, events)
    _state_path(session_id).write_text(json.dumps(state, indent=2, sort_keys=True))
    return state


def load_session_state(session_id: str) -> dict[str, Any] | None:
    path = _state_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

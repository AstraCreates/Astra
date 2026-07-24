"""Local-first, event-sourced Company OS storage.

Each company owns a directory under ``workspace/company``.  Snapshots are
atomically replaced; events are append-only JSONL records with content hashes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from backend.core.json_store import cross_process_file_lock, read_json, write_json_atomic

_COLLECTIONS = (
    "initiatives", "squads", "squad_roles", "squad_meetings", "missions", "tasks", "task_attempts",
    "artifacts", "approvals", "conversation", "context_records", "policy_decisions", "mcp_audit",
    "dispatch_audit",
)
_SEGMENT_LIMIT = 250
_SNAPSHOT_INTERVAL = 50
# Notified with company_id after every durable event append. Lets other
# layers (e.g. the route-level TTL cache in company_os_routes.py) invalidate
# themselves without company_os.py importing them back -- that would be
# circular, since every route module already imports from here. Registering
# a listener at the single choke point every mutation passes through also
# means a route added later can't forget to invalidate the cache, which is
# exactly how the read-your-own-write staleness bug happened the first time:
# every route was individually responsible for calling cache_bump(), and
# every route except the approval ones simply didn't.
_mutation_listeners: list[Any] = []


def on_mutation(listener: Any) -> None:
    """Register a ``listener(company_id: str)`` called after every append_event."""
    _mutation_listeners.append(listener)
logger = logging.getLogger(__name__)


def create_company_os(company_id: str, founder_id: str, name: str, *, state: str = "active",
                      root: str | Path | None = None) -> dict[str, Any]:
    """Create a Company OS, returning the existing record if it already exists."""
    directory = _company_dir(company_id, root)
    with _writer_lock(directory):
        existing = _load_snapshot(directory)
        if existing is not None:
            return copy.deepcopy(existing["state"])
        now = _now()
        record = {
            "company_id": company_id, "founder_id": founder_id, "name": name,
            "state": state, "created_at": now, "updated_at": now,
            **{collection: [] for collection in _COLLECTIONS},
        }
        _write_snapshot(directory, record, 0)
        return copy.deepcopy(record)


def ensure_company_operations(company_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Create the standing Operations initiative once, without duplicating it."""
    company = get_company_os(company_id, root=root)
    if company is None:
        raise KeyError(f"unknown company: {company_id}")
    existing = next((item for item in company["initiatives"] if item.get("system_key") == "company_operations"), None)
    if existing:
        _ensure_operations_tasks(company_id, existing["initiative_id"], root=root)
        return existing
    initiative = create_initiative(company_id, "Company Operations", root=root, department="operations", system_key="company_operations")
    squad = create_squad(company_id, initiative["initiative_id"], "Company Operations Squad", root=root, department="operations", lifecycle="formed")
    mission = create_mission(company_id, initiative["initiative_id"], squad["squad_id"], "Maintain recurring company operations", root=root,
                             department="operations", system_key="company_operations")
    _ensure_operations_tasks(company_id, initiative["initiative_id"], root=root, mission=mission, squad=squad)
    return initiative


def _ensure_operations_tasks(company_id: str, initiative_id: str, *, root: str | Path | None,
                             mission: dict[str, Any] | None = None, squad: dict[str, Any] | None = None) -> None:
    state = get_company_os(company_id, root=root) or {}
    mission = mission or next((item for item in state.get("missions", []) if item.get("initiative_id") == initiative_id and item.get("system_key") == "company_operations"), None)
    squad = squad or next((item for item in state.get("squads", []) if item.get("initiative_id") == initiative_id), None)
    if not mission or not squad:
        return
    present = {item.get("name") for item in state.get("tasks", []) if item.get("mission_id") == mission["mission_id"]}
    # These are local, reversible standing checks. The scheduler can run them
    # without creating external side effects, and the board is never a blank shell.
    for name, cadence in (("Review company operating health", 86_400), ("Review pending approvals and blockers", 3_600)):
        if name not in present:
            create_task(company_id, initiative_id, squad["squad_id"], name, root=root,
                        mission_id=mission["mission_id"], department="operations", operation="internal_analysis",
                        cadence_seconds=cadence, state="scheduled", recurring=True)


def get_company_os(company_id: str, *, root: str | Path | None = None) -> dict[str, Any] | None:
    """Return the current materialized Company OS, or ``None`` when unknown."""
    directory = _company_dir(company_id, root)
    if not directory.exists():
        return None
    with _writer_lock(directory):
        loaded = _load_snapshot(directory)
        if loaded is None:
            return None
        state, _ = _replay(directory, loaded)
        return state


def company_recovery_lock(company_id: str, *, root: str | Path | None = None):
    """Return the cross-worker lock used while recovering one company."""
    return cross_process_file_lock(_company_dir(company_id, root) / ".recovery.lock")


def list_company_os(founder_id: str | None = None, *, root: str | Path | None = None) -> list[dict[str, Any]]:
    base = _root(root)
    if not base.exists():
        return []
    records = [get_company_os(path.name, root=base) for path in base.iterdir() if path.is_dir()]
    return [record for record in records if record and (founder_id is None or record["founder_id"] == founder_id)]


def append_event(company_id: str, event_type: str | dict[str, Any], payload: dict[str, Any] | None = None,
                 *, root: str | Path | None = None, **fields: Any) -> dict[str, Any]:
    """Append a checksummed domain event and return its stored envelope."""
    directory = _require_company(company_id, root)
    if isinstance(event_type, dict):
        payload = dict(event_type)
        event_type = str(payload.pop("type", ""))
    payload = {**(payload or {}), **fields}
    if not event_type:
        raise ValueError("event_type is required")
    with _writer_lock(directory):
        loaded = _load_snapshot(directory)
        assert loaded is not None
        state, last_sequence = _replay(directory, loaded)
        event = {"sequence": last_sequence + 1, "type": event_type, "payload": payload, "at": _now()}
        _apply_event(state, event)
        event["checksum"] = _checksum(event)
        _append_line(_active_segment(directory), event)
        if event["sequence"] % _SNAPSHOT_INTERVAL == 0:
            # `state` is already fully materialized post-event, so advancing
            # the snapshot here is free and keeps every future _replay() to a
            # short tail instead of the whole event log (was O(total events)
            # on every read, 26k+ events -> 100s+ per GET /os).
            _write_snapshot(directory, state, event["sequence"])
        result = copy.deepcopy(event)
    for listener in _mutation_listeners:
        try:
            listener(company_id)
        except Exception:
            logger.warning("Company OS mutation listener failed company=%s", company_id, exc_info=True)
    return result


def replay_events(company_id: str, *, root: str | Path | None = None) -> list[dict[str, Any]]:
    """Validate and return events newer than the persisted snapshot."""
    directory = _require_company(company_id, root)
    with _writer_lock(directory):
        loaded = _load_snapshot(directory)
        assert loaded is not None
        return list(_events_after(directory, int(loaded["last_sequence"])))


def snapshot(company_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Materialize and atomically persist the current Company OS snapshot."""
    directory = _require_company(company_id, root)
    with _writer_lock(directory):
        loaded = _load_snapshot(directory)
        assert loaded is not None
        state, sequence = _replay(directory, loaded)
        _write_snapshot(directory, state, sequence)
        return copy.deepcopy(state)


def compact(company_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Persist a snapshot then remove fully represented event segments."""
    directory = _require_company(company_id, root)
    with _writer_lock(directory):
        loaded = _load_snapshot(directory)
        assert loaded is not None
        state, sequence = _replay(directory, loaded)
        _write_snapshot(directory, state, sequence)
        for segment in _segments(directory):
            segment.unlink(missing_ok=True)
        return copy.deepcopy(state)


def create_initiative(company_id: str, name: str, *, initiative_id: str | None = None,
                      state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    # An initiative is the durable strategic workspace; keep its brief and
    # acceptance contract explicit instead of inferring them from task names.
    defaults = {
        "objective": name, "success_criteria": [], "priority": "normal", "owner": "copilot",
        "budget": {}, "due_date": None, "director": data.get("department", "operations"),
        "roadmap": [], "dependencies": [], "decisions": [], "state": state,
    }
    return _create(company_id, "initiative", {"initiative_id": initiative_id or _id("initiative"), "name": name, **defaults, **data}, root)


def create_squad(company_id: str, initiative_id: str, name: str, *, squad_id: str | None = None,
                 state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    defaults = {"role_ids": [], "meeting_ids": []}
    return _create(company_id, "squad", {"squad_id": squad_id or _id("squad"), "initiative_id": initiative_id, "name": name, "state": state, **defaults, **data}, root)


def create_squad_role(company_id: str, squad_id: str, name: str, *, role_id: str | None = None,
                      state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    """Create a durable role that can be assigned only within its squad."""
    defaults = {"task_ids": []}
    return _create(company_id, "squad_role", {"role_id": role_id or _id("role"), "squad_id": squad_id,
                                                "name": name, "state": state, **defaults, **data}, root)


def create_squad_meeting(company_id: str, squad_id: str, name: str, *, meeting_id: str | None = None,
                         state: str = "scheduled", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    """Create a squad-scoped meeting with role participants."""
    defaults = {"participant_role_ids": [], "task_ids": []}
    return _create(company_id, "squad_meeting", {"meeting_id": meeting_id or _id("meeting"), "squad_id": squad_id,
                                                   "name": name, "state": state, **defaults, **data}, root)


def create_mission(company_id: str, initiative_id: str, squad_id: str, name: str, *, mission_id: str | None = None,
                   state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "mission", {"mission_id": mission_id or _id("mission"), "initiative_id": initiative_id, "squad_id": squad_id, "name": name, "state": state, **data}, root)


def create_task(company_id: str, initiative_id: str, squad_id: str, name: str, *, task_id: str | None = None,
                mission_id: str | None = None, state: str = "pending", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    defaults = {"role_id": None, "meeting_id": None, "depends_on_task_ids": []}
    return _create(company_id, "task", {"task_id": task_id or _id("task"), "initiative_id": initiative_id, "squad_id": squad_id, "mission_id": mission_id, "name": name, "state": state, **defaults, **data}, root)


def create_task_attempt(company_id: str, task_id: str, *, attempt_id: str | None = None,
                        state: str = "started", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "task_attempt", {"attempt_id": attempt_id or _id("attempt"), "task_id": task_id, "state": state, **data}, root)


def create_artifact(company_id: str, name: str, *, artifact_id: str | None = None,
                    root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    """Mirrors to the Library unless created already-archived. The Library has
    no archived/hidden concept of its own (a file exists or it's deleted), so
    mirroring an internal, working-material artifact (e.g. a research
    mission's raw evidence and mid-pipeline synthesis note) would leave it
    permanently visible there even though it's intentionally hidden from the
    Company OS artifacts rail -- founders were seeing 3 downloadable files
    per research request instead of the one they actually asked for."""
    resolved_id = artifact_id or _id("artifact")
    # Artifacts inherit their initiative through the producing task, making
    # the initiative workspace the single place to review every outcome.
    if not data.get("initiative_id") and data.get("task_id"):
        company = get_company_os(company_id, root=root) or {}
        task = next((item for item in company.get("tasks", []) if item.get("task_id") == data.get("task_id")), None)
        if task and task.get("initiative_id"):
            data["initiative_id"] = task["initiative_id"]
    library_file_id = data.get("library_file_id")
    if not library_file_id and data.get("state") != "archived":
        library_file_id = _mirror_artifact_to_library(company_id, resolved_id, name, data, root=root)
    payload = {"artifact_id": resolved_id, "name": name, **data}
    if library_file_id:
        payload["library_file_id"] = library_file_id
    return _create(company_id, "artifact", payload, root)


def create_approval(company_id: str, title: str, *, approval_id: str | None = None,
                    task_id: str | None = None, state: str = "pending",
                    root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "approval", {"approval_id": approval_id or _id("approval"), "title": title,
                                               "task_id": task_id, "state": state, **data}, root)


def update_approval(company_id: str, approval_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "approval", "approval_id", approval_id, changes, root)


def update_initiative(company_id: str, initiative_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist an initiative lifecycle transition (e.g. state="archived" for a
    founder-requested delete -- soft, matching every other entity's pattern in
    this event-sourced store; nothing is ever physically removed from history)."""
    return _update(company_id, "initiative", "initiative_id", initiative_id, changes, root)


def reconcile_initiatives(company_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Persist derived initiative rollups without treating an empty task list as done.

    This is deliberately callable after asynchronous task transitions and at
    recovery boundaries. Founder-authored archive state always wins.

    Returns the freshly materialized company state (with any derived changes
    already applied in-place) so callers don't need a second full replay just
    to read back what they already computed here.
    """
    company = get_company_os(company_id, root=root) or {}
    changes: dict[str, dict[str, Any]] = {}
    terminal = {"done", "complete", "completed", "archived", "cancelled"}
    for initiative in company.get("initiatives", []):
        if initiative.get("state") == "archived":
            continue
        initiative_id = initiative["initiative_id"]
        missions = [item for item in company.get("missions", []) if item.get("initiative_id") == initiative_id]
        tasks = [item for item in company.get("tasks", []) if item.get("initiative_id") == initiative_id]
        approvals = [item for item in company.get("approvals", []) if item.get("state") == "pending" and any(task.get("task_id") == item.get("task_id") for task in tasks)]
        complete = sum(1 for task in tasks if task.get("state") in terminal)
        progress = round(complete / len(tasks) * 100) if tasks else 0
        states = {str(item.get("state", "")) for item in missions + tasks}
        criteria = initiative.get("success_criteria") or []
        criteria_met = bool(initiative.get("acceptance_confirmed")) if criteria else bool(missions or tasks)
        if approvals or "waiting" in states or "awaiting_approval" in states:
            state = "review"
        elif any(value in states for value in ("working", "active", "pending", "scheduled")):
            state = "working"
        elif missions and all(item.get("state") in terminal for item in missions) and criteria_met:
            state = "done"
        elif tasks or missions:
            state = "planned"
        else:
            state = "planned"
        derived = {"state": state, "progress": progress, "squad_count": len({item.get("squad_id") for item in missions}), "pending_approval_count": len(approvals)}
        if any(initiative.get(key) != value for key, value in derived.items()):
            update_initiative(company_id, initiative_id, root=root, **derived)
            initiative.update(derived)
            changes[initiative_id] = derived
    return company


def update_task(company_id: str, task_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "task", "task_id", task_id, changes, root)


def update_squad(company_id: str, squad_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist a squad lifecycle transition without mutating the snapshot directly."""
    return _update(company_id, "squad", "squad_id", squad_id, changes, root)


def update_squad_role(company_id: str, role_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "squad_role", "role_id", role_id, changes, root)


def update_squad_meeting(company_id: str, meeting_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "squad_meeting", "meeting_id", meeting_id, changes, root)


def update_mission(company_id: str, mission_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist a mission lifecycle transition without mutating the snapshot directly."""
    return _update(company_id, "mission", "mission_id", mission_id, changes, root)


def add_task_dependency(company_id: str, task_id: str, depends_on_task_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Add one prerequisite to a task, preserving the task graph's invariants."""
    company = get_company_os(company_id, root=root)
    if company is None:
        raise KeyError(f"unknown company: {company_id}")
    task = _must_find(company, "tasks", "task_id", task_id)
    dependencies = list(task.get("depends_on_task_ids") or [])
    if depends_on_task_id not in dependencies:
        dependencies.append(depends_on_task_id)
    return update_task(company_id, task_id, root=root, depends_on_task_ids=dependencies)


def update_task_attempt(company_id: str, attempt_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "task_attempt", "attempt_id", attempt_id, changes, root)


def update_artifact(company_id: str, artifact_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "artifact", "artifact_id", artifact_id, changes, root)


def append_message(company_id: str, message: str, *, scope: str = "company", scope_id: str | None = None,
                   author: str | None = None, root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "message", {"message_id": _id("message"), "message": message, "scope": scope, "scope_id": scope_id, "author": author, **data}, root)


def update_message(company_id: str, message_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist a message edit or soft-delete (archived=True), same append-only
    pattern as every other entity -- _apply_event already replays message.updated
    events into the conversation list, so no new event kind is needed here."""
    return _update(company_id, "message", "message_id", message_id, changes, root)


def add_context_record(company_id: str, key: str, value: Any, *, scope: str = "company", scope_id: str | None = None,
                       root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    _validate_scope(scope, scope_id)
    defaults = {"version": 1, "provenance": "local", "author": "copilot", "confidence": 1.0,
                "source_references": [], "supersedes": None, "canonical": scope == "company", "promoted_revision": False}
    return _create(company_id, "context_record", {"context_id": _id("context"), "key": key, "value": value,
                                                     "scope": scope, "scope_id": scope_id, **defaults, **data}, root)


def resolve_context(company_id: str, *, initiative_id: str | None = None, squad_id: str | None = None,
                    meeting_id: str | None = None, task_id: str | None = None,
                    root: str | Path | None = None) -> dict[str, Any]:
    """Resolve context by overlaying company -> initiative -> squad -> meeting -> task records."""
    record = get_company_os(company_id, root=root)
    if record is None:
        raise KeyError(f"unknown company: {company_id}")
    if meeting_id is not None:
        meeting = _must_find(record, "squad_meetings", "meeting_id", meeting_id)
        if squad_id is not None and meeting["squad_id"] != squad_id:
            raise ValueError("meeting belongs to a different squad")
        squad_id = squad_id or meeting["squad_id"]
        squad = _must_find(record, "squads", "squad_id", squad_id)
        if initiative_id is not None and squad["initiative_id"] != initiative_id:
            raise ValueError("meeting belongs to a different initiative")
        initiative_id = initiative_id or squad["initiative_id"]
    targets = [("company", None), ("initiative", initiative_id), ("squad", squad_id), ("meeting", meeting_id), ("task", task_id)]
    resolved: dict[str, Any] = {}
    source_records: dict[str, dict[str, Any]] = {}
    for scope, scope_id in targets:
        for item in record["context_records"]:
            if item["scope"] == scope and item.get("scope_id") == scope_id:
                previous = source_records.get(item["key"])
                # Meetings are read-only consumers of squad context. Their local
                # notes may add facts, but cannot silently replace a squad fact.
                if previous and (previous.get("canonical") or scope == "meeting") and not item.get("promoted_revision"):
                    continue
                resolved[item["key"]] = copy.deepcopy(item["value"])
                source_records[item["key"]] = item
    return resolved


def _create(company_id: str, kind: str, payload: dict[str, Any], root: str | Path | None) -> dict[str, Any]:
    event = append_event(company_id, f"{kind}.created", payload, root=root)
    result = dict(payload)
    result["created_at"] = event["at"]
    return result


def _update(company_id: str, kind: str, key: str, entity_id: str, changes: dict[str, Any], root: str | Path | None) -> dict[str, Any]:
    event = append_event(company_id, f"{kind}.updated", {key: entity_id, "changes": changes}, root=root)
    result = {key: entity_id, **changes, "updated_at": event["at"]}
    return result


def _apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    kind, separator, action = event["type"].partition(".")
    allowed = {"initiative", "squad", "squad_role", "squad_meeting", "mission", "task", "task_attempt", "message", "context_record", "artifact", "approval"}
    if separator != "." or kind not in allowed | {"policy", "mcp", "dispatch"}:
        raise ValueError(f"unsupported Company OS event: {event['type']}")
    if kind == "mcp" and action in {"tool_called", "tool_completed", "tool_failed"}:
        state.setdefault("mcp_audit", []).append({
            "event_type": event["type"],
            **copy.deepcopy(event["payload"]),
            "created_at": event["at"],
        })
        state["updated_at"] = event["at"]
        return
    if kind == "policy" and action in {"decided", "approval_consumed"}:
        state["policy_decisions"].append({
            "event_type": event["type"], **copy.deepcopy(event["payload"]), "created_at": event["at"],
        })
        state["updated_at"] = event["at"]
        return
    if kind == "dispatch" and action == "routed":
        state.setdefault("dispatch_audit", []).append({
            "event_type": event["type"], **copy.deepcopy(event["payload"]), "created_at": event["at"]
        })
        state["updated_at"] = event["at"]
        return
    if action == "updated" and kind in {"initiative", "squad", "squad_role", "squad_meeting", "mission", "task", "task_attempt", "artifact", "message", "approval"}:
        # A durable event log is append-only forever: even after the message
        # edit/delete API routes were pulled back (pending an audit-safe
        # design), any message.updated events already written by that code
        # still have to replay. Rejecting a historical event type here 500s
        # every read for any company whose log contains one -- not just the
        # new API surface, the entire company becomes unreadable.
        key = {"initiative": "initiative_id", "squad": "squad_id", "squad_role": "role_id", "squad_meeting": "meeting_id", "mission": "mission_id", "task": "task_id", "task_attempt": "attempt_id", "artifact": "artifact_id", "message": "message_id", "approval": "approval_id"}[kind]
        collection = {"message": "conversation", "squad_role": "squad_roles", "squad_meeting": "squad_meetings"}.get(kind, f"{kind}s")
        entity = _must_find(state, collection, key, event["payload"][key])
        candidate = {**entity, **copy.deepcopy(event["payload"].get("changes") or {})}
        _validate_entity_scope(state, kind, candidate, replacing_id=event["payload"][key])
        entity.update(copy.deepcopy(event["payload"].get("changes") or {}))
        entity["updated_at"] = event["at"]
        state["updated_at"] = event["at"]
        return
    if action != "created":
        raise ValueError(f"unsupported Company OS event: {event['type']}")
    payload = copy.deepcopy(event["payload"])
    _validate_entity_scope(state, kind, payload)
    collection = {"message": "conversation", "context_record": "context_records", "squad_role": "squad_roles", "squad_meeting": "squad_meetings"}.get(kind, f"{kind}s")
    payload.setdefault("created_at", event["at"])
    state[collection].append(payload)
    state["updated_at"] = event["at"]


def _validate_entity_scope(state: dict[str, Any], kind: str, payload: dict[str, Any], *, replacing_id: str | None = None) -> None:
    if kind == "squad":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
    elif kind == "mission":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
        squad = _must_find(state, "squads", "squad_id", payload["squad_id"])
        if squad["initiative_id"] != payload["initiative_id"]:
            raise ValueError("squad belongs to a different initiative")
    elif kind == "squad_role":
        _must_find(state, "squads", "squad_id", payload["squad_id"])
        if replacing_id is not None:
            for task in state["tasks"]:
                if task.get("role_id") == replacing_id and task.get("squad_id") != payload["squad_id"]:
                    raise ValueError("role belongs to a different squad than an assigned task")
    elif kind == "squad_meeting":
        _must_find(state, "squads", "squad_id", payload["squad_id"])
        _validate_role_ids(state, payload.get("participant_role_ids") or [], payload["squad_id"])
        if replacing_id is not None:
            for task in state["tasks"]:
                if task.get("meeting_id") == replacing_id and task.get("squad_id") != payload["squad_id"]:
                    raise ValueError("meeting belongs to a different squad than a linked task")
    elif kind == "task":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
        squad = _must_find(state, "squads", "squad_id", payload["squad_id"])
        if squad["initiative_id"] != payload["initiative_id"]:
            raise ValueError("squad belongs to a different initiative")
        if payload.get("mission_id"):
            mission = _must_find(state, "missions", "mission_id", payload["mission_id"])
            if mission["squad_id"] != payload["squad_id"]:
                raise ValueError("mission belongs to a different squad")
        if payload.get("role_id"):
            _validate_role_ids(state, [payload["role_id"]], payload["squad_id"])
        if payload.get("meeting_id"):
            meeting = _must_find(state, "squad_meetings", "meeting_id", payload["meeting_id"])
            if meeting["squad_id"] != payload["squad_id"]:
                raise ValueError("meeting belongs to a different squad")
        _validate_task_dependencies(state, payload, replacing_id=replacing_id)
    elif kind == "task_attempt":
        _must_find(state, "tasks", "task_id", payload["task_id"])
    elif kind in {"message", "context_record"}:
        _validate_scope(payload.get("scope", "company"), payload.get("scope_id"), state)


def _validate_scope(scope: str, scope_id: str | None, state: dict[str, Any] | None = None) -> None:
    collections = {"company": None, "initiative": ("initiatives", "initiative_id"), "squad": ("squads", "squad_id"), "meeting": ("squad_meetings", "meeting_id"), "task": ("tasks", "task_id")}
    if scope not in collections or (scope == "company" and scope_id is not None) or (scope != "company" and not scope_id):
        raise ValueError("scope must be company, initiative, squad, meeting, or task with its matching scope_id")
    if state is not None and collections[scope] is not None:
        collection, key = collections[scope]
        _must_find(state, collection, key, scope_id)


def _must_find(state: dict[str, Any], collection: str, key: str, value: str) -> dict[str, Any]:
    for item in state[collection]:
        if item.get(key) == value:
            return item
    raise ValueError(f"unknown {key}: {value}")


def _validate_role_ids(state: dict[str, Any], role_ids: list[str], squad_id: str) -> None:
    for role_id in role_ids:
        role = _must_find(state, "squad_roles", "role_id", role_id)
        if role["squad_id"] != squad_id:
            raise ValueError("role belongs to a different squad")


def _validate_task_dependencies(state: dict[str, Any], task: dict[str, Any], *, replacing_id: str | None) -> None:
    dependencies = task.get("depends_on_task_ids") or []
    if not isinstance(dependencies, list) or len(dependencies) != len(set(dependencies)):
        raise ValueError("depends_on_task_ids must be a list of unique task ids")
    if dependencies and not task.get("mission_id"):
        raise ValueError("task dependencies require a mission")
    task_id = task.get("task_id")
    if task_id in dependencies:
        raise ValueError("task cannot depend on itself")
    tasks = [item for item in state["tasks"] if item.get("task_id") != replacing_id]
    tasks.append(task)
    by_id = {item.get("task_id"): item for item in tasks}
    for dependency_id in dependencies:
        dependency = _must_find({"tasks": tasks}, "tasks", "task_id", dependency_id)
        if dependency.get("mission_id") != task.get("mission_id"):
            raise ValueError("task dependency belongs to a different mission")

    # Dependencies point from a task to its prerequisites. A DFS across the
    # materialized candidate graph makes create and update event replay obey
    # the same cycle rule.
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(current_id: str) -> None:
        if current_id in visiting:
            raise ValueError("task dependencies must be acyclic")
        if current_id in visited:
            return
        visiting.add(current_id)
        for dependency_id in by_id[current_id].get("depends_on_task_ids") or []:
            if dependency_id in by_id:
                visit(dependency_id)
        visiting.remove(current_id)
        visited.add(current_id)
    for current_id in by_id:
        visit(current_id)


def _root(root: str | Path | None) -> Path:
    # Company OS must share the durable workspace volume used by the backend,
    # never the container image's current working directory.
    return Path(root) if root is not None else Path(os.environ.get("ASTRA_WORKSPACE", Path.cwd() / "workspace")) / "company"


def _company_dir(company_id: str, root: str | Path | None) -> Path:
    if not company_id or Path(company_id).name != company_id:
        raise ValueError("company_id must be a non-empty path-safe identifier")
    return _root(root) / company_id


def _require_company(company_id: str, root: str | Path | None) -> Path:
    directory = _company_dir(company_id, root)
    if not directory.exists() or _load_snapshot(directory) is None:
        raise KeyError(f"unknown company: {company_id}")
    return directory


def _mirror_artifact_to_library(company_id: str, artifact_id: str, name: str, data: dict[str, Any], *, root: str | Path | None) -> str | None:
    """Create the Library file for a not-yet-persisted artifact and return its
    file id, so create_artifact can fold it into the artifact.created event
    instead of following up with a second artifact.updated event."""
    try:
        company = get_company_os(company_id, root=root)
        if not company:
            return None
        from backend.library.store import create_file
        file = create_file(
            founder_id=str(company["founder_id"]),
            department=str(data.get("department") or "Operations").replace("_", " ").title(),
            filename=f"{name}.md",
            content=str(data.get("content") or ""),
            source_tag="Company OS",
            source_session_id=str(artifact_id),
        )
        return file["id"]
    except Exception as exc:
        # The Company OS event is already durable; a later projection rebuild
        # can retry a failed mirror without risking loss of the primary artifact.
        logger.warning("Company OS artifact Library mirror failed: company=%s artifact=%s error=%s", company_id, artifact_id, exc)
        return None


def _writer_lock(directory: Path):
    return cross_process_file_lock(directory / ".writer.lock")


def _snapshot_path(directory: Path) -> Path:
    return directory / "snapshot.json"


def _load_snapshot(directory: Path) -> dict[str, Any] | None:
    path = _snapshot_path(directory)
    if not path.exists():
        return None
    data = read_json(path, lambda: None)
    if not isinstance(data, dict) or "state" not in data or "last_sequence" not in data:
        raise ValueError(f"invalid Company OS snapshot: {path}")
    if data.get("checksum") != _checksum(data):
        raise ValueError(f"corrupt Company OS snapshot: {path}: checksum mismatch")
    return data


def _write_snapshot(directory: Path, state: dict[str, Any], sequence: int) -> None:
    snapshot = {"schema_version": 1, "last_sequence": sequence, "state": state}
    snapshot["checksum"] = _checksum(snapshot)
    write_json_atomic(_snapshot_path(directory), snapshot, sort_keys=True)


def _segments(directory: Path) -> list[Path]:
    return sorted(directory.glob("events-*.jsonl"))


def _active_segment(directory: Path) -> Path:
    segments = _segments(directory)
    if not segments:
        return directory / "events-000001.jsonl"
    last = segments[-1]
    if sum(1 for _ in _read_segment(last)) >= _SEGMENT_LIMIT:
        number = int(last.stem.split("-")[-1]) + 1
        return directory / f"events-{number:06d}.jsonl"
    return last


def _events_after(directory: Path, sequence: int) -> Iterable[dict[str, Any]]:
    expected = sequence + 1
    for segment in _segments(directory):
        for event in _read_segment(segment):
            if event["sequence"] <= sequence:
                continue
            if event["sequence"] != expected:
                raise ValueError("Company OS event sequence is not contiguous")
            expected += 1
            yield event


def _replay(directory: Path, loaded: dict[str, Any]) -> tuple[dict[str, Any], int]:
    # `loaded` always comes straight from a fresh read_json() call (see every
    # caller of _load_snapshot) -- nothing else holds a reference to it, so
    # mutating loaded["state"] in place is safe. Skipping the deepcopy matters:
    # on a large company (multi-MB snapshot) this was a full recursive copy
    # of the entire state on every cache-miss read, dominating request time.
    state = loaded["state"]
    _normalize_state(state)
    sequence = int(loaded["last_sequence"])
    for event in _events_after(directory, sequence):
        _apply_event(state, event)
        sequence = event["sequence"]
    _normalize_state(state)
    return state, sequence


def _normalize_state(state: dict[str, Any]) -> None:
    """Supply graph defaults while replaying snapshots written before squads had roles."""
    for collection in _COLLECTIONS:
        state.setdefault(collection, [])
    for squad in state["squads"]:
        squad.setdefault("role_ids", [])
        squad.setdefault("meeting_ids", [])
    for role in state["squad_roles"]:
        role.setdefault("task_ids", [])
    for meeting in state["squad_meetings"]:
        meeting.setdefault("participant_role_ids", [])
        meeting.setdefault("task_ids", [])
    for task in state["tasks"]:
        task.setdefault("role_id", None)
        task.setdefault("meeting_id", None)
        task.setdefault("depends_on_task_ids", [])

    # Older snapshots do not have the denormalized graph indexes. Rebuild them
    # from the authoritative collections so migrations remain idempotent.
    roles_by_squad: dict[str, list[str]] = {}
    meetings_by_squad: dict[str, list[str]] = {}
    tasks_by_role: dict[str, list[str]] = {}
    tasks_by_meeting: dict[str, list[str]] = {}
    for role in state["squad_roles"]:
        roles_by_squad.setdefault(role["squad_id"], []).append(role["role_id"])
    for meeting in state["squad_meetings"]:
        meetings_by_squad.setdefault(meeting["squad_id"], []).append(meeting["meeting_id"])
    for task in state["tasks"]:
        if task.get("role_id"):
            tasks_by_role.setdefault(task["role_id"], []).append(task["task_id"])
        if task.get("meeting_id"):
            tasks_by_meeting.setdefault(task["meeting_id"], []).append(task["task_id"])
    for squad in state["squads"]:
        squad["role_ids"] = roles_by_squad.get(squad["squad_id"], [])
        squad["meeting_ids"] = meetings_by_squad.get(squad["squad_id"], [])
    for role in state["squad_roles"]:
        role["task_ids"] = tasks_by_role.get(role["role_id"], [])
    for meeting in state["squad_meetings"]:
        meeting["task_ids"] = tasks_by_meeting.get(meeting["meeting_id"], [])


def _read_segment(path: Path) -> Iterable[dict[str, Any]]:
    raw = path.read_bytes() if path.exists() else b""
    lines = raw.splitlines(keepends=True)
    valid_end = 0
    for index, line in enumerate(lines):
        is_last = index == len(lines) - 1
        try:
            if not line.endswith(b"\n"):
                raise ValueError("unterminated event")
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            if is_last:
                # A crash can leave only the final append torn. Preserve all prior events.
                with path.open("r+b") as fh:
                    fh.truncate(valid_end)
                    fh.flush()
                    os.fsync(fh.fileno())
                return
            raise ValueError(f"corrupt Company OS event in {path}: {exc}") from exc
        if not isinstance(event, dict) or event.get("checksum") != _checksum(event):
            raise ValueError(f"corrupt Company OS event in {path}: event checksum mismatch")
        valid_end += len(line)
        yield event


def _append_line(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("ab") as fh:
        fh.write(encoded)
        fh.flush()
        os.fsync(fh.fileno())


def _checksum(event: dict[str, Any]) -> str:
    content = {key: value for key, value in event.items() if key != "checksum"}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

"""Local-first, event-sourced Company OS storage.

Each company owns a directory under ``workspace/company``.  Snapshots are
atomically replaced; events are append-only JSONL records with content hashes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from backend.core.json_store import json_file_lock, read_json, write_json_atomic

_COLLECTIONS = (
    "initiatives", "squads", "missions", "tasks", "task_attempts",
    "artifacts", "approvals", "conversation", "context_records", "policy_decisions",
)
_SEGMENT_LIMIT = 250


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
        return copy.deepcopy(event)


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
    return _create(company_id, "initiative", {"initiative_id": initiative_id or _id("initiative"), "name": name, "state": state, **data}, root)


def create_squad(company_id: str, initiative_id: str, name: str, *, squad_id: str | None = None,
                 state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "squad", {"squad_id": squad_id or _id("squad"), "initiative_id": initiative_id, "name": name, "state": state, **data}, root)


def create_mission(company_id: str, initiative_id: str, squad_id: str, name: str, *, mission_id: str | None = None,
                   state: str = "active", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "mission", {"mission_id": mission_id or _id("mission"), "initiative_id": initiative_id, "squad_id": squad_id, "name": name, "state": state, **data}, root)


def create_task(company_id: str, initiative_id: str, squad_id: str, name: str, *, task_id: str | None = None,
                mission_id: str | None = None, state: str = "pending", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "task", {"task_id": task_id or _id("task"), "initiative_id": initiative_id, "squad_id": squad_id, "mission_id": mission_id, "name": name, "state": state, **data}, root)


def create_task_attempt(company_id: str, task_id: str, *, attempt_id: str | None = None,
                        state: str = "started", root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "task_attempt", {"attempt_id": attempt_id or _id("attempt"), "task_id": task_id, "state": state, **data}, root)


def create_artifact(company_id: str, name: str, *, artifact_id: str | None = None,
                    root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "artifact", {"artifact_id": artifact_id or _id("artifact"), "name": name, **data}, root)


def create_approval(company_id: str, title: str, *, approval_id: str | None = None,
                    task_id: str | None = None, state: str = "pending",
                    root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "approval", {"approval_id": approval_id or _id("approval"), "title": title,
                                               "task_id": task_id, "state": state, **data}, root)


def update_task(company_id: str, task_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "task", "task_id", task_id, changes, root)


def update_squad(company_id: str, squad_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist a squad lifecycle transition without mutating the snapshot directly."""
    return _update(company_id, "squad", "squad_id", squad_id, changes, root)


def update_mission(company_id: str, mission_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    """Persist a mission lifecycle transition without mutating the snapshot directly."""
    return _update(company_id, "mission", "mission_id", mission_id, changes, root)


def update_task_attempt(company_id: str, attempt_id: str, *, root: str | Path | None = None, **changes: Any) -> dict[str, Any]:
    return _update(company_id, "task_attempt", "attempt_id", attempt_id, changes, root)


def append_message(company_id: str, message: str, *, scope: str = "company", scope_id: str | None = None,
                   author: str | None = None, root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    return _create(company_id, "message", {"message_id": _id("message"), "message": message, "scope": scope, "scope_id": scope_id, "author": author, **data}, root)


def add_context_record(company_id: str, key: str, value: Any, *, scope: str = "company", scope_id: str | None = None,
                       root: str | Path | None = None, **data: Any) -> dict[str, Any]:
    _validate_scope(scope, scope_id)
    defaults = {"version": 1, "provenance": "local", "author": "copilot", "confidence": 1.0,
                "source_references": [], "supersedes": None, "canonical": scope == "company", "promoted_revision": False}
    return _create(company_id, "context_record", {"context_id": _id("context"), "key": key, "value": value,
                                                     "scope": scope, "scope_id": scope_id, **defaults, **data}, root)


def resolve_context(company_id: str, *, initiative_id: str | None = None, squad_id: str | None = None,
                    task_id: str | None = None, root: str | Path | None = None) -> dict[str, Any]:
    """Resolve context by overlaying company -> initiative -> squad -> task records."""
    record = get_company_os(company_id, root=root)
    if record is None:
        raise KeyError(f"unknown company: {company_id}")
    targets = [("company", None), ("initiative", initiative_id), ("squad", squad_id), ("task", task_id)]
    resolved: dict[str, Any] = {}
    source_records: dict[str, dict[str, Any]] = {}
    for scope, scope_id in targets:
        for item in record["context_records"]:
            if item["scope"] == scope and item.get("scope_id") == scope_id:
                previous = source_records.get(item["key"])
                if previous and previous.get("canonical") and not item.get("promoted_revision"):
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
    allowed = {"initiative", "squad", "mission", "task", "task_attempt", "message", "context_record", "artifact", "approval"}
    if separator != "." or kind not in allowed | {"policy"}:
        raise ValueError(f"unsupported Company OS event: {event['type']}")
    if kind == "policy" and action == "decided":
        state["policy_decisions"].append({**copy.deepcopy(event["payload"]), "created_at": event["at"]})
        state["updated_at"] = event["at"]
        return
    if action == "updated" and kind in {"squad", "mission", "task", "task_attempt"}:
        key = {"squad": "squad_id", "mission": "mission_id", "task": "task_id", "task_attempt": "attempt_id"}[kind]
        entity = _must_find(state, f"{kind}s", key, event["payload"][key])
        entity.update(copy.deepcopy(event["payload"].get("changes") or {}))
        entity["updated_at"] = event["at"]
        state["updated_at"] = event["at"]
        return
    if action != "created":
        raise ValueError(f"unsupported Company OS event: {event['type']}")
    payload = copy.deepcopy(event["payload"])
    _validate_entity_scope(state, kind, payload)
    collection = {"message": "conversation", "context_record": "context_records"}.get(kind, f"{kind}s")
    payload.setdefault("created_at", event["at"])
    state[collection].append(payload)
    state["updated_at"] = event["at"]


def _validate_entity_scope(state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    if kind == "squad":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
    elif kind == "mission":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
        squad = _must_find(state, "squads", "squad_id", payload["squad_id"])
        if squad["initiative_id"] != payload["initiative_id"]:
            raise ValueError("squad belongs to a different initiative")
    elif kind == "task":
        _must_find(state, "initiatives", "initiative_id", payload["initiative_id"])
        squad = _must_find(state, "squads", "squad_id", payload["squad_id"])
        if squad["initiative_id"] != payload["initiative_id"]:
            raise ValueError("squad belongs to a different initiative")
        if payload.get("mission_id"):
            mission = _must_find(state, "missions", "mission_id", payload["mission_id"])
            if mission["squad_id"] != payload["squad_id"]:
                raise ValueError("mission belongs to a different squad")
    elif kind == "task_attempt":
        _must_find(state, "tasks", "task_id", payload["task_id"])
    elif kind in {"message", "context_record"}:
        _validate_scope(payload.get("scope", "company"), payload.get("scope_id"), state)


def _validate_scope(scope: str, scope_id: str | None, state: dict[str, Any] | None = None) -> None:
    collections = {"company": None, "initiative": ("initiatives", "initiative_id"), "squad": ("squads", "squad_id"), "task": ("tasks", "task_id")}
    if scope not in collections or (scope == "company" and scope_id is not None) or (scope != "company" and not scope_id):
        raise ValueError("scope must be company, initiative, squad, or task with its matching scope_id")
    if state is not None and collections[scope] is not None:
        collection, key = collections[scope]
        _must_find(state, collection, key, scope_id)


def _must_find(state: dict[str, Any], collection: str, key: str, value: str) -> dict[str, Any]:
    for item in state[collection]:
        if item.get(key) == value:
            return item
    raise ValueError(f"unknown {key}: {value}")


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


def _writer_lock(directory: Path):
    return json_file_lock(directory / ".writer.lock")


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
    state = copy.deepcopy(loaded["state"])
    sequence = int(loaded["last_sequence"])
    for event in _events_after(directory, sequence):
        _apply_event(state, event)
        sequence = event["sequence"]
    return state, sequence


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

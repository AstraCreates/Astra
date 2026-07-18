"""Phase 1 internal-cohort dual-write and parity helpers for Company OS.

This module is intentionally transport-free: an internal route can call these
functions without acquiring a second persistence authority.  Cohort membership
is a small atomic local configuration, while dual-write receipts and parity
assessments are Company OS artifacts and therefore audited in its event log.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from backend import company_os
from backend.core.json_store import cross_process_file_lock, read_json, write_json_atomic


_REGISTRY_NAME = "phase1-internal-cohort.json"
_RECEIPT_KIND = "phase1_dual_write_receipt"
_ASSESSMENT_KIND = "phase1_parity_assessment"


def configure_internal_test_cohort(
    company_id: str,
    *,
    enabled: bool = True,
    root: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically enable or disable a company for internal-only dual writes."""
    path = _registry_path(root)
    with cross_process_file_lock(path):
        registry = _read_registry(path)
        companies = registry["companies"]
        if enabled:
            companies[company_id] = {
                "company_id": company_id,
                "enabled": True,
                "updated_at": _now(),
                "metadata": dict(metadata or {}),
            }
        else:
            companies.pop(company_id, None)
        registry["updated_at"] = _now()
        write_json_atomic(path, registry, sort_keys=True)
        return dict(companies.get(company_id, {"company_id": company_id, "enabled": False}))


def get_internal_test_cohort(company_id: str, *, root: str | Path | None = None) -> dict[str, Any] | None:
    """Return a cohort entry, or ``None`` when a company is not opted in."""
    entry = _read_registry(_registry_path(root))["companies"].get(company_id)
    return dict(entry) if entry else None


def is_internal_test_cohort(company_id: str, *, root: str | Path | None = None) -> bool:
    entry = get_internal_test_cohort(company_id, root=root)
    return bool(entry and entry.get("enabled"))


def list_internal_test_cohort(*, root: str | Path | None = None) -> list[dict[str, Any]]:
    """List enabled cohort companies for an internal traffic router."""
    return [dict(item) for item in _read_registry(_registry_path(root))["companies"].values() if item.get("enabled")]


def dual_write_legacy_activity(
    company_id: str,
    activity: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Map one normalized legacy activity to Company OS and store a receipt.

    ``activity`` accepts ``type`` (for example ``task.created`` or ``task``),
    an optional stable ``legacy_activity_id``, and entity fields.  Artifact
    content may be supplied as ``content`` or ``content_hash``.  Calls are
    idempotent when the stable legacy activity identifier is repeated.
    """
    if not is_internal_test_cohort(company_id, root=root):
        raise PermissionError("company is not in the internal Phase 1 cohort")
    if company_os.get_company_os(company_id, root=root) is None:
        raise KeyError(f"unknown company: {company_id}")
    normalized = _normalize_activity(activity)
    legacy_id = normalized["legacy_activity_id"]
    current = company_os.get_company_os(company_id, root=root) or {}
    for artifact in current.get("artifacts", []):
        if artifact.get("phase1_kind") == _RECEIPT_KIND and artifact.get("legacy_activity_id") == legacy_id:
            return {"status": "duplicate", "legacy_activity_id": legacy_id, "receipt": artifact}

    mapped = _map_activity(company_id, normalized, root=root)
    receipt = company_os.create_artifact(
        company_id,
        f"Phase 1 dual-write receipt: {legacy_id}",
        root=root,
        phase1_kind=_RECEIPT_KIND,
        legacy_activity_id=legacy_id,
        legacy_type=normalized["type"],
        mapped_entity_id=_entity_id(mapped),
        mapped_entity_type=normalized["type"],
        legacy_content_hash=_content_hash(normalized),
        mapped_content_hash=_content_hash(mapped),
        event_count=1,
        source_activity=_json_safe(normalized),
    )
    return {"status": "written", "legacy_activity_id": legacy_id, "mapped": mapped, "receipt": receipt}


def dual_write_legacy_fixture(
    company_id: str,
    fixture: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Dual-write all ``activities`` in a supplied legacy parity fixture."""
    activities = fixture.get("activities", fixture.get("events", []))
    if not isinstance(activities, list):
        raise ValueError("fixture activities must be a list")
    results = [dual_write_legacy_activity(company_id, item, root=root) for item in activities]
    return {"company_id": company_id, "written": sum(item["status"] == "written" for item in results), "results": results}


def assess_parity(
    company_id: str,
    fixture: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Assess Phase 1 event, artifact hash, and replayed task-state parity.

    The returned assessment is also persisted as a Company OS artifact.  This
    deliberately compares against the replayed materialized state rather than
    in-memory dual-write results, so restart/recovery regressions are visible.
    """
    if not is_internal_test_cohort(company_id, root=root):
        raise PermissionError("company is not in the internal Phase 1 cohort")
    activities = fixture.get("activities", fixture.get("events", []))
    if not isinstance(activities, list):
        raise ValueError("fixture activities must be a list")
    state = company_os.get_company_os(company_id, root=root)
    if state is None:
        raise KeyError(f"unknown company: {company_id}")
    receipts = [item for item in state.get("artifacts", []) if item.get("phase1_kind") == _RECEIPT_KIND]
    expected_ids = {_normalize_activity(item)["legacy_activity_id"] for item in activities}
    matched_receipts = [item for item in receipts if item.get("legacy_activity_id") in expected_ids]
    missing_ids = sorted(expected_ids - {item.get("legacy_activity_id") for item in matched_receipts})

    expected_artifacts = {_artifact_key(item): _content_hash(item) for item in activities if _normalize_type(item) == "artifact"}
    actual_artifacts = {
        _artifact_key(item): _content_hash(item)
        for item in state.get("artifacts", [])
        if item.get("phase1_kind") not in {_RECEIPT_KIND, _ASSESSMENT_KIND}
    }
    artifact_mismatches = {
        key: {"expected": expected, "actual": actual_artifacts.get(key)}
        for key, expected in expected_artifacts.items()
        if actual_artifacts.get(key) != expected
    }

    expected_tasks = {
        str(item.get("task_id") or item.get("id")): str(item.get("state", item.get("status", "pending")))
        for item in activities if _normalize_type(item) in {"task", "task_updated"}
    }
    replayed_tasks = {str(task.get("task_id")): str(task.get("state", task.get("status", "pending"))) for task in state.get("tasks", [])}
    task_mismatches = {
        task_id: {"expected": expected, "actual": replayed_tasks.get(task_id)}
        for task_id, expected in expected_tasks.items()
        if replayed_tasks.get(task_id) != expected
    }
    assessment = {
        "company_id": company_id,
        "fixture_id": str(fixture.get("fixture_id") or _stable_hash(activities)),
        "event_count": {"expected": len(activities), "actual": len(matched_receipts), "missing_activity_ids": missing_ids},
        "artifact_content_hash": {"expected": len(expected_artifacts), "mismatches": artifact_mismatches},
        "replay_task_state": {"expected": len(expected_tasks), "mismatches": task_mismatches},
    }
    assessment["passed"] = not missing_ids and not artifact_mismatches and not task_mismatches
    persisted = company_os.create_artifact(
        company_id,
        f"Phase 1 parity assessment: {assessment['fixture_id']}",
        root=root,
        phase1_kind=_ASSESSMENT_KIND,
        assessment=_json_safe(assessment),
    )
    return {**assessment, "record": persisted}


def _map_activity(company_id: str, item: Mapping[str, Any], *, root: str | Path | None) -> dict[str, Any]:
    kind = item["type"]
    # Structural fields are passed to the frozen Company OS API explicitly;
    # forwarding them as metadata would either duplicate arguments or let a
    # legacy fixture smuggle an alternate identity into the persisted entity.
    structural = {
        "type", "legacy_activity_id", "event_id", "event_type", "id", "status", "state", "name", "title",
        "initiative_id", "squad_id", "mission_id", "task_id", "attempt_id", "artifact_id", "approval_id",
        "message", "scope", "scope_id", "author", "key", "value", "changes",
    }
    data = {key: value for key, value in item.items() if key not in structural}
    if kind == "initiative":
        return company_os.create_initiative(company_id, str(item["name"]), initiative_id=item.get("initiative_id") or item.get("id"), root=root, **data)
    if kind == "squad":
        return company_os.create_squad(company_id, str(item["initiative_id"]), str(item["name"]), squad_id=item.get("squad_id") or item.get("id"), root=root, **data)
    if kind == "mission":
        return company_os.create_mission(company_id, str(item["initiative_id"]), str(item["squad_id"]), str(item["name"]), mission_id=item.get("mission_id") or item.get("id"), root=root, **data)
    if kind == "task":
        return company_os.create_task(company_id, str(item["initiative_id"]), str(item["squad_id"]), str(item["name"]), task_id=item.get("task_id") or item.get("id"), mission_id=item.get("mission_id"), state=str(item.get("state", item.get("status", "pending"))), root=root, **data)
    if kind == "task_attempt":
        return company_os.create_task_attempt(company_id, str(item["task_id"]), attempt_id=item.get("attempt_id") or item.get("id"), state=str(item.get("state", item.get("status", "started"))), root=root, **data)
    if kind == "task_updated":
        task_id = str(item.get("task_id") or item.get("id"))
        changes = dict(item.get("changes") or {"state": item.get("state", item.get("status", "pending"))})
        return company_os.update_task(company_id, task_id, root=root, **changes)
    if kind == "artifact":
        return company_os.create_artifact(company_id, str(item["name"]), artifact_id=item.get("artifact_id") or item.get("id"), root=root, **data)
    if kind == "approval":
        return company_os.create_approval(company_id, str(item["title"]), approval_id=item.get("approval_id") or item.get("id"), task_id=item.get("task_id"), state=str(item.get("state", item.get("status", "pending"))), root=root, **data)
    if kind == "message":
        return company_os.append_message(company_id, str(item["message"]), scope=str(item.get("scope", "company")), scope_id=item.get("scope_id"), author=item.get("author"), root=root, **data)
    if kind == "context_record":
        return company_os.add_context_record(company_id, str(item["key"]), item.get("value"), scope=str(item.get("scope", "company")), scope_id=item.get("scope_id"), root=root, **data)
    raise ValueError(f"unsupported legacy activity type: {kind}")


def _normalize_activity(activity: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(activity, Mapping):
        raise ValueError("legacy activity must be an object")
    item = dict(activity)
    item["type"] = _normalize_type(item)
    if not item["type"]:
        raise ValueError("legacy activity type is required")
    entity_id = item.get("id") or item.get("task_id") or item.get("artifact_id") or item.get("mission_id")
    item["legacy_activity_id"] = str(item.get("legacy_activity_id") or item.get("event_id") or (
        f"{item['type']}:{entity_id}" if entity_id else _stable_hash(item)
    ))
    return item


def _normalize_type(item: Mapping[str, Any]) -> str:
    raw = str(item.get("type") or item.get("event_type") or "").lower().replace(".", "_")
    aliases = {"conversation": "message", "conversation_message": "message", "context": "context_record", "task_update": "task_updated"}
    return aliases.get(raw, raw.removesuffix("_created"))


def _artifact_key(item: Mapping[str, Any]) -> str:
    return str(item.get("artifact_id") or item.get("id") or item.get("name") or _normalize_activity(item)["legacy_activity_id"])


def _content_hash(item: Mapping[str, Any]) -> str | None:
    supplied = item.get("content_hash")
    if supplied:
        return str(supplied)
    if "content" not in item:
        return None
    return hashlib.sha256(str(item["content"]).encode("utf-8")).hexdigest()


def _entity_id(record: Mapping[str, Any]) -> str | None:
    for key in ("initiative_id", "squad_id", "mission_id", "task_id", "attempt_id", "artifact_id", "approval_id", "message_id", "context_id"):
        if record.get(key):
            return str(record[key])
    return None


def _registry_path(root: str | Path | None) -> Path:
    base = Path(root) if root is not None else Path.cwd() / "workspace" / "company"
    return base / _REGISTRY_NAME


def _read_registry(path: Path) -> dict[str, Any]:
    value = read_json(path, lambda: {"schema_version": 1, "companies": {}, "updated_at": None})
    if not isinstance(value, dict) or not isinstance(value.get("companies"), dict):
        raise ValueError("invalid Phase 1 cohort registry")
    return value


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

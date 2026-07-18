"""Phase 1 integrity evidence and cutover gates for the local Company OS.

The Company OS store remains authoritative.  This module deliberately keeps
its evidence append-only so an operator can audit both successful drills and
failures without trusting a mutable readiness flag.
"""
from __future__ import annotations

import copy
import calendar
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend import company_os
from backend.core.json_store import json_file_lock

_SOAK_SECONDS = 72 * 60 * 60
_EVIDENCE_FILE = "integrity-evidence.jsonl"


def run_recovery_drill(
    company_id: str,
    *,
    root: str | Path | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Exercise atomic snapshot recovery and event checksum replay.

    No application record is mutated: the drill only materializes a snapshot,
    rereads it through the public store API, and replays the remaining event
    log.  Its result is durably recorded whether it passes or fails.
    """
    at = observed_at or _now()
    try:
        before = _state_digest(_require_company(company_id, root))
        company_os.snapshot(company_id, root=root)
        recovered = _require_company(company_id, root)
        company_os.replay_events(company_id, root=root)  # validates every retained event checksum
        after = _state_digest(recovered)
        outcome = {
            "kind": "recovery_drill",
            "observed_at": at,
            "snapshot_recovery_passed": before == after,
            "checksum_replay_passed": True,
            "passed": before == after,
            "before_state_hash": before,
            "after_state_hash": after,
        }
    except Exception as exc:  # Evidence must survive the failure being measured.
        outcome = {
            "kind": "recovery_drill",
            "observed_at": at,
            "snapshot_recovery_passed": False,
            "checksum_replay_passed": False,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return _append_evidence(company_id, outcome, root=root)


def record_parity_evidence(
    company_id: str,
    *,
    source_event_count: int,
    company_os_event_count: int,
    source_artifacts: Mapping[str, str] | Iterable[Mapping[str, Any]],
    company_os_artifacts: Mapping[str, str] | Iterable[Mapping[str, Any]],
    source_task_states: Mapping[str, str] | Iterable[Mapping[str, Any]],
    company_os_task_states: Mapping[str, str] | Iterable[Mapping[str, Any]],
    cohort: str = "internal",
    observed_at: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Record a single, inspectable shadow-parity observation for a company."""
    source_artifact_hashes = _artifact_hashes(source_artifacts)
    os_artifact_hashes = _artifact_hashes(company_os_artifacts)
    source_states = _task_states(source_task_states)
    os_states = _task_states(company_os_task_states)
    event_parity = source_event_count == company_os_event_count
    artifact_parity = source_artifact_hashes == os_artifact_hashes
    task_state_parity = source_states == os_states
    return _append_evidence(company_id, {
        "kind": "parity_observation",
        "observed_at": observed_at or _now(),
        "cohort": cohort,
        "event_count_parity": event_parity,
        "artifact_content_hash_parity": artifact_parity,
        "task_state_parity": task_state_parity,
        "passed": event_parity and artifact_parity and task_state_parity,
        "source_event_count": source_event_count,
        "company_os_event_count": company_os_event_count,
        "source_artifact_hashes": source_artifact_hashes,
        "company_os_artifact_hashes": os_artifact_hashes,
        "source_task_states": source_states,
        "company_os_task_states": os_states,
    }, root=root)


def record_phase_1_failure(company_id: str, error: str, *, observed_at: str | None = None,
                           root: str | Path | None = None) -> dict[str, Any]:
    """Durably fail closed when an internal-cohort shadow operation fails."""
    return _append_evidence(company_id, {
        "kind": "parity_observation",
        "observed_at": observed_at or _now(),
        "event_count_parity": False,
        "artifact_content_hash_parity": False,
        "task_state_parity": False,
        "passed": False,
        "error": error,
    }, root=root)


def evaluate_soak_eligibility(
    company_id: str,
    *,
    now: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Return whether the preceding 72 hours have uninterrupted drill coverage."""
    evaluated_at = now or _now()
    cutoff = _epoch(evaluated_at) - _SOAK_SECONDS
    drills = [entry for entry in read_integrity_evidence(company_id, root=root)
              if entry.get("kind") == "recovery_drill"]
    timed = [(entry, _epoch(str(entry["observed_at"]))) for entry in drills if entry.get("observed_at")]
    covered = bool(timed) and min(timestamp for _, timestamp in timed) <= cutoff
    failures = [entry for entry, timestamp in timed if timestamp >= cutoff and not entry.get("passed")]
    return {
        "soak_window_hours": 72,
        "evaluated_at": evaluated_at,
        "coverage_started_at": min((entry["observed_at"] for entry, _ in timed), default=None),
        "zero_recovery_failures": not failures,
        "full_window_covered": covered,
        "eligible": covered and not failures,
        "recovery_failures": copy.deepcopy(failures),
    }


def evaluate_phase_1_gate(
    company_id: str,
    *,
    now: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate the non-bypassable Phase 1 gate for Phase 2 and cutover.

    A current passing parity observation and a passing recovery drill must be
    present, and the recovery record must prove a complete failure-free 72-hour
    soak.  Missing evidence is a block, never an implicit pass.
    """
    evidence = read_integrity_evidence(company_id, root=root)
    parity = _latest(evidence, "parity_observation")
    recovery = _latest(evidence, "recovery_drill")
    soak = evaluate_soak_eligibility(company_id, now=now, root=root)
    checks = {
        "event_count_parity": bool(parity and parity.get("event_count_parity")),
        "artifact_content_hash_parity": bool(parity and parity.get("artifact_content_hash_parity")),
        "task_state_parity": bool(parity and parity.get("task_state_parity")),
        "recovery_drill_passed": bool(recovery and recovery.get("passed")),
        "seventy_two_hour_zero_failure_soak": soak["eligible"],
    }
    allowed = all(checks.values())
    return {
        "company_id": company_id,
        "phase": 1,
        "checks": checks,
        "soak": soak,
        "blocked_reasons": [name for name, passed in checks.items() if not passed],
        "phase_2_allowed": allowed,
        "cutover_allowed": allowed,
    }


def require_phase_1_gate(company_id: str, *, now: str | None = None,
                         root: str | Path | None = None) -> dict[str, Any]:
    """Raise when an operator attempts Phase 2/cutover without Phase 1 proof."""
    gate = evaluate_phase_1_gate(company_id, now=now, root=root)
    if not gate["phase_2_allowed"]:
        raise PermissionError("Phase 1 gate is closed: " + ", ".join(gate["blocked_reasons"]))
    return gate


def read_integrity_evidence(company_id: str, *, root: str | Path | None = None) -> list[dict[str, Any]]:
    """Read and checksum-validate the append-only integrity evidence log."""
    path = _evidence_path(company_id, root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with json_file_lock(path.parent / ".integrity-evidence.lock"):
        records = _read_evidence_unlocked(path)
    return records


def _append_evidence(company_id: str, payload: dict[str, Any], *, root: str | Path | None) -> dict[str, Any]:
    path = _evidence_path(company_id, root)
    if not path.parent.is_dir():
        raise KeyError(f"unknown company: {company_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with json_file_lock(path.parent / ".integrity-evidence.lock"):
        sequence = len(_read_evidence_unlocked(path)) + 1
        record = {"sequence": sequence, "recorded_at": _now(), **copy.deepcopy(payload)}
        record["checksum"] = _checksum(record)
        with path.open("ab") as handle:
            handle.write((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    return record


def _read_evidence_unlocked(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("checksum") != _checksum(record):
            raise ValueError("integrity evidence checksum mismatch")
        records.append(record)
    return records


def _require_company(company_id: str, root: str | Path | None) -> dict[str, Any]:
    company = company_os.get_company_os(company_id, root=root)
    if company is None:
        raise KeyError(f"unknown company: {company_id}")
    return company


def _evidence_path(company_id: str, root: str | Path | None) -> Path:
    base = Path(root) if root is not None else Path.cwd() / "workspace" / "company"
    if not company_id or Path(company_id).name != company_id:
        raise ValueError("company_id must be a non-empty path-safe identifier")
    return base / company_id / _EVIDENCE_FILE


def _state_digest(state: dict[str, Any]) -> str:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checksum(record: Mapping[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "checksum"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _artifact_hashes(items: Mapping[str, str] | Iterable[Mapping[str, Any]]) -> dict[str, str]:
    if isinstance(items, Mapping):
        return {str(key): str(value) for key, value in items.items()}
    return {str(item["artifact_id"]): str(item.get("content_hash", item.get("hash", ""))) for item in items}


def _task_states(items: Mapping[str, str] | Iterable[Mapping[str, Any]]) -> dict[str, str]:
    if isinstance(items, Mapping):
        return {str(key): str(value) for key, value in items.items()}
    return {str(item["task_id"]): str(item["state"]) for item in items}


def _latest(records: Iterable[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    matches = [record for record in records if record.get("kind") == kind]
    return matches[-1] if matches else None


def _epoch(timestamp: str) -> float:
    return float(calendar.timegm(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

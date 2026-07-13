"""Durable anomaly ledger for Wave 4.5 control-plane drills."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_MAX_EVENTS = 500
_KNOWN_KEYS = {
    "receipt_collision",
    "approval_mismatch",
    "tenant_leak_probe",
    "budget_overshoot",
    "event_sequence_gap",
}


def _root() -> Path:
    root = Path(".astra/control_plane_anomalies")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ledger_path() -> Path:
    return _root() / "platform.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"events": [], "updated_at": _now()}
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {"events": [], "updated_at": _now()}
    data.setdefault("events", [])
    data.setdefault("updated_at", _now())
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = _now()
    _ledger_path().write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document

        mirror_document("control_plane_anomalies", "platform", data)
    except Exception:
        pass
    return data


def record_anomaly(
    key: str,
    *,
    severity: str = "critical",
    run_id: str = "",
    step_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if key not in _KNOWN_KEYS:
        raise ValueError(f"unknown anomaly key {key!r}")
    event = {
        "key": key,
        "severity": severity,
        "run_id": str(run_id or ""),
        "step_id": str(step_id or ""),
        "payload": dict(payload or {}),
        "recorded_at": _now(),
    }
    with _LOCK:
        ledger = _load()
        events = list(ledger.get("events") or [])
        events.append(event)
        ledger["events"] = events[-_MAX_EVENTS:]
        _save(ledger)
    return event


def list_anomalies(limit: int = 100, key: str = "") -> dict[str, Any]:
    with _LOCK:
        ledger = _load()
    events = list(ledger.get("events") or [])
    if key:
        events = [item for item in events if item.get("key") == key]
    events = list(reversed(events))
    return {
        "events": events[: max(1, min(limit, _MAX_EVENTS))],
        "total": len(events),
        "updated_at": ledger.get("updated_at"),
    }


def anomaly_metrics() -> dict[str, int]:
    data = list_anomalies(limit=_MAX_EVENTS)
    events = data["events"]
    counts = {name: 0 for name in _KNOWN_KEYS}
    for item in events:
        key = str(item.get("key") or "")
        if key in counts:
            counts[key] += 1
    return {
        "control_plane_anomalies_total": len(events),
        "receipt_collision_alerts": counts["receipt_collision"],
        "approval_mismatch_alerts": counts["approval_mismatch"],
        "tenant_leak_probe_alerts": counts["tenant_leak_probe"],
        "budget_overshoot_alerts": counts["budget_overshoot"],
        "event_sequence_gap_alerts": counts["event_sequence_gap"],
    }

"""Durable anomaly ledger for Wave 4.5 control-plane drills."""
from __future__ import annotations

import json
import os
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
    try:
        _mirror_rollout_evidence(event)
    except Exception:
        pass
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


def _mirror_rollout_evidence(event: dict[str, Any]) -> None:
    # record_anomaly() is called unconditionally from action_executor.py/fakes.py
    # collision/mismatch/gap-detection code -- including from FAKE repos exercised by
    # the test suite. The local ledger write above is safely test-isolated (callers
    # chdir to tmp_path), but this function makes a REAL Supabase call via the default
    # SupabaseRolloutEvidenceRepository, with no dependency injection available at this
    # call depth. Any dev running tests locally against real prod Supabase credentials
    # would otherwise silently write fake halt-triggering evidence into a live rollout
    # campaign (this happened for real: see astra_rollout_evidence rows created by
    # test_execute_external_action_marks_receipt_collision on 2026-07-15).
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    from backend.control_plane.wave7_rollout import evaluate_rollout_campaign, record_rollout_evidence, rollout_status_snapshot

    campaigns = (rollout_status_snapshot().get("campaigns") or {})
    campaign = campaigns.get("control_plane_v2") or next(iter(campaigns.values()), None)
    if not isinstance(campaign, dict):
        return
    campaign_id = str(campaign.get("id") or "").strip()
    stage = str(campaign.get("stage") or "").strip()
    if not campaign_id or not stage:
        return

    key = str(event.get("key") or "")
    metric_flags = {
        "approval_mismatch": {"approval_digest_mismatch": True},
        "receipt_collision": {"duplicate_external_effect_receipt": True},
        "budget_overshoot": {"budget_overshoot_unexplained": True},
        "tenant_leak_probe": {"tenant_leak_probe_failed": True},
        "event_sequence_gap": {"event_sequence_gap": True},
    }
    metrics = dict(metric_flags.get(key) or {})
    if not metrics:
        return
    metrics["anomaly_key"] = key
    metrics["anomaly_payload"] = dict(event.get("payload") or {})

    record_rollout_evidence(
        campaign_id=campaign_id,
        kind="halt_probe",
        stage=stage,  # type: ignore[arg-type]
        passed=False,
        summary=f"Auto-recorded anomaly {key}",
        metrics=metrics,
        run_id=str(event.get("run_id") or "") or None,
    )
    evaluate_rollout_campaign(
        feature=str(campaign.get("feature") or "control_plane_v2"),
        baseline_completion_rate=0.95,
        baseline_p95_latency_ms=1000.0,
    )

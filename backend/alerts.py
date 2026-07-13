"""Production alert evaluation and delivery.

Readiness and metrics are passive. This module turns degraded platform state
into durable alert records and optionally delivers them to an operations
webhook. It is intentionally small and local-first, but the payloads are stable
enough to back a future Slack/PagerDuty/incident provider.
"""

from __future__ import annotations

import json
import re
import time
import hashlib
from pathlib import Path
from typing import Any

import requests


SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


def _root() -> Path:
    root = Path(".astra/alerts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ledger_path() -> Path:
    return _root() / "platform.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"alerts": [], "last_delivery": None, "updated_at": _now()}
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {"alerts": [], "last_delivery": None, "updated_at": _now()}
    data.setdefault("alerts", [])
    data.setdefault("last_delivery", None)
    data.setdefault("updated_at", _now())
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = _now()
    _ledger_path().write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("alerts", "platform", data)
    except Exception:
        pass
    return data


def evaluate_platform_alerts(status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build alert candidates from a platform status snapshot."""
    if status is None:
        from backend.platform_status import platform_status
        status = platform_status()
    alerts: list[dict[str, Any]] = []
    if not status.get("ready"):
        failed = [
            key
            for key, value in (status.get("checks") or {}).items()
            if key != "runtime" and isinstance(value, dict) and value.get("ok") is False
        ]
        alerts.append(_alert(
            "platform_not_ready",
            "critical",
            "Astra is not ready to serve production stack runs.",
            {"failed_checks": failed, "status": status.get("status")},
        ))
    runtime = (status.get("checks") or {}).get("runtime") or {}
    if runtime.get("memory_percent", 0) > 90:
        alerts.append(_alert("runtime_memory_high", "critical", "Backend memory usage is above 90%.", {"memory_percent": runtime.get("memory_percent")}))
    if runtime.get("disk_percent", 0) > 88:
        alerts.append(_alert("runtime_disk_high", "critical", "Backend disk usage is above 88%.", {"disk_percent": runtime.get("disk_percent")}))
    state = status.get("state") or {}
    if state.get("runs_error", 0) > 0:
        alerts.append(_alert("run_errors_present", "warning", "Durable run ledger contains failed runs.", {"runs_error": state.get("runs_error")}))
    if state.get("connector_sources_error", 0) > 0:
        alerts.append(_alert("connector_sync_errors_present", "warning", "Connector sync ledger contains failed syncs.", {"connector_sources_error": state.get("connector_sources_error")}))
    anomaly_map = [
        ("receipt_collision_alerts", "receipt_collision_detected", "critical", "External action receipt collision detected."),
        ("approval_mismatch_alerts", "approval_mismatch_detected", "critical", "Approval mismatch detected during durable action execution."),
        ("tenant_leak_probe_alerts", "tenant_leak_probe_detected", "critical", "Cross-company tenant leak probe was detected and blocked."),
        ("budget_overshoot_alerts", "budget_overshoot_detected", "warning", "Budget overshoot was detected during reconciliation."),
        ("event_sequence_gap_alerts", "event_sequence_gap_detected", "critical", "Run event sequence gap detected."),
    ]
    for metric_key, alert_key, severity, message in anomaly_map:
        count = int(state.get(metric_key, 0) or 0)
        if count > 0:
            alerts.append(_alert(alert_key, severity, message, {metric_key: count}))
    return alerts


def record_platform_alerts(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist alert candidates, de-duplicating by stable alert id."""
    ledger = _load()
    existing = {item.get("id"): item for item in ledger.get("alerts", [])}
    for alert in alerts:
        previous = existing.get(alert["id"])
        if previous:
            previous["last_seen_at"] = alert["last_seen_at"]
            previous["count"] = int(previous.get("count") or 1) + 1
            previous["payload"] = alert.get("payload", {})
            previous["status"] = "open"
        else:
            existing[alert["id"]] = alert
    ledger["alerts"] = sorted(existing.values(), key=lambda item: item.get("last_seen_at", ""), reverse=True)[:200]
    return _save(ledger)


def run_alert_check(status: dict[str, Any] | None = None, *, deliver: bool = True) -> dict[str, Any]:
    """Evaluate, persist, and optionally deliver platform alerts."""
    alerts = evaluate_platform_alerts(status)
    ledger = record_platform_alerts(alerts)
    delivery = deliver_alerts(alerts) if deliver and alerts else {"ok": True, "delivered": 0, "skipped": not bool(alerts)}
    if alerts:
        ledger["last_delivery"] = delivery
        _save(ledger)
    return {
        "ok": True,
        "alert_count": len(alerts),
        "alerts": alerts,
        "delivery": delivery,
    }


def deliver_alerts(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.config import settings

    min_rank = SEVERITY_RANK.get(str(settings.astra_alert_min_severity or "warning").lower(), 2)
    selected = [alert for alert in alerts if SEVERITY_RANK.get(alert.get("severity"), 0) >= min_rank]
    webhook_url = str(settings.astra_alert_webhook_url or "")
    if not webhook_url:
        return {"ok": True, "delivered": 0, "skipped": True, "reason": "ASTRA_ALERT_WEBHOOK_URL not configured.", "eligible": len(selected)}
    payload = {"service": "astra", "sent_at": _now(), "alerts": selected}
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        ok = response.status_code < 400
        return {
            "ok": ok,
            "delivered": len(selected) if ok else 0,
            "status_code": response.status_code,
            "response": response.text[:240],
            "eligible": len(selected),
        }
    except Exception as exc:
        return {"ok": False, "delivered": 0, "error": str(exc), "eligible": len(selected)}


def list_alerts(limit: int = 50, status: str = "") -> dict[str, Any]:
    ledger = _load()
    alerts = list(ledger.get("alerts") or [])
    if status:
        alerts = [alert for alert in alerts if alert.get("status") == status]
    return {
        "alerts": alerts[: max(1, min(limit, 200))],
        "alert_count": len(alerts),
        "open_count": len([alert for alert in ledger.get("alerts", []) if alert.get("status") == "open"]),
        "last_delivery": ledger.get("last_delivery"),
        "updated_at": ledger.get("updated_at"),
    }


def alert_metrics() -> dict[str, int]:
    data = list_alerts(limit=200)
    alerts = data["alerts"]
    return {
        "alerts_total": len(alerts),
        "alerts_open": len([alert for alert in alerts if alert.get("status") == "open"]),
        "alerts_critical": len([alert for alert in alerts if alert.get("severity") == "critical" and alert.get("status") == "open"]),
        "alerts_warning": len([alert for alert in alerts if alert.get("severity") == "warning" and alert.get("status") == "open"]),
    }


def _alert(key: str, severity: str, message: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    return {
        "id": _stable_id(key, payload),
        "key": key,
        "severity": severity,
        "message": message,
        "payload": payload,
        "status": "open",
        "count": 1,
        "first_seen_at": now,
        "last_seen_at": now,
    }


def _stable_id(key: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"key": key, "payload": payload}, sort_keys=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", key).strip("_") or "alert"
    return f"{safe}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"

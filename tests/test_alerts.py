from backend.alerts import alert_metrics, list_alerts, run_alert_check
from backend.config import settings


class _FakeResponse:
    status_code = 200
    text = "ok"


def _degraded_status() -> dict:
    return {
        "ready": False,
        "status": "degraded",
        "checks": {
            "redis": {"ok": False, "status": "unavailable"},
            "runtime": {"ok": True, "memory_percent": 91, "disk_percent": 20, "process_rss_mb": 1},
        },
        "state": {
            "sessions_active": 0,
            "sessions_completed": 0,
            "events_buffered": 0,
            "workflow_snapshots": 0,
            "approval_ledgers": 0,
            "company_brains": 0,
            "runs_error": 1,
            "connector_sources_error": 1,
            "receipt_collision_alerts": 1,
            "approval_mismatch_alerts": 1,
            "tenant_leak_probe_alerts": 1,
            "budget_overshoot_alerts": 1,
            "event_sequence_gap_alerts": 1,
        },
    }


def test_alert_check_records_and_deduplicates_platform_alerts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "")

    first = run_alert_check(_degraded_status())
    second = run_alert_check(_degraded_status())
    ledger = list_alerts(limit=20)
    metrics = alert_metrics()

    assert first["alert_count"] >= 4
    assert second["alert_count"] == first["alert_count"]
    assert ledger["open_count"] == first["alert_count"]
    assert all(alert["count"] == 2 for alert in ledger["alerts"])
    assert metrics["alerts_open"] == first["alert_count"]
    assert metrics["alerts_critical"] >= 2
    keys = {alert["key"] for alert in ledger["alerts"]}
    assert "receipt_collision_detected" in keys
    assert "approval_mismatch_detected" in keys
    assert "tenant_leak_probe_detected" in keys
    assert "event_sequence_gap_detected" in keys


def test_alert_delivery_posts_to_configured_webhook(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "https://hooks.example/astra")
    monkeypatch.setattr(settings, "astra_alert_min_severity", "warning")
    calls: list[dict] = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse()

    monkeypatch.setattr("backend.alerts.requests.post", fake_post)

    result = run_alert_check(_degraded_status())

    assert result["delivery"]["ok"] is True
    assert result["delivery"]["delivered"] == result["alert_count"]
    assert calls[0]["url"] == "https://hooks.example/astra"
    assert calls[0]["json"]["service"] == "astra"
    assert len(calls[0]["json"]["alerts"]) == result["alert_count"]


def test_prometheus_metrics_include_alert_counts(tmp_path, monkeypatch):
    from backend import platform_status as ps

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "")
    run_alert_check(_degraded_status(), deliver=False)
    monkeypatch.setattr(ps, "platform_status", lambda: {
        "ready": True,
        "status": "healthy",
        "uptime_seconds": 1,
        "checks": {
            "runtime": {"ok": True, "memory_percent": 10, "disk_percent": 20, "process_rss_mb": 1},
            "stack_templates": {"ready_templates": 6, "min_score": 100, "ok": True},
            "auth_policy": {"ok": True},
        },
        "state": ps._state_metrics(),
    })

    metrics = ps.prometheus_metrics()

    assert "astra_alerts_open" in metrics
    assert "astra_alerts_critical" in metrics

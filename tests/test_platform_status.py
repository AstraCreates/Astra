from backend import platform_status as ps


def test_platform_status_checks_stack_templates_and_control_plane(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from backend.config import settings
    monkeypatch.setattr(settings, "astra_require_auth", False)

    stack_check = ps._check_stack_templates()
    billing_check = ps._check_accounts_billing()
    objective_check = ps._check_objective_readiness()
    auth_check = ps._check_auth_policy()
    ledger_check = ps._check_durable_ledgers()

    assert stack_check["ok"] is True
    assert stack_check["templates"] >= 6
    assert stack_check["min_score"] == 100
    assert billing_check["ok"] is True
    assert objective_check["ok"] is True
    assert {"beta", "starter", "team", "scale"} <= set(billing_check["plans"])
    assert auth_check["ok"] is True
    assert ledger_check["ok"] is True
    assert ledger_check["checks"]["approvals"]["ok"] is True
    assert ledger_check["checks"]["connector_sync"]["ok"] is True
    assert ledger_check["checks"]["run_ledger"]["path"] == ".astra/run_ledger"


def test_platform_status_readiness_includes_platform_subsystems(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from backend.config import settings
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(ps, "_check_redis", lambda: {"ok": True, "status": "ok"})
    monkeypatch.setattr(ps, "_check_models", lambda: {"ok": True, "status": "configured"})
    monkeypatch.setattr(ps, "_check_company_brain_scheduler", lambda: {"ok": True, "status": "running"})
    monkeypatch.setattr(ps, "_check_supabase", lambda: {"ok": False, "status": "missing_config"})
    monkeypatch.setattr(ps, "_check_storage", lambda: {"ok": True, "backend": "local", "status": "ok"})
    monkeypatch.setattr(ps, "_check_objective_readiness", lambda: {"ok": True, "status": "ready"})
    monkeypatch.setattr(ps, "_runtime_metrics", lambda: {"ok": True, "memory_percent": 10, "disk_percent": 20, "process_rss_mb": 1})

    status = ps.platform_status()
    ready = ps.readiness_status()
    metrics = ps.prometheus_metrics()

    assert status["ready"] is True
    assert status["checks"]["stack_templates"]["ok"] is True
    assert status["checks"]["objective_readiness"]["ok"] is True
    assert status["checks"]["accounts_billing"]["ok"] is True
    assert status["checks"]["durable_ledgers"]["ok"] is True
    assert status["checks"]["auth_policy"]["ok"] is True
    assert set(ready["checks"]) == {"redis", "models", "production_env", "company_brain_scheduler", "stack_templates", "objective_readiness", "accounts_billing", "auth_policy", "durable_ledgers"}
    assert "astra_redis_up 1" in metrics
    assert "astra_company_brain_scheduler_up 1" in metrics
    assert "astra_control_plane_anomalies_total" in metrics
    assert "astra_receipt_collision_alerts" in metrics


def test_platform_status_flags_missing_platform_admins_when_auth_enabled(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    monkeypatch.setattr(settings, "astra_platform_admins", "")

    auth_check = ps._check_auth_policy()

    assert auth_check["ok"] is False
    assert "ASTRA_PLATFORM_ADMINS is empty while auth is enabled." in auth_check["gaps"]

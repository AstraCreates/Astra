from backend.config import settings
from backend.deploy_evidence import build_deploy_evidence
from backend.production_smoke import run_production_smoke


def _configured_settings(monkeypatch):
    monkeypatch.setattr(settings, "frontend_url", "https://app.astracreates.com")
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_platform_admins", "admin_1")
    monkeypatch.setattr(settings, "astra_jwt_secret", "secret")
    monkeypatch.setattr(settings, "astra_creds_key", "creds")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live")
    monkeypatch.setattr(settings, "stripe_price_starter", "price_starter")
    monkeypatch.setattr(settings, "stripe_price_team", "price_team")
    monkeypatch.setattr(settings, "stripe_price_scale", "price_scale")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_live")
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "https://hooks.example/astra")


def test_deploy_evidence_names_missing_production_proof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3003")
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "astra_platform_admins", "")
    monkeypatch.setattr(settings, "astra_jwt_secret", "")
    monkeypatch.setattr(settings, "astra_creds_key", "")
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "stripe_price_starter", "")
    monkeypatch.setattr(settings, "stripe_price_team", "")
    monkeypatch.setattr(settings, "stripe_price_scale", "")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "")

    evidence = build_deploy_evidence(base_url="http://localhost:8000", strict=True)

    assert evidence["ok"] is False
    assert "FRONTEND_URL=https://..." in evidence["missing"]
    assert "ASTRA_REQUIRE_AUTH=true" in evidence["missing"]
    assert "ASTRA_CREDS_KEY" in evidence["missing"]
    assert "STRIPE_SECRET_KEY" in evidence["missing"]
    assert "ASTRA_ALERT_WEBHOOK_URL" in evidence["missing"]
    assert "founder_id for connector validation" in evidence["missing"]
    assert all({"key", "ok", "message", "details", "missing"} <= set(check) for check in evidence["checks"])


def test_deploy_evidence_passes_with_mocked_live_connector_proof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configured_settings(monkeypatch)
    monkeypatch.setattr("backend.connector_validation.validate_stack_connectors", lambda founder_id, stack_id, live=False: {
        "ready": True,
        "live": live,
        "connectors": [{"key": "github", "required": True, "status": "validated", "provider": {"status": "ok"}}],
    })

    evidence = build_deploy_evidence(
        founder_id="founder_prod",
        stack_id="idea_to_revenue",
        base_url="https://api.astracreates.com",
        live_connectors=True,
        strict=True,
        smoke_report={"checks": [
            {"key": "http_health", "ok": True},
            {"key": "http_ready", "ok": True},
            {"key": "http_metrics", "ok": True},
        ]},
    )

    assert evidence["ok"] is True
    assert evidence["missing"] == []
    assert all("missing" in check for check in evidence["checks"])


def test_strict_smoke_includes_deploy_evidence_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.platform_status.platform_status", lambda: {
        "ready": True,
        "status": "healthy",
        "checks": {
            "redis": {"ok": True},
            "models": {"ok": True},
            "company_brain_scheduler": {"ok": True},
            "stack_templates": {"ok": True},
            "accounts_billing": {"ok": True},
            "auth_policy": {"ok": True},
            "durable_ledgers": {"ok": True},
            "runtime": {"ok": True, "memory_percent": 10, "disk_percent": 10},
        },
    })

    result = run_production_smoke(strict=True)
    check = next(item for item in result["checks"] if item["key"] == "deploy_evidence_ready")

    assert result["ok"] is False
    assert check["ok"] is False
    assert "missing" in check["details"]
    assert result["deploy_evidence"]["ok"] is False

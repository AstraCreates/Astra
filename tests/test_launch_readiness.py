import pytest

from backend.config import settings
from backend.launch_readiness import build_launch_readiness
from backend.production_verify import run_production_verification


def _configure_prod_env(monkeypatch):
    monkeypatch.setattr(settings, "backend_url", "https://api.astracreates.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.astracreates.com")
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_platform_admins", "admin_1")
    monkeypatch.setattr(settings, "astra_jwt_secret", "secret")
    monkeypatch.setattr(settings, "astra_jwt_jwks_url", "")
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    monkeypatch.setattr(settings, "astra_creds_key", "creds")
    monkeypatch.setattr(settings, "astra_alert_webhook_url", "https://hooks.example/astra")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_live")
    monkeypatch.setattr(settings, "stripe_price_starter", "price_starter")
    monkeypatch.setattr(settings, "stripe_price_team", "price_team")
    monkeypatch.setattr(settings, "stripe_price_scale", "price_scale")


def test_launch_readiness_reports_missing_external_proof(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_prod_env(monkeypatch)

    audit = build_launch_readiness(
        founder_id="founder_prod",
        stack_id="idea_to_revenue",
        base_url="https://api.astracreates.com",
    )
    failed_keys = {check["key"] for check in audit["failed"]}

    assert audit["ok"] is False
    assert "latest_report_found" in failed_keys
    assert "objective_code_contract" not in failed_keys
    assert "production_requirements" not in failed_keys
    assert {"key", "ok", "message", "details"} <= set(audit["checks"][0])
    assert "missing" not in audit["checks"][0]


def test_launch_readiness_passes_with_saved_live_verification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_prod_env(monkeypatch)
    monkeypatch.setattr("backend.production_smoke.run_production_smoke", lambda **kwargs: {
        "ok": True,
        "created_at": "2026-05-29T00:00:00Z",
        "stack_id": kwargs["stack_id"],
        "failed_count": 0,
        "summary": "production smoke passed",
        "checks": [],
        "deploy_evidence": {"ok": True, "summary": "complete", "missing": [], "checks": []},
    })
    report = run_production_verification(
        founder_id="founder_prod",
        stack_id="idea_to_revenue",
        base_url="https://api.astracreates.com",
        live_connectors=True,
        save=True,
    )

    audit = build_launch_readiness(
        founder_id="founder_prod",
        stack_id="idea_to_revenue",
        base_url="https://api.astracreates.com",
        report_id=report["id"],
    )

    assert audit["ok"] is True
    assert audit["failed"] == []
    assert audit["bundle"]["ok"] is True
    assert audit["manifest"]["verified"] is True


@pytest.mark.asyncio
async def test_admin_launch_readiness_endpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_prod_env(monkeypatch)
    from backend.api.admin import launch_readiness

    audit = await launch_readiness(
        founder_id="founder_prod",
        stack_id="idea_to_revenue",
        base_url="https://api.astracreates.com",
    )

    assert audit["founder_id"] == "founder_prod"
    assert audit["stack_id"] == "idea_to_revenue"
    assert any(check["key"] == "latest_report_found" for check in audit["checks"])

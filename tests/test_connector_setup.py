from backend.config import settings
from backend.connector_setup import build_connector_setup_plan, seed_stack_connector_credentials_from_env
from backend.connectors.contracts import normalize_connector_service, prepare_connector_credentials_for_save
from backend.tools.company_brain import ingest_company_brain_records
from backend.provisioning.credentials_store import load_all_credentials, store_credentials


def test_connector_setup_plan_reports_required_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.provisioning.credentials_store._STORE_DIR", tmp_path / ".credentials")
    monkeypatch.setattr(settings, "backend_url", "https://api.astra.test")

    plan = build_connector_setup_plan("founder_setup", "idea_to_revenue")

    github = next(item for item in plan["connectors"] if item["key"] == "github")
    vercel = next(item for item in plan["connectors"] if item["key"] == "vercel")

    assert plan["ready"] is False
    assert github["setup_status"] == "missing_credentials"
    assert "token" in github["missing_fields"]
    assert github["webhook"]["supported"] is True
    assert github["webhook"]["url"] == "https://api.astra.test/brain/founder_setup/webhooks/github"
    assert vercel["required"] is True
    assert vercel["webhook"]["supported"] is False


def test_connector_setup_plan_marks_connected_connector_needing_memory_sync(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.provisioning.credentials_store._STORE_DIR", tmp_path / ".credentials")
    store_credentials("founder_setup", "github", {"token": "ghp_test", "webhook_secret": "whsec_test"})
    store_credentials("founder_setup", "vercel", {"token": "vercel_test"})

    plan = build_connector_setup_plan("founder_setup", "idea_to_revenue")
    github = next(item for item in plan["connectors"] if item["key"] == "github")

    assert github["connected"] is True
    assert github["setup_status"] == "connected_needs_sync"
    assert github["webhook"]["secret_configured"] is True
    assert any("Run Company Brain import for GitHub" in action for action in plan["next_actions"])


def test_connector_setup_plan_ready_when_required_credentials_and_memory_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.provisioning.credentials_store._STORE_DIR", tmp_path / ".credentials")
    store_credentials("founder_setup", "github", {"token": "ghp_test", "webhook_secret": "whsec_test"})
    store_credentials("founder_setup", "vercel", {"token": "vercel_test"})
    ingest_company_brain_records(
        "founder_setup",
        "github",
        [{"title": "Repo context", "content": "Astra repository contains the product launch surface and deployment handoff."}],
    )

    plan = build_connector_setup_plan("founder_setup", "idea_to_revenue")
    github = next(item for item in plan["connectors"] if item["key"] == "github")
    vercel = next(item for item in plan["connectors"] if item["key"] == "vercel")

    assert github["setup_status"] == "ready"
    assert vercel["setup_status"] == "ready"
    assert plan["ready"] is True


def test_seed_stack_connector_credentials_from_env_never_returns_secret_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.provisioning.credentials_store._STORE_DIR", tmp_path / ".credentials")
    monkeypatch.setattr(settings, "github_token", "ghp_secret")
    monkeypatch.setattr(settings, "vercel_token", "vercel_secret")

    result = seed_stack_connector_credentials_from_env("founder_setup", "idea_to_revenue")
    saved = load_all_credentials("founder_setup")

    seeded_keys = {item["key"] for item in result["seeded"]}
    assert result["seeded_count"] >= 2
    assert {"github", "vercel"}.issubset(seeded_keys)
    assert saved["github"]["token"] == "ghp_secret"
    assert saved["vercel"]["token"] == "vercel_secret"
    assert "ghp_secret" not in str(result)
    assert "vercel_secret" not in str(result)


def test_seed_stack_connector_credentials_from_env_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.provisioning.credentials_store._STORE_DIR", tmp_path / ".credentials")
    monkeypatch.setattr(settings, "github_token", "ghp_secret")
    monkeypatch.setattr(settings, "vercel_token", "vercel_secret")

    result = seed_stack_connector_credentials_from_env("founder_setup", "idea_to_revenue", dry_run=True)
    saved = load_all_credentials("founder_setup")

    assert result["dry_run"] is True
    assert result["seeded_count"] >= 2
    assert saved == {}


def test_prepare_connector_credentials_for_save_merges_existing_and_normalizes_alias():
    service, creds = prepare_connector_credentials_for_save(
        "googledocs",
        {"access_token": " new-token ", "ignored": "x"},
        existing={"refresh_token": "keep-me"},
    )

    assert service == "google_docs"
    assert creds == {"refresh_token": "keep-me", "access_token": "new-token"}
    assert normalize_connector_service("googlecalendar") == "google_calendar"


def test_prepare_connector_credentials_for_save_rejects_empty_payload():
    try:
        prepare_connector_credentials_for_save("resend", {"api_key": "   "})
    except ValueError as exc:
        assert "supported credential field" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty credential payload")

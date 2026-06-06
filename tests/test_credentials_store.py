from pathlib import Path

from backend.config import settings
from backend.provisioning import credentials_store
from backend.tools import integration_connect


def test_store_credentials_encrypts_and_generates_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(credentials_store, "_STORE_DIR", tmp_path / "creds")
    monkeypatch.setattr(settings, "astra_creds_key", "")

    credentials_store.store_credentials("founder-1", "github", {"token": "ghp_secret_123"})

    saved_path = credentials_store._founder_path("founder-1")
    raw = saved_path.read_text(encoding="utf-8")
    assert "ghp_secret_123" not in raw
    assert '"encrypted": true' in raw
    assert credentials_store.load_credentials("founder-1", "github") == {"token": "ghp_secret_123"}
    assert "ASTRA_CREDS_KEY=" in Path(".env").read_text(encoding="utf-8")


def test_load_plaintext_credentials_migrates_to_encrypted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(credentials_store, "_STORE_DIR", tmp_path / "creds")
    monkeypatch.setattr(settings, "astra_creds_key", "test-creds-key")

    saved_path = credentials_store._founder_path("founder-2")
    saved_path.write_text('{"stripe":{"access_token":"sk_live_plain"}}', encoding="utf-8")

    loaded = credentials_store.load_all_credentials("founder-2")

    assert loaded["stripe"]["access_token"] == "sk_live_plain"
    migrated = saved_path.read_text(encoding="utf-8")
    assert "sk_live_plain" not in migrated
    assert '"encrypted": true' in migrated


def test_founder_credential_save_does_not_touch_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(credentials_store, "_STORE_DIR", tmp_path / "creds")
    monkeypatch.setattr(settings, "astra_creds_key", "test-creds-key")
    Path(".env").write_text("GITHUB_TOKEN=platform-token\n", encoding="utf-8")

    integration_connect._save_founder_credentials("founder-3", "github", {"token": "ghp_founder_secret"})

    assert Path(".env").read_text(encoding="utf-8") == "GITHUB_TOKEN=platform-token\n"
    assert credentials_store.load_credentials("founder-3", "github") == {"token": "ghp_founder_secret"}

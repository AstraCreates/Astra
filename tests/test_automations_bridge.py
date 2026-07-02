from __future__ import annotations

from types import SimpleNamespace

from backend.tools import automations_bridge


class _Response:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_ensure_automations_account_skips_platform_id_when_unset(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(automations_bridge, "load_credentials", lambda founder_id, service: None)
    monkeypatch.setattr(automations_bridge, "store_credentials", lambda founder_id, service, creds: captured.setdefault("stored", creds))
    monkeypatch.delenv("AP_PLATFORM_ID", raising=False)

    def fake_post(url: str, json: dict, timeout: float):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(automations_bridge.requests, "post", fake_post)

    creds = automations_bridge.ensure_automations_account("Founder 123")

    assert captured["url"] == f"{automations_bridge._BASE_URL}/api/v1/authentication/sign-up"
    assert "platformId" not in captured["json"]
    assert creds["email"] == "founder_123@founders.astra.internal"
    assert captured["stored"] == creds


def test_ensure_automations_account_includes_platform_id_when_configured(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(automations_bridge, "load_credentials", lambda founder_id, service: None)
    monkeypatch.setattr(automations_bridge, "store_credentials", lambda founder_id, service, creds: None)
    monkeypatch.setenv("AP_PLATFORM_ID", "plat_123")

    def fake_post(url: str, json: dict, timeout: float):
        captured["json"] = json
        return _Response()

    monkeypatch.setattr(automations_bridge.requests, "post", fake_post)

    automations_bridge.ensure_automations_account("founder")

    assert captured["json"]["platformId"] == "plat_123"


def test_get_automations_session_token_accepts_nested_token(monkeypatch):
    monkeypatch.setattr(
        automations_bridge,
        "ensure_automations_account",
        lambda founder_id: {"email": "founder@example.com", "password": "secret"},
    )

    def fake_post(url: str, json: dict, timeout: float):
        return _Response(json_data={"data": {"access_token": "nested-token"}})

    monkeypatch.setattr(automations_bridge.requests, "post", fake_post)

    token = automations_bridge.get_automations_session_token("founder")

    assert token == "nested-token"

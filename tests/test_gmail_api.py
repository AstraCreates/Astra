import json

from backend.tools.gmail_api import fetch_gmail_verification, refresh_gmail_access_token


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_refresh_gmail_access_token_uses_google_oauth(monkeypatch):
    called = {}

    def fake_post(url, data=None, timeout=None):
        called["url"] = url
        called["data"] = data
        return _FakeResponse(200, {"access_token": "ya29.new-token", "expires_in": 3600})

    monkeypatch.setattr("backend.tools.gmail_api.requests.post", fake_post)
    monkeypatch.setattr("backend.config.settings.google_client_id", "google-client")
    monkeypatch.setattr("backend.config.settings.google_client_secret", "google-secret")

    refreshed = refresh_gmail_access_token({"refresh_token": "refresh-123"})

    assert refreshed["access_token"] == "ya29.new-token"
    assert called["data"]["refresh_token"] == "refresh-123"


def test_fetch_gmail_verification_extracts_code_from_message(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.gmail_api.get_gmail_api_credentials",
        lambda founder_id, inline_credentials=None: {"access_token": "ya29.token"},
    )

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/messages"):
            return _FakeResponse(200, {"messages": [{"id": "msg-1"}]})
        body = "Your Vercel verification code is 123456."
        encoded = __import__("base64").urlsafe_b64encode(body.encode()).decode().rstrip("=")
        return _FakeResponse(200, {"payload": {"body": {"data": encoded}}})

    monkeypatch.setattr("backend.tools.gmail_api.requests.get", fake_get)

    result = fetch_gmail_verification("founder-1", "vercel")

    assert result["code"] == "123456"
    assert result["link"] == ""

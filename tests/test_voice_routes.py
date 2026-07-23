import base64
import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.voice_routes import router as voice_router
from backend.config import settings


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_router)
    return TestClient(app)


def _body(audio: bytes = b"fake webm audio") -> dict:
    return {
        "founder_id": "founder_voice",
        "filename": "note.webm",
        "mime": "audio/webm",
        "data_base64": base64.b64encode(audio).decode("ascii"),
    }


class _FakeTranscriptions:
    seen: dict = {}

    @classmethod
    def create(cls, file, **kwargs):
        cls.seen = {"audio": file.read(), "kwargs": kwargs}
        return "voice note text"


class _FakeAudio:
    transcriptions = _FakeTranscriptions


class _FakeOpenAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.audio = _FakeAudio()


def _install_fake_openai(monkeypatch):
    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = _FakeOpenAI
    _FakeTranscriptions.seen = {}
    monkeypatch.setitem(sys.modules, "openai", fake_module)


def test_voice_transcribe_uses_whisper_default_without_realtime(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "voice_transcription_model", "whisper-1")
    monkeypatch.setattr(settings, "voice_transcription_max_bytes", 25 * 1024 * 1024)
    _install_fake_openai(monkeypatch)

    response = _client().post("/voice/transcribe", json=_body(b"hello audio"))

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "filename": "note.webm",
        "mime": "audio/webm",
        "model": "whisper-1",
        "text": "voice note text",
        "size_bytes": 11,
    }
    assert _FakeTranscriptions.seen["audio"] == b"hello audio"
    assert _FakeTranscriptions.seen["kwargs"] == {
        "model": "whisper-1",
        "response_format": "text",
    }


def test_voice_transcribe_accepts_language_prompt_and_model_override(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    _install_fake_openai(monkeypatch)
    body = {
        **_body(),
        "language": "en",
        "prompt": "Astra product names may appear.",
        "model": "gpt-4o-mini-transcribe",
    }

    response = _client().post("/voice/transcribe", json=body)

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-4o-mini-transcribe"
    assert _FakeTranscriptions.seen["kwargs"] == {
        "model": "gpt-4o-mini-transcribe",
        "response_format": "text",
        "language": "en",
        "prompt": "Astra product names may appear.",
    }


def test_voice_transcribe_rejects_invalid_base64(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)

    response = _client().post("/voice/transcribe", json={**_body(), "data_base64": "not base64 !!!"})

    assert response.status_code == 422
    assert response.json()["detail"] == "data_base64 must be valid base64 audio"


def test_voice_transcribe_rejects_oversized_audio(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "voice_transcription_max_bytes", 3)

    response = _client().post("/voice/transcribe", json=_body(b"1234"))

    assert response.status_code == 413
    assert response.json()["detail"] == "Audio file exceeds 3 bytes"


def test_voice_transcribe_requires_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = _client().post("/voice/transcribe", json=_body())

    assert response.status_code == 503
    assert response.json()["detail"] == "OPENAI_API_KEY is not configured"


def test_voice_transcribe_requires_auth_in_strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    monkeypatch.setattr(settings, "astra_allow_dev_auth", False)

    response = _client().post("/voice/transcribe", json=_body())

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."

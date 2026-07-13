from backend.observability.langfuse_hooks import (
    build_langfuse_payload,
    emit_langfuse_event,
    langfuse_enabled,
)


def test_langfuse_disabled_by_default(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_langfuse_enabled", False)
    assert langfuse_enabled() is False
    assert emit_langfuse_event("test", {"goal": "secret"}) is False


def test_build_langfuse_payload_redacts_sensitive_fields():
    payload = build_langfuse_payload("model.call", {
        "goal": "private plan",
        "nested": {"api_key": "sk-live"},
        "ok": "value",
    })
    assert payload["name"] == "model.call"
    assert payload["attributes"]["goal"] == "[REDACTED]"
    assert payload["attributes"]["nested"]["api_key"] == "[REDACTED]"
    assert payload["attributes"]["ok"] == "value"


def test_langfuse_enabled_hook_emits_best_effort(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_langfuse_enabled", True)
    assert emit_langfuse_event("test", {"ok": "value"}) is True

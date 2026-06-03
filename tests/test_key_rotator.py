from backend.config import settings
from backend.core import key_rotator


def test_openrouter_key_rotates_round_robin(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "k1")
    monkeypatch.setattr(settings, "openrouter_api_key_2", "k2")
    monkeypatch.setattr(settings, "openrouter_api_key_3", "k3")
    monkeypatch.setattr(key_rotator, "_cycle", None)
    monkeypatch.setattr(key_rotator, "_cycle_keys", None)

    assert [key_rotator.get_openrouter_key() for _ in range(5)] == ["k1", "k2", "k3", "k1", "k2"]


def test_openrouter_key_cycle_refreshes_when_settings_change(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "k1")
    monkeypatch.setattr(settings, "openrouter_api_key_2", "k2")
    monkeypatch.setattr(settings, "openrouter_api_key_3", "")
    monkeypatch.setattr(key_rotator, "_cycle", None)
    monkeypatch.setattr(key_rotator, "_cycle_keys", None)

    assert key_rotator.get_openrouter_key() == "k1"
    assert key_rotator.get_openrouter_key() == "k2"

    monkeypatch.setattr(settings, "openrouter_api_key_3", "k3")

    assert [key_rotator.get_openrouter_key() for _ in range(4)] == ["k1", "k2", "k3", "k1"]

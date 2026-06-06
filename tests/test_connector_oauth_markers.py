from backend.connector_validation import validate_connector
from backend.stacks.readiness import _is_connected


def test_readiness_does_not_treat_platform_composio_key_as_founder_connection():
    connected, source = _is_connected({}, "notion")
    assert connected is False
    assert source is None


def test_validation_accepts_composio_oauth_marker(monkeypatch):
    monkeypatch.setattr("backend.connector_validation.get_composio_app_status", lambda founder_id: {"notion": True})
    result = validate_connector(
        "founder-1",
        "notion",
        credentials={"notion": {"connected": True, "connected_via": "composio_oauth", "composio_app": "notion"}},
        required=True,
        live=True,
    )
    assert result["status"] == "validated"
    assert result["provider"]["status"] == "ok"


def test_validation_fails_when_composio_oauth_app_inactive(monkeypatch):
    monkeypatch.setattr("backend.connector_validation.get_composio_app_status", lambda founder_id: {"notion": False})
    result = validate_connector(
        "founder-1",
        "notion",
        credentials={"notion": {"connected": True, "connected_via": "composio_oauth", "composio_app": "notion"}},
        required=True,
        live=True,
    )
    assert result["status"] == "provider_error"

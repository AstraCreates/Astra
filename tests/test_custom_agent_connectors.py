from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.custom_agents_routes import custom_agents_router
from backend.custom_agents.builder import connector_readiness


def test_custom_agent_connector_readiness_includes_missing_details(monkeypatch):
    monkeypatch.setattr(
        "backend.connector_validation.validate_connector",
        lambda founder_id, key: {"status": "missing_credentials", "missing_fields": ["api_key"]},
    )

    result = connector_readiness("founder-1", ["resend_send_email"])

    assert result["ready"] is False
    assert result["missing"] == ["resend"]
    assert result["missing_details"][0]["key"] == "resend"
    assert result["missing_details"][0]["fields"][0]["key"] == "api_key"


def test_custom_agent_connect_route_returns_key_field_specs(monkeypatch):
    app = FastAPI()
    app.include_router(custom_agents_router)
    client = TestClient(app)

    monkeypatch.setattr("backend.api.custom_agents_routes.require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)

    response = client.get("/custom-agents/founder-1/connect/resend")

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "key"
    assert data["connector"] == "resend"
    assert data["fields"][0]["key"] == "api_key"

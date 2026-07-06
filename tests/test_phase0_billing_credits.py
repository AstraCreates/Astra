from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api.credits_routes import credits_router
from backend.config import settings
from backend.credits.store import add_credits, deduct_credits, get_credits


def test_deduct_credits_rejects_insufficient_balance_without_auto_refill():
    founder_id = "phase0_insufficient"
    starting = get_credits(founder_id)
    amount = starting["balance"] + 1

    with pytest.raises(ValueError, match="insufficient credits"):
        deduct_credits(founder_id, amount, "over budget")

    after = get_credits(founder_id)
    assert after["balance"] == starting["balance"]
    assert after["total_granted"] == starting["total_granted"]
    assert after["total_used"] == 0
    assert [tx["type"] for tx in after["transactions"]] == ["grant"]


def test_deduct_credits_still_records_valid_usage():
    founder_id = "phase0_valid_usage"
    before = add_credits(founder_id, 100, "grant", "test grant")

    after = deduct_credits(founder_id, 40, "test usage", session_id="sess_1")

    assert after["balance"] == before["balance"] - 40
    assert after["total_used"] == 40
    assert after["transactions"][-1]["type"] == "usage"
    assert after["transactions"][-1]["session_id"] == "sess_1"


def test_credits_webhook_rejects_when_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    app = FastAPI()
    app.include_router(credits_router)
    client = TestClient(app)

    response = client.post(
        "/credits/webhook",
        json={"type": "checkout.session.completed", "data": {"object": {"metadata": {}}}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Stripe webhook secret is not configured"


def test_funding_kit_call_llm_imports_runtime_dependencies(monkeypatch):
    from backend.funding import kit

    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = type("Message", (), {"content": "ok"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeClient:
        chat = type("Chat", (), {"completions": _FakeCompletions()})()

    def fake_get_or_client(base_url, api_key):
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return _FakeClient()

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key_2", "")
    monkeypatch.setattr(settings, "openrouter_api_key_3", "")
    monkeypatch.setattr(settings, "agent_model_api_key", "agent-key")
    monkeypatch.setattr("backend.core.llm_client.get_or_client", fake_get_or_client)

    assert kit._call_llm("hello") == "ok"
    assert captured["api_key"] == "agent-key"
    assert captured["model"] == settings.highoutput_model_name

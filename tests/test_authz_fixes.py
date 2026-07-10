import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from backend.api.schemas import GoalRequest
from backend.main import app


@pytest.mark.asyncio
async def test_continue_goal_rejects_prior_session_owned_by_another_founder(monkeypatch):
    monkeypatch.setattr(
        "backend.api.routes.require_founder_access",
        lambda request, founder_id, min_role="viewer": founder_id,
    )
    monkeypatch.setattr(
        "backend.core.session_store.get_session_meta",
        lambda session_id: {"founder_id": "founder-other"},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/goal/continue",
            json={
                "founder_id": "founder-1",
                "instruction": "Continue the prior goal",
                "prior_session_id": "session-123",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "prior session does not belong to founder"


def test_goal_request_rejects_overlength_instruction():
    with pytest.raises(ValidationError):
        GoalRequest(
            founder_id="founder-1",
            instruction="x" * 20001,
        )

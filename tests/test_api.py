import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from backend.main import app


@pytest.mark.asyncio
async def test_goal_endpoint_returns_session_id(mocker):
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value={"session_id": "abc123", "results": {}, "shared": {}})
    mocker.patch("backend.api.routes.get_orchestrator", return_value=mock_orch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/goal", json={
            "founder_id": "f_001",
            "instruction": "Draft a founder agreement for AcmeCo",
            "constraints": {},
        })
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_status_endpoint_returns_goal_info(mocker):
    mocker.patch(
        "backend.api.routes.get_supabase",
        return_value=_mock_supabase_with_goal(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/status/g_abc123")
    assert response.status_code == 200


def _mock_supabase_with_goal():
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g_abc123", "status": "in_progress", "instruction": "draft NDA"}
    ]
    return mock

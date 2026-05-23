import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from backend.main import app


@pytest.mark.asyncio
async def test_goal_endpoint_returns_202(mocker):
    mocker.patch(
        "backend.api.routes.orchestrator.run_goal",
        new=AsyncMock(return_value={
            "goal_id": "g_abc123",
            "status": "done",
            "results": [{"task_id": "t_001", "agent": "legal", "output": {"document": "Agreement text"}}],
            "pending_approvals": [],
            "elapsed_seconds": 1.2,
        }),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/goal", json={
            "founder_id": "f_001",
            "instruction": "Draft a founder agreement for AcmeCo",
            "constraints": {},
        })
    assert response.status_code == 200
    body = response.json()
    assert body["goal_id"] == "g_abc123"
    assert body["status"] == "done"


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
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g_abc123", "status": "in_progress", "instruction": "draft NDA"}
    ]
    return mock

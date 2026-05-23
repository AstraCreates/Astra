import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.orchestrator.loop import OrchestratorLoop
from backend.agents.base import AgentTask, AgentResult


@pytest.fixture
def loop(mocker):
    mocker.patch("backend.orchestrator.loop.parse_goal", new=AsyncMock(return_value={
        "instruction": "draft a founder agreement",
        "entities": {"company_name": "AcmeCo"},
        "constraints": {},
        "priority_agents": ["legal"],
    }))
    mocker.patch("backend.orchestrator.loop.build_task_dag", new=AsyncMock(return_value=[
        {"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft founder agreement", "tools_available": ["doc_generator"], "constraints": {}}
    ]))
    mocker.patch("backend.orchestrator.loop.persist_goal", new=AsyncMock())
    mocker.patch("backend.orchestrator.loop.persist_task_graph", new=AsyncMock())
    mocker.patch("backend.orchestrator.loop.update_task_status", new=AsyncMock())
    mocker.patch("backend.orchestrator.loop.update_goal_status", new=AsyncMock())
    mocker.patch("backend.orchestrator.loop.vector_store.write", new=AsyncMock())
    return OrchestratorLoop()


@pytest.mark.asyncio
async def test_process_goal_dispatches_task_to_agent(loop, mocker):
    ready_tasks = [
        {"id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft founder agreement",
         "context_bundle": {"company_name": "AcmeCo"}, "tools_available": [], "constraints": {}, "goal_id": "g_001"}
    ]
    mocker.patch("backend.orchestrator.loop.get_ready_tasks", new=AsyncMock(side_effect=[ready_tasks, []]))
    mocker.patch("backend.orchestrator.loop.has_in_progress_tasks", new=AsyncMock(side_effect=[True, False]))

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=AgentResult(
        task_id="t_001", agent="legal", status="done",
        output={"document": "Agreement text"}, confidence=0.95, reasoning="Generated",
    ))
    mocker.patch("backend.orchestrator.loop.AGENTS", {"legal": mock_agent})

    result = await loop.run_goal("g_001", "f_001", "draft a founder agreement", {})
    assert result["status"] == "done"
    mock_agent.run.assert_called_once()

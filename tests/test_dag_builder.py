import pytest
from unittest.mock import MagicMock
from backend.orchestrator.dag_builder import build_task_dag


@pytest.mark.asyncio
async def test_dag_builder_returns_tasks_list(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"tasks": [{"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft a founder agreement for AcmeCo"}]}'
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.orchestrator.dag_builder._get_model", return_value=mock_model)

    dag = await build_task_dag(
        goal_id="g1",
        parsed_goal={"instruction": "draft a founder agreement", "entities": {"company_name": "AcmeCo"}, "priority_agents": ["legal"]},
    )
    assert isinstance(dag, list)
    assert len(dag) == 1
    assert dag[0]["agent"] == "legal"
    assert dag[0]["depends_on"] == []


@pytest.mark.asyncio
async def test_dag_builder_falls_back_on_invalid_json(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid json"
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.orchestrator.dag_builder._get_model", return_value=mock_model)

    dag = await build_task_dag(
        goal_id="g1",
        parsed_goal={"instruction": "do something", "entities": {}, "priority_agents": []},
    )
    assert isinstance(dag, list)
    assert len(dag) >= 1


@pytest.mark.asyncio
async def test_dag_builder_assigns_unique_task_ids(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    # Both tasks have same task_id "t_001" — should be deduplicated
    mock_response.text = '{"tasks": [{"task_id": "t_001", "agent": "legal", "depends_on": []}, {"task_id": "t_001", "agent": "research", "depends_on": []}]}'
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.orchestrator.dag_builder._get_model", return_value=mock_model)

    dag = await build_task_dag(goal_id="g1", parsed_goal={"instruction": "launch", "entities": {}, "priority_agents": []})
    ids = [t["task_id"] for t in dag]
    assert len(ids) == len(set(ids)), f"Duplicate task IDs: {ids}"
    assert len(dag) == 2

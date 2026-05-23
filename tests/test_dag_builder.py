import json
import pytest
from unittest.mock import MagicMock


def _make_mock_client(response_json: str):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=response_json))]
    )
    return mock_client


@pytest.fixture(autouse=True)
def reset_dag_client(mocker):
    """Reset the cached OpenAI client so each test gets a fresh mock."""
    import backend.orchestrator.dag_builder as dag_mod
    dag_mod._client = None
    yield
    dag_mod._client = None


@pytest.fixture
def mock_three_task_dag(mocker):
    payload = json.dumps({
        "tasks": [
            {"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft agreement", "tools_available": [], "constraints": {}},
            {"task_id": "t_002", "agent": "research", "depends_on": [], "instruction": "Research market", "tools_available": [], "constraints": {}},
            {"task_id": "t_003", "agent": "web", "depends_on": ["t_001", "t_002"], "instruction": "Build landing page", "tools_available": [], "constraints": {}},
        ]
    })
    mocker.patch("backend.orchestrator.dag_builder.openai.OpenAI", return_value=_make_mock_client(payload))


@pytest.mark.asyncio
async def test_dag_builder_returns_tasks_list(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag(
        goal_id="g_abc",
        parsed_goal={"instruction": "launch my startup", "entities": {"company_name": "AcmeCo"}, "priority_agents": ["legal"]},
    )
    assert isinstance(dag, list)
    assert len(dag) == 3
    assert dag[0]["agent"] == "legal"


@pytest.mark.asyncio
async def test_dag_task_ids_are_goal_prefixed(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    for task in dag:
        assert task["task_id"].startswith("g_abc_"), f"Expected 'g_abc_' prefix, got: {task['task_id']}"


@pytest.mark.asyncio
async def test_dag_depends_on_remapped_to_goal_prefix(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    task_ids = {t["task_id"] for t in dag}
    for task in dag:
        for dep in task["depends_on"]:
            assert dep in task_ids, f"depends_on '{dep}' not in task_ids {task_ids}"


@pytest.mark.asyncio
async def test_dag_web_task_depends_on_two_tasks(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    web_task = next(t for t in dag if t["agent"] == "web")
    assert len(web_task["depends_on"]) == 2
    task_ids = {t["task_id"] for t in dag}
    assert all(dep in task_ids for dep in web_task["depends_on"])


@pytest.mark.asyncio
async def test_dag_builder_falls_back_on_invalid_json(mocker):
    mocker.patch(
        "backend.orchestrator.dag_builder.openai.OpenAI",
        return_value=_make_mock_client("not valid json at all")
    )
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_fallback", {"instruction": "do something", "entities": {}, "priority_agents": []})
    assert isinstance(dag, list)
    assert len(dag) >= 1
    assert dag[0]["task_id"].startswith("g_fallback_")


@pytest.mark.asyncio
async def test_dag_builder_no_pk_collision_across_goals(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag1 = await build_task_dag("g_001", {"instruction": "launch", "entities": {}, "priority_agents": []})
    dag2 = await build_task_dag("g_002", {"instruction": "launch", "entities": {}, "priority_agents": []})
    ids1 = {t["task_id"] for t in dag1}
    ids2 = {t["task_id"] for t in dag2}
    assert ids1.isdisjoint(ids2), f"ID collision across goals: {ids1 & ids2}"

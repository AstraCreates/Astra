import json
import pytest
from unittest.mock import MagicMock, AsyncMock

FOUNDER_ID = "83ede714-c2ba-4842-ac33-19b6c7ff22a8"

_AGENT_OUTPUTS = {
    "legal": {"document_name": "AcmeCo Founder Agreement", "content": "AGREEMENT text..."},
    "research": {"report_title": "AcmeCo Market Analysis", "tam_usd": "4B", "competitors": ["CompA"]},
    "web": {"headline": "Your AI founding team.", "cta_text": "Get Started", "value_props": ["Fast", "Simple", "Founder-first"]},
    "marketing": {"gtm_summary": "Cold email + ProductHunt", "email_sequence": [{"subject": "Hi", "body": "..."}], "channels": ["cold_email"]},
    "technical": {"spec_title": "AcmeCo MVP Spec", "stack": {"backend": "FastAPI"}, "mvp_features": [{"name": "Auth", "priority": "must"}]},
    "ops": {"weekly_digest": "Week 1 complete.", "priorities": ["Sign agreement", "Launch page", "Send emails"], "blockers": [], "next_actions": [{"action": "Review agreement", "owner": "Founder", "due": "48 hours"}]},
}


def _agent_response(agent_id: str) -> str:
    return json.dumps({
        "status": "done",
        "output": _AGENT_OUTPUTS[agent_id],
        "confidence": 0.9,
        "reasoning": f"{agent_id} task complete",
    })


@pytest.fixture
def mock_infra(mocker):
    task_store: dict = {}
    goal_store: dict = {}

    async def fake_persist_goal(goal_id, founder_id, instruction, constraints):
        goal_store[goal_id] = {"id": goal_id, "status": "pending"}

    async def fake_persist_task_graph(goal_id, founder_id, tasks):
        for t in tasks:
            task_store[t["task_id"]] = {
                **t, "id": t["task_id"], "goal_id": goal_id, "status": "pending",
            }

    async def fake_get_ready_tasks(goal_id):
        done_ids = {
            tid for tid, t in task_store.items()
            if t.get("status") == "done" and t.get("goal_id") == goal_id
        }
        return [
            t for t in task_store.values()
            if t.get("goal_id") == goal_id
            and t.get("status") == "pending"
            and all(dep in done_ids for dep in t.get("depends_on", []))
        ]

    async def fake_has_in_progress(goal_id):
        return any(
            t.get("status") == "in_progress" and t.get("goal_id") == goal_id
            for t in task_store.values()
        )

    async def fake_update_task_status(task_id, status, output=None):
        if task_id in task_store:
            task_store[task_id]["status"] = status
            if output:
                task_store[task_id]["output"] = output

    async def fake_update_goal_status(goal_id, status, elapsed_seconds=None):
        if goal_id in goal_store:
            goal_store[goal_id]["status"] = status

    mocker.patch("backend.orchestrator.loop.persist_goal", side_effect=fake_persist_goal)
    mocker.patch("backend.orchestrator.loop.persist_task_graph", side_effect=fake_persist_task_graph)
    mocker.patch("backend.orchestrator.loop.get_ready_tasks", side_effect=fake_get_ready_tasks)
    mocker.patch("backend.orchestrator.loop.has_in_progress_tasks", side_effect=fake_has_in_progress)
    mocker.patch("backend.orchestrator.loop.update_task_status", side_effect=fake_update_task_status)
    mocker.patch("backend.orchestrator.loop.update_goal_status", side_effect=fake_update_goal_status)
    mocker.patch("backend.memory.vector_store.vector_store.write", new=AsyncMock())
    mocker.patch("backend.memory.vector_store.vector_store.retrieve", new=AsyncMock(return_value=[]))

    return {"goals": goal_store, "tasks": task_store}


@pytest.fixture
def mock_goal_parser(mocker):
    async def fake_parse(goal_id, founder_id, raw):
        return {
            "instruction": "launch AcmeCo — an AI tool for first-time founders",
            "entities": {"company_name": "AcmeCo", "problem": "founders waste time on admin"},
            "constraints": {},
            "priority_agents": ["legal", "research"],
        }
    mocker.patch("backend.orchestrator.loop.parse_goal", side_effect=fake_parse)


@pytest.fixture
def mock_dag_builder(mocker):
    async def fake_build(goal_id, parsed):
        raw_tasks = [
            {"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft founder agreement", "tools_available": ["doc_generator"], "constraints": {}},
            {"task_id": "t_002", "agent": "research", "depends_on": [], "instruction": "Research market", "tools_available": ["web_search"], "constraints": {}},
            {"task_id": "t_003", "agent": "web", "depends_on": ["t_001", "t_002"], "instruction": "Create landing page", "tools_available": ["landing_page_generator"], "constraints": {}},
            {"task_id": "t_004", "agent": "marketing", "depends_on": ["t_001", "t_002"], "instruction": "Create GTM plan", "tools_available": ["email_sequence_generator"], "constraints": {}},
            {"task_id": "t_005", "agent": "technical", "depends_on": ["t_003"], "instruction": "Create tech spec", "tools_available": ["spec_generator"], "constraints": {}},
            {"task_id": "t_006", "agent": "ops", "depends_on": ["t_001", "t_002", "t_003", "t_004", "t_005"], "instruction": "Synthesize all outputs", "tools_available": ["digest_generator"], "constraints": {}},
        ]
        old_to_new = {}
        for i, task in enumerate(raw_tasks):
            old_id = task["task_id"]
            new_id = f"{goal_id}_t_{i+1:03d}"
            old_to_new[old_id] = new_id
            task["task_id"] = new_id
        for task in raw_tasks:
            task["depends_on"] = [old_to_new.get(dep, dep) for dep in task["depends_on"]]
        return raw_tasks
    mocker.patch("backend.orchestrator.loop.build_task_dag", side_effect=fake_build)


@pytest.fixture
def mock_all_agents(mocker):
    from backend.orchestrator.loop import AGENTS
    for agent_id, agent in AGENTS.items():
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_agent_response(agent_id)))]
        )
        agent._client = mock_client
    yield
    for agent in AGENTS.values():
        agent._client = None


@pytest.mark.asyncio
async def test_six_agent_dag_all_complete(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    result = await loop.run_goal(
        goal_id="g_six_test",
        founder_id=FOUNDER_ID,
        raw_instruction="launch my startup AcmeCo",
        constraints={},
    )
    assert result["status"] == "done"
    completed_agents = {r["agent"] for r in result["results"]}
    assert completed_agents == {"legal", "research", "web", "marketing", "technical", "ops"}


@pytest.mark.asyncio
async def test_ops_depends_on_all_others(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    await loop.run_goal("g_order_test", FOUNDER_ID, "launch AcmeCo", {})

    ops_task = next(
        (t for t in mock_infra["tasks"].values() if t.get("agent") == "ops"),
        None,
    )
    assert ops_task is not None
    other_ids = {tid for tid, t in mock_infra["tasks"].items() if t.get("agent") != "ops"}
    assert all(dep in other_ids for dep in ops_task.get("depends_on", [])), (
        f"ops.depends_on should reference all other tasks; got {ops_task['depends_on']}"
    )


@pytest.mark.asyncio
async def test_no_pending_approvals_on_auto_goal(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    result = await loop.run_goal("g_approval_test", FOUNDER_ID, "launch AcmeCo", {})
    assert result["pending_approvals"] == []

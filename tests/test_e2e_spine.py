"""
Gate test for Stage 1 spine.
/goal 'draft a founder agreement' → Legal Agent → document returned.
All external calls (OpenAI-compat, Supabase, Vertex AI) are mocked.
"""
import json
import pytest
import backend.orchestrator.goal_parser as _gp_module
import backend.orchestrator.dag_builder as _dag_module
from unittest.mock import AsyncMock, MagicMock


def _make_openai_mock(content: str) -> MagicMock:
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    return mock_client


@pytest.fixture(autouse=True)
def reset_singletons():
    _gp_module._client = None
    _dag_module._client = None
    yield
    _gp_module._client = None
    _dag_module._client = None


@pytest.fixture
def mock_openai_parse(mocker):
    mock_client = _make_openai_mock(json.dumps({
        "instruction": "draft a founder agreement for AcmeCo",
        "entities": {"company_name": "AcmeCo", "icp": "solo founders"},
        "constraints": {},
        "priority_agents": ["legal"],
    }))
    mocker.patch("backend.orchestrator.goal_parser.openai.OpenAI", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_openai_dag(mocker):
    mock_client = _make_openai_mock(json.dumps({
        "tasks": [{
            "task_id": "t_001",
            "agent": "legal",
            "depends_on": [],
            "instruction": "Draft a founder agreement for AcmeCo. Include equity split, roles, IP assignment, and vesting schedule.",
            "tools_available": ["doc_generator"],
            "constraints": {},
        }]
    }))
    mocker.patch("backend.orchestrator.dag_builder.openai.OpenAI", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_legal_agent_model(mocker):
    founder_agreement_text = (
        "FOUNDER AGREEMENT\n\n"
        "1. EQUITY: Each founder receives 50% equity subject to 4-year vesting with 1-year cliff.\n"
        "2. ROLES: Founder A serves as CEO. Founder B serves as CTO.\n"
        "3. IP ASSIGNMENT: All IP created by founders is assigned to AcmeCo.\n"
        "4. VESTING: 4-year vesting schedule, 25% cliff after year 1, monthly thereafter.\n\n"
        "AI-generated document preparation — not legal advice. "
        "Review with a licensed attorney before signing."
    )
    mock_client = _make_openai_mock(json.dumps({
        "status": "done",
        "output": {"document": founder_agreement_text, "doc_type": "founder_agreement"},
        "confidence": 0.92,
        "reasoning": "Generated founder agreement with standard clauses",
    }))
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_db(mocker):
    tasks_store = {}
    goals_store = {}

    async def mock_persist_goal(goal_id, founder_id, instruction, constraints):
        goals_store[goal_id] = {"id": goal_id, "status": "pending", "instruction": instruction}

    async def mock_persist_tasks(goal_id, founder_id, tasks):
        for t in tasks:
            tasks_store[t["task_id"]] = {
                "id": t["task_id"], "goal_id": goal_id, "agent": t["agent"],
                "instruction": t["instruction"], "depends_on": t.get("depends_on", []),
                "context_bundle": {}, "tools_available": t.get("tools_available", []),
                "constraints": t.get("constraints", {}), "status": "pending",
            }

    call_count = {"get_ready": 0}

    async def mock_get_ready(goal_id):
        call_count["get_ready"] += 1
        if call_count["get_ready"] == 1:
            return [t for t in tasks_store.values() if t["status"] == "pending"]
        return []

    async def mock_has_in_progress(goal_id):
        return any(t["status"] == "in_progress" for t in tasks_store.values())

    async def mock_update_status(task_id, status, result=None):
        if task_id in tasks_store:
            tasks_store[task_id]["status"] = status

    async def mock_update_goal(goal_id, status, elapsed_seconds=None):
        if goal_id in goals_store:
            goals_store[goal_id]["status"] = status

    mocker.patch("backend.orchestrator.loop.persist_goal", side_effect=mock_persist_goal)
    mocker.patch("backend.orchestrator.loop.persist_task_graph", side_effect=mock_persist_tasks)
    mocker.patch("backend.orchestrator.loop.get_ready_tasks", side_effect=mock_get_ready)
    mocker.patch("backend.orchestrator.loop.has_in_progress_tasks", side_effect=mock_has_in_progress)
    mocker.patch("backend.orchestrator.loop.update_task_status", side_effect=mock_update_status)
    mocker.patch("backend.orchestrator.loop.update_goal_status", side_effect=mock_update_goal)
    mocker.patch("backend.orchestrator.loop.vector_store.write", new=AsyncMock())
    mocker.patch("backend.orchestrator.context_builder.vector_store.retrieve", new=AsyncMock(return_value=[]))
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return tasks_store, goals_store


@pytest.mark.asyncio
async def test_spine_gate_draft_founder_agreement(
    mock_openai_parse, mock_openai_dag, mock_legal_agent_model, mock_db
):
    """
    GATE TEST — Stage 1 spine.
    /goal 'draft a founder agreement' must return a real document via Legal Agent.
    """
    from backend.orchestrator.loop import OrchestratorLoop

    loop = OrchestratorLoop()
    result = await loop.run_goal(
        goal_id="g_test_001",
        founder_id="f_test_001",
        raw_instruction="draft a founder agreement for AcmeCo",
        constraints={},
    )

    assert result["status"] == "done", f"Expected 'done', got: {result}"
    assert len(result["results"]) >= 1
    legal_result = next(r for r in result["results"] if r["agent"] == "legal")

    assert "document" in legal_result["output"], "Legal Agent must return a document in output"

    doc_text = legal_result["output"]["document"]
    assert len(doc_text) > 100, "Document must be non-trivial"
    assert "not legal advice" in doc_text.lower(), "Document must contain legal disclaimer"
    assert result["pending_approvals"] == [], "Draft document should not require approval"

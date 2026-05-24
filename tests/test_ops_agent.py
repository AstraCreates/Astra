import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_ops_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "weekly_digest": "Week 1: Founder agreement drafted, market research complete (TAM $4B), landing page copy ready, cold email sequence built, tech spec written. Ready to review and ship.",
                "priorities": [
                    "Review and sign founder agreement (Legal Agent output)",
                    "Approve landing page copy before deploy",
                    "Send first 20 cold emails to ICP list",
                ],
                "blockers": [],
                "next_actions": [
                    {"action": "Review founder agreement", "owner": "Founder", "due": "48 hours"},
                    {"action": "Approve landing page copy", "owner": "Founder", "due": "3 days"},
                    {"action": "Deploy landing page", "owner": "Astra", "due": "3 days"},
                    {"action": "Send cold email batch 1", "owner": "Astra", "due": "1 week"},
                ],
            },
            "confidence": 0.92,
            "reasoning": "Synthesized all 5 agent outputs into prioritized action plan",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_ops_agent_id():
    from backend.agents.ops import OPS_AGENT
    assert OPS_AGENT.agent_id == "ops"


def test_ops_agent_reads_all_namespaces():
    from backend.agents.ops import OPS_AGENT
    expected = {"shared", "legal", "research", "web", "marketing", "technical", "ops"}
    assert expected.issubset(set(OPS_AGENT.memory_namespaces))


def test_ops_agent_has_digest_tool():
    from backend.agents.ops import OPS_AGENT
    assert "news_search" in OPS_AGENT.tools


@pytest.mark.asyncio
async def test_ops_agent_run_returns_done(mock_ops_model):
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="ops",
        system_prompt="You are the Ops Agent.",
        model=settings.agent_model_name,
        tools=["task_manager", "digest_generator"],
        memory_namespaces=["shared", "legal", "research", "web", "marketing", "technical", "ops"],
    )
    task = AgentTask(
        task_id="t_006", goal_id="g_001", founder_id="f_001",
        agent="ops", instruction="Synthesize all agent outputs into ops plan for AcmeCo",
        context_bundle={"company_name": "AcmeCo"},
        constraints={}, tools_available=["task_manager", "digest_generator"],
    )
    result = await agent.run(task)
    assert result.status == "done"
    assert "weekly_digest" in result.output
    assert "priorities" in result.output
    assert "next_actions" in result.output
    assert all("action" in a and "owner" in a and "due" in a for a in result.output["next_actions"])


@pytest.mark.asyncio
async def test_ops_agent_run_blocked_on_invalid_json(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json at all"))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="ops",
        system_prompt="You are the Ops Agent.",
        model=settings.agent_model_name,
        tools=["task_manager", "digest_generator"],
        memory_namespaces=["shared", "legal", "research", "web", "marketing", "technical", "ops"],
    )
    task = AgentTask(
        task_id="t_006", goal_id="g_001", founder_id="f_001",
        agent="ops", instruction="Create ops plan",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "blocked"
    # blocked_reason is implementation detail of ReAct loop

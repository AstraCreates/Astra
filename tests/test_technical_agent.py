import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_technical_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "spec_title": "AcmeCo MVP Technical Spec",
                "stack": {"backend": "FastAPI + Python 3.12", "frontend": "Next.js 14", "db": "Supabase (Postgres)", "hosting": "Vercel + Railway"},
                "mvp_features": [
                    {"name": "User auth (email + Google)", "priority": "must"},
                    {"name": "Goal submission form", "priority": "must"},
                    {"name": "Agent results dashboard", "priority": "must"},
                    {"name": "Stripe payment integration", "priority": "must"},
                    {"name": "Email notifications", "priority": "nice"},
                ],
                "architecture_summary": "REST API backend with async task processing, React SPA frontend, Postgres for persistence. No microservices — monolith until $10k MRR.",
                "timeline_weeks": 4,
            },
            "confidence": 0.88,
            "reasoning": "Standard SaaS stack, proven for 0-to-launch",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_technical_agent_id():
    from backend.agents.technical import TECHNICAL_AGENT
    assert TECHNICAL_AGENT.agent_id == "technical"


def test_technical_agent_namespaces():
    from backend.agents.technical import TECHNICAL_AGENT
    assert "technical" in TECHNICAL_AGENT.memory_namespaces
    assert "web" in TECHNICAL_AGENT.memory_namespaces
    assert "shared" in TECHNICAL_AGENT.memory_namespaces


def test_technical_agent_has_spec_tool():
    from backend.agents.technical import TECHNICAL_AGENT
    assert "spec_generator" in TECHNICAL_AGENT.tools


@pytest.mark.asyncio
async def test_technical_agent_run_returns_done(mock_technical_model):
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="technical",
        system_prompt="You are the Technical Agent.",
        model=settings.agent_model_name,
        tools=["spec_generator", "code_scaffolder"],
        memory_namespaces=["technical", "web", "shared"],
    )
    task = AgentTask(
        task_id="t_005", goal_id="g_001", founder_id="f_001",
        agent="technical", instruction="Create MVP tech spec for AcmeCo based on the landing page design",
        context_bundle={"company_name": "AcmeCo"},
        constraints={}, tools_available=["spec_generator"],
    )
    result = await agent.run(task)
    assert result.status == "done"
    assert "spec_title" in result.output
    assert "stack" in result.output
    assert "mvp_features" in result.output
    assert all("name" in f and "priority" in f for f in result.output["mvp_features"])


@pytest.mark.asyncio
async def test_technical_agent_run_blocked_on_invalid_json(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json at all"))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="technical",
        system_prompt="You are the Technical Agent.",
        model=settings.agent_model_name,
        tools=["spec_generator", "code_scaffolder"],
        memory_namespaces=["technical", "web", "shared"],
    )
    task = AgentTask(
        task_id="t_005", goal_id="g_001", founder_id="f_001",
        agent="technical", instruction="Create tech spec",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "blocked"
    assert result.blocked_reason == "invalid_json"

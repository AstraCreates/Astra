import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_web_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "page_title": "AcmeCo — AI for Founders",
                "headline": "Your AI founding team, on demand.",
                "subheadline": "Handle legal, research, and launch in days, not months.",
                "value_props": [
                    "Draft founder agreements in minutes",
                    "Know your market before you build",
                    "Launch a landing page this week",
                ],
                "cta_text": "Start Your Company",
                "cta_url": "/signup",
            },
            "confidence": 0.9,
            "reasoning": "Landing page copy based on ICP pain points",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_web_agent_id():
    from backend.agents.web import WEB_AGENT
    assert WEB_AGENT.agent_id == "web"


def test_web_agent_namespaces():
    from backend.agents.web import WEB_AGENT
    assert "web" in WEB_AGENT.memory_namespaces
    assert "research" in WEB_AGENT.memory_namespaces
    assert "shared" in WEB_AGENT.memory_namespaces


def test_web_agent_has_landing_page_tool():
    from backend.agents.web import WEB_AGENT
    assert "landing_page_generator" in WEB_AGENT.tools


@pytest.mark.asyncio
async def test_web_agent_run_returns_done(mock_web_model):
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="web",
        system_prompt="You are the Web Agent.",
        model=settings.agent_model_name,
        tools=["landing_page_generator"],
        memory_namespaces=["web", "research", "shared"],
    )
    task = AgentTask(
        task_id="t_003", goal_id="g_001", founder_id="f_001",
        agent="web", instruction="Create landing page copy for AcmeCo targeting B2B SaaS founders",
        context_bundle={"company_name": "AcmeCo", "icp": "B2B SaaS founders"},
        constraints={}, tools_available=["landing_page_generator"],
    )
    result = await agent.run(task)
    assert result.status == "done"
    assert "headline" in result.output
    assert "cta_text" in result.output
    assert "value_props" in result.output


@pytest.mark.asyncio
async def test_web_agent_run_blocked_on_invalid_json(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json at all"))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="web",
        system_prompt="You are the Web Agent.",
        model=settings.agent_model_name,
        tools=["landing_page_generator"],
        memory_namespaces=["web", "research", "shared"],
    )
    task = AgentTask(
        task_id="t_003", goal_id="g_001", founder_id="f_001",
        agent="web", instruction="Create landing page",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "blocked"
    assert result.blocked_reason == "invalid_json"

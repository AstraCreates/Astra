import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_research_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "report_title": "AcmeCo Market Analysis",
                "tam_usd": "4B",
                "sam_usd": "400M",
                "som_usd": "40M",
                "competitors": ["CompA — incumbent SaaS", "CompB — VC-backed"],
                "icp": "Bootstrapped B2B SaaS founders, <5 employees",
                "key_insights": "Market growing 23% YoY; no self-serve player under $500/mo",
            },
            "confidence": 0.85,
            "reasoning": "Based on available market context",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_research_agent_id():
    from backend.agents.research import RESEARCH_AGENT
    assert RESEARCH_AGENT.agent_id == "research"


def test_research_agent_namespaces():
    from backend.agents.research import RESEARCH_AGENT
    assert "research" in RESEARCH_AGENT.memory_namespaces
    assert "shared" in RESEARCH_AGENT.memory_namespaces


def test_research_agent_has_web_search_tool():
    from backend.agents.research import RESEARCH_AGENT
    assert "web_search" in RESEARCH_AGENT.tools


def test_research_agent_has_market_analyzer_tool():
    from backend.agents.research import RESEARCH_AGENT
    assert "market_analyzer" in RESEARCH_AGENT.tools


@pytest.mark.asyncio
async def test_research_agent_run_returns_done(mock_research_model):
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="research",
        system_prompt="You are the Research Agent.",
        model=settings.agent_model_name,
        tools=["web_search", "market_analyzer"],
        memory_namespaces=["research", "shared"],
    )
    task = AgentTask(
        task_id="t_001", goal_id="g_001", founder_id="f_001",
        agent="research", instruction="Research the AI productivity tools market for AcmeCo",
        context_bundle={"company_name": "AcmeCo", "problem": "founders waste time on admin"},
        constraints={}, tools_available=["web_search", "market_analyzer"],
    )
    result = await agent.run(task)
    assert result.status == "done"
    assert "report_title" in result.output
    assert "tam_usd" in result.output
    assert "competitors" in result.output


@pytest.mark.asyncio
async def test_research_agent_run_blocked_on_invalid_json(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json at all"))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="research",
        system_prompt="You are the Research Agent.",
        model=settings.agent_model_name,
        tools=["web_search", "market_analyzer"],
        memory_namespaces=["research", "shared"],
    )
    task = AgentTask(
        task_id="t_001", goal_id="g_001", founder_id="f_001",
        agent="research", instruction="Research market",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "blocked"
    assert result.blocked_reason == "invalid_json"

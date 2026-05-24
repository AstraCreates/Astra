import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_marketing_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "gtm_summary": "Target bootstrapped SaaS founders via cold email + ProductHunt launch in week 3",
                "channels": ["cold_email", "product_hunt", "indie_hackers"],
                "email_sequence": [
                    {"subject": "Quick question about {company}", "body": "Hi {first_name}, saw you're building {company}. How much time do you spend on legal and admin? We cut that to zero. Worth 15 min?"},
                    {"subject": "Re: Quick question", "body": "Following up — happy to show you a 5-minute demo. No pitch, just the product."},
                    {"subject": "Last one", "body": "Not the right time? No worries. Link if you change your mind."},
                ],
                "messaging_pillars": ["Speed — days not months", "Founder-first — built for non-lawyers", "Full stack — legal + research + launch in one"],
            },
            "confidence": 0.87,
            "reasoning": "GTM plan based on ICP and market research context",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_marketing_agent_id():
    from backend.agents.marketing import MARKETING_AGENT
    assert MARKETING_AGENT.agent_id == "marketing"


def test_marketing_agent_namespaces():
    from backend.agents.marketing import MARKETING_AGENT
    assert "marketing" in MARKETING_AGENT.memory_namespaces
    assert "research" in MARKETING_AGENT.memory_namespaces
    assert "shared" in MARKETING_AGENT.memory_namespaces


def test_marketing_agent_has_email_tool():
    from backend.agents.marketing import MARKETING_AGENT
    assert "send_email_campaign" in MARKETING_AGENT.tools


@pytest.mark.asyncio
async def test_marketing_agent_run_returns_done(mock_marketing_model):
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="marketing",
        system_prompt="You are the Marketing Agent.",
        model=settings.agent_model_name,
        tools=["email_sequence_generator", "gtm_planner"],
        memory_namespaces=["marketing", "research", "shared"],
    )
    task = AgentTask(
        task_id="t_004", goal_id="g_001", founder_id="f_001",
        agent="marketing", instruction="Create GTM plan for AcmeCo targeting bootstrapped B2B SaaS founders",
        context_bundle={"company_name": "AcmeCo", "icp": "B2B SaaS founders"},
        constraints={}, tools_available=["email_sequence_generator", "gtm_planner"],
    )
    result = await agent.run(task)
    assert result.status == "done"
    assert "gtm_summary" in result.output
    assert "email_sequence" in result.output
    assert len(result.output["email_sequence"]) >= 3
    assert all("subject" in e and "body" in e for e in result.output["email_sequence"])


@pytest.mark.asyncio
async def test_marketing_agent_run_blocked_on_invalid_json(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json at all"))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    from backend.agents.base import AstraAgent
    from backend.config import settings
    agent = AstraAgent(
        agent_id="marketing",
        system_prompt="You are the Marketing Agent.",
        model=settings.agent_model_name,
        tools=["email_sequence_generator", "gtm_planner"],
        memory_namespaces=["marketing", "research", "shared"],
    )
    task = AgentTask(
        task_id="t_004", goal_id="g_001", founder_id="f_001",
        agent="marketing", instruction="Create GTM plan",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "blocked"
    # blocked_reason is implementation detail of ReAct loop

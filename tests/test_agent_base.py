import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.core.agent import Agent, AgentContext


def _make_agent(mocker, llm_response: str = None) -> Agent:
    agent = Agent(name="legal", role="legal specialist. Draft legal documents.", tools={})
    if llm_response is not None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=llm_response))]
        )
        agent._client = mock_client
    return agent


def _ctx(**kwargs) -> AgentContext:
    defaults = dict(goal="Draft NDA", founder_id="f1", session_id="s1", shared={})
    defaults.update(kwargs)
    return AgentContext(**defaults)


def test_agent_has_correct_name():
    agent = Agent(name="legal", role="legal", tools={})
    assert agent.name == "legal"


def test_agent_stores_tools():
    tools = {"generate_pdf": lambda: None}
    agent = Agent(name="legal", role="legal", tools=tools)
    assert "generate_pdf" in agent.tools


@pytest.mark.asyncio
async def test_agent_run_calls_llm_and_returns_result(mocker):
    done_json = json.dumps({
        "tool": "done",
        "args": {"summary": "NDA drafted", "output": {"document": "Agreement text"}},
    })
    agent = _make_agent(mocker, llm_response=done_json)
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(_ctx())
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_agent_run_with_tool_call(mocker):
    tool_call = json.dumps({"tool": "generate_pdf", "args": {"title": "NDA", "sections": []}})
    done_call = json.dumps({"tool": "done", "args": {"summary": "done", "output": {}}})

    call_count = 0

    def fake_llm(messages):
        nonlocal call_count
        call_count += 1
        return tool_call if call_count == 1 else done_call

    agent = Agent(name="legal", role="legal", tools={"generate_pdf": lambda title, sections: "pdf_path"})
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(_ctx())
    assert call_count >= 1

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


@pytest.mark.asyncio
async def test_agent_run_native_tool_batch_emits_tool_role_messages(mocker):
    """A native-origin tool_batch (native:true + real ids, the shape _call_llm
    builds at agent.py:686-701 from a genuine tool_calls response) must produce
    a conformant assistant(tool_calls=[...]) + tool(tool_call_id=...) message
    pair -- NOT the merged role:user text blob the prose-JSON tool_batch path
    uses. Regression guard for the previously-uncovered native branch."""
    native_batch = json.dumps({
        "action": "tool_batch",
        "native": True,
        "calls": [{"id": "call_abc123", "tool": "generate_pdf", "args": {"title": "NDA", "sections": []}}],
    })
    done_call = json.dumps({"tool": "done", "args": {"summary": "done", "output": {}}})

    call_count = 0
    captured_messages = None

    def fake_llm(messages):
        nonlocal call_count, captured_messages
        call_count += 1
        if call_count == 2:
            # By the second call, the tool_batch handler has already appended
            # whatever it builds for the first response into `messages`.
            captured_messages = list(messages)
        return native_batch if call_count == 1 else done_call

    agent = Agent(name="legal", role="legal", tools={"generate_pdf": lambda title, sections: "pdf_path"})
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(_ctx())

    assert isinstance(result, dict)
    assert captured_messages is not None

    assistant_msgs = [m for m in captured_messages if m.get("role") == "assistant" and m.get("tool_calls")]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == ""
    assert assistant_msgs[0]["tool_calls"][0]["id"] == "call_abc123"
    assert assistant_msgs[0]["tool_calls"][0]["function"]["name"] == "generate_pdf"

    tool_msgs = [m for m in captured_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_abc123"
    assert tool_msgs[0]["name"] == "generate_pdf"

    # No merged role:user "Tool result (...)" blob for a native batch.
    user_blobs = [m for m in captured_messages if m.get("role") == "user" and "Tool result (" in str(m.get("content", ""))]
    assert not user_blobs


@pytest.mark.asyncio
async def test_agent_run_prose_tool_batch_unchanged(mocker):
    """A prose-JSON tool_batch (no native marker, no real ids -- a model typing
    {"action":"tool_batch",...} in text) must keep using the merged role:user
    blob exactly as before. Guards against the native branch leaking into the
    non-native path."""
    prose_batch = json.dumps({
        "action": "tool_batch",
        "calls": [{"tool": "generate_pdf", "args": {"title": "NDA", "sections": []}}],
    })
    done_call = json.dumps({"tool": "done", "args": {"summary": "done", "output": {}}})

    call_count = 0
    captured_messages = None

    def fake_llm(messages):
        nonlocal call_count, captured_messages
        call_count += 1
        if call_count == 2:
            captured_messages = list(messages)
        return prose_batch if call_count == 1 else done_call

    agent = Agent(name="legal", role="legal", tools={"generate_pdf": lambda title, sections: "pdf_path"})
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    await agent.run(_ctx())

    assert captured_messages is not None
    assert not [m for m in captured_messages if m.get("role") == "tool"]
    user_blobs = [m for m in captured_messages if m.get("role") == "user" and "Tool result (" in str(m.get("content", ""))]
    assert len(user_blobs) == 1

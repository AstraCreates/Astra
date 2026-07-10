import json
import sys
import types
from unittest.mock import AsyncMock

import pytest

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object, RateLimitError=Exception)

from backend.core.agent import Agent, AgentContext, _normalize_toolish_payload


def _ctx() -> AgentContext:
    return AgentContext(goal="Investigate competitors", founder_id="f1", session_id="s1", shared={})


def test_normalizes_stringified_openai_arguments():
    parsed = _normalize_toolish_payload({
        "name": "build_research_queries",
        "arguments": '{"topic":"Acme","focus":"competitors"}',
    })
    assert parsed["action"] == "tool"
    assert parsed["tool"] == "build_research_queries"
    assert parsed["args"] == {"topic": "Acme", "focus": "competitors"}


def test_normalizes_nested_function_arguments_without_stringifying_payload():
    parsed = _normalize_toolish_payload({
        "function": {
            "name": "deep_research",
            "arguments": '{"queries":["Acme competitors"]}',
        },
    })
    assert parsed["action"] == "tool"
    assert parsed["tool"] == "deep_research"
    assert parsed["args"] == {"queries": ["Acme competitors"]}


@pytest.mark.asyncio
async def test_agent_uses_one_shot_repair_for_unknown_tool_without_retry_loop(mocker):
    responses = iter([
        '{"action":"tool","tool":"deep_reseach","args":{"queries":["Acme"]}}',
        '{"name":"deep_research","arguments":{"queries":["Acme"]}}',
        '{"action":"done","output":{"summary":"repaired"}}',
    ])

    agent = Agent(
        name="hardening_probe",
        role="probe",
        tools={"deep_research": lambda **kwargs: {"report": "real"}},
        max_iterations=4,
    )
    agent._call_llm = lambda _messages, _ctx=None: next(responses)
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx())

    assert result["summary"] == "repaired"


@pytest.mark.asyncio
async def test_agent_repairs_natural_language_tool_request(mocker):
    responses = iter([
        "I should investigate Acme competitors and pricing before summarizing.",
        '{"action":"tool","tool":"deep_research","args":{"queries":["Acme competitors and pricing"]}}',
        '{"action":"done","output":{"summary":"natural language repaired"}}',
    ])

    agent = Agent(
        name="hardening_probe",
        role="probe",
        tools={"deep_research": lambda **kwargs: {"report": "real"}},
        max_iterations=4,
    )
    agent._call_llm = lambda _messages, _ctx=None: next(responses)
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx())

    assert result["summary"] == "natural language repaired"


@pytest.mark.asyncio
async def test_agent_backs_off_before_retrying_tool_error(mocker):
    responses = iter([
        '{"action":"tool","tool":"flaky","args":{}}',
        '{"action":"done","output":{"summary":"partial"}}',
        '{"action":"done","output":{"summary":"partial"}}',
    ])
    sleep = AsyncMock()
    mocker.patch("backend.core.agent.asyncio.sleep", new=sleep)

    agent = Agent(
        name="hardening_probe",
        role="probe",
        tools={"flaky": lambda **kwargs: {"error": "temporary"}},
        max_iterations=2,
    )
    agent._call_llm = lambda _messages, _ctx=None: next(responses)
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    await agent.run(_ctx())

    sleep.assert_awaited_with(2.0)


@pytest.mark.asyncio
async def test_agent_recovers_when_action_field_is_a_dict(mocker):
    """Real production crash: the model returned {"action": {...}} (a dict, not a
    string) on its first turn. Unguarded `x in self.tools` / `x == "done"` checks
    against that value raised TypeError: unhashable type: 'dict' before any tool
    was even dispatched — the run never got a chance to reach a normal completion
    or error status, agent.run() itself raised.

    This test deliberately asserts NOTHING about how/when the run eventually
    finishes (that depends on unrelated completion-quality-gate machinery keyed
    off agent name/tools — orthogonal to this bug and not this test's job to
    pin down). The only thing under test: a malformed dict-shaped action must
    not raise TypeError out of agent.run() — it should be treated as an
    'unknown action' and the loop should keep control (retry/exhaust normally),
    exactly like the WARNING-logged recovery already visible for any other
    malformed-but-hashable action value."""
    malformed = json.dumps({
        "action": {"tool": "generate_pdf"},
        "reasoning": {"note": "wrong shape"},
    })

    def fake_llm(_messages, _ctx=None):
        return malformed

    agent = Agent(name="hardening_probe", role="probe", tools={}, max_iterations=2)
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx())  # must not raise TypeError

    assert isinstance(result, dict)

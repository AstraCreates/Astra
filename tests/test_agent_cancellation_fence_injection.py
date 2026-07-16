"""Regression test for a real production crash:

    ✗ research_competitors
    deep_research: 'str' object has no attribute 'is_set'

Root cause: backend.tools.browser_research.deep_research() takes an internal
cancellation_fence/cancel_event kwarg meant to be injected by
Agent._execute_tool (a real threading.Event). But Agent._system_prompt's
_sig() dumped every inspect.signature() param -- including these two -- into
the tool listing shown to the model (functools.wraps' __wrapped__ makes
inspect.signature follow through the resilient-tool wrapper to the real
function). A model that then supplied its own value for cancellation_fence
survived agent.py's old args.setdefault(...) call (setdefault only fills
absent keys), and a plain string has no .is_set(), crashing every downstream
cancellation checkpoint in deep_research/browser_research.py.

Fixed by (1) excluding cancellation_fence/cancel_event from the prompt's
tool-signature listing, and (2) force-overwriting cancellation_fence in
_execute_tool instead of setdefault, so even a model that still somehow
supplies a value can never make it through.
"""
from __future__ import annotations

import pytest

from backend.core.agent import Agent, AgentContext


def _ctx(**kwargs) -> AgentContext:
    defaults = dict(goal="Research the competitive landscape", founder_id="f1", session_id="s1", shared={})
    defaults.update(kwargs)
    return AgentContext(**defaults)


def test_system_prompt_hides_cancellation_fence_from_model():
    def deep_research(queries=None, max_rounds=None, recursive_depth=None, cancel_event=None, cancellation_fence=None):
        """Run recursive research."""
        return {}

    agent = Agent(name="research_competitors", role="research", tools={"deep_research": deep_research})
    prompt = agent._system_prompt()

    assert "cancellation_fence" not in prompt
    assert "cancel_event" not in prompt
    assert "deep_research(queries, max_rounds, recursive_depth)" in prompt


@pytest.mark.asyncio
async def test_execute_tool_overrides_model_supplied_cancellation_fence(mocker):
    """Reproduces the exact prod crash: the model's tool-call args already
    contain a (bogus) cancellation_fence value. Before the fix, setdefault()
    respected it and it reached the tool as a plain string."""
    captured = {}

    def deep_research(queries=None, cancellation_fence=None):
        captured["cancellation_fence"] = cancellation_fence
        if cancellation_fence is not None and cancellation_fence.is_set():
            return {"error": "cancelled"}
        return {"ok": True, "queries": queries}

    agent = Agent(name="research_competitors", role="research", tools={"deep_research": deep_research})
    mocker.patch("backend.core.events.publish", new=mocker.AsyncMock())

    result = await agent._execute_tool(
        "deep_research",
        {"queries": ["competitor pricing"], "cancellation_fence": ""},
        _ctx(),
    )

    assert result == {"ok": True, "queries": ["competitor pricing"]}
    assert captured["cancellation_fence"] is not None
    assert hasattr(captured["cancellation_fence"], "is_set")
    assert captured["cancellation_fence"].is_set() is False


@pytest.mark.asyncio
async def test_execute_tool_injects_real_fence_when_absent(mocker):
    captured = {}

    def deep_research(queries=None, cancellation_fence=None):
        captured["cancellation_fence"] = cancellation_fence
        return {"ok": True}

    agent = Agent(name="research_competitors", role="research", tools={"deep_research": deep_research})
    mocker.patch("backend.core.events.publish", new=mocker.AsyncMock())

    await agent._execute_tool("deep_research", {"queries": ["market size"]}, _ctx())

    assert hasattr(captured["cancellation_fence"], "is_set")

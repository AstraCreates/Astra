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

import json

import pytest
from unittest.mock import AsyncMock

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


@pytest.mark.asyncio
async def test_done_rejected_for_insufficient_calls_names_an_untried_tool(mocker):
    """A second real production bug, same log: 'research' hit max_iterations_reached
    while 'research_competitors' completed cleanly on the same sequence of tool calls.

    _MIN_CALLS_BY_AGENT["research"] is 3 but _REQUIRED_BY_AGENT["research"] only
    names 2 tools (run_research_pipeline, deep_research) -- a 3rd, unspecified
    distinct tool call is implicitly required. actual_calls counts DISTINCT tool
    NAMES, so re-calling an already-used tool never helps, but the old rejection
    message just said "keep researching / executing" with no hint which tool
    would actually count, so the model could loop uselessly until MAX_ITERATIONS.
    research_competitors (min_calls=2, exactly matching its 2 required tools)
    never hits this gap, which is exactly why only "research" errored.
    """
    outputs = iter([
        json.dumps({"action": "tool", "tool": "run_research_pipeline", "args": {}}),
        json.dumps({"action": "tool", "tool": "deep_research", "args": {"queries": ["q"]}}),
        json.dumps({"action": "done", "output": {"summary": "s", "sources": ["u"]}}),
        json.dumps({"action": "tool", "tool": "news_search", "args": {"query": "q"}}),
        json.dumps({"action": "done", "output": {"summary": "s", "sources": ["u"]}}),
    ])
    captured_messages = []

    def fake_llm(messages, ctx=None):
        captured_messages.append(list(messages))
        return next(outputs)

    agent = Agent(name="research", role="research", tools={
        "run_research_pipeline": lambda **kw: {"coverage": {"ready": False}},
        "deep_research": lambda **kw: {"ok": True},
        "news_search": lambda **kw: {"ok": True},
    })
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx())

    assert result.get("status") != "max_iterations_reached"
    assert result.get("summary") == "s"

    rejection_prompt = captured_messages[3][-1]["content"]
    assert "already used again does not count" in rejection_prompt
    assert "news_search" in rejection_prompt


@pytest.mark.parametrize("agent_name,required", [
    ("research_market", {"deep_research"}),
    ("research_financial", {"deep_research", "generate_pdf"}),
    ("research_regulatory", {"deep_research", "generate_pdf"}),
    ("research_execution", {"run_research_pipeline", "deep_research"}),
])
def test_research_lane_completion_gates_no_longer_missing(agent_name, required):
    """research_market/financial/regulatory/execution had NO entry at all in
    _REQUIRED_BY_AGENT/_MIN_CALLS_BY_AGENT -- the .get(name, set())/.get(name, 1)
    fallbacks silently gave them zero required tools and min_calls=1, so a model
    could call one throwaway tool (e.g. news_search) and `done`, never touching
    deep_research despite every one of these prompts calling it "MANDATORY"."""
    from backend.core import agent as agent_mod

    assert agent_name in agent_mod._REQUIRED_BY_AGENT
    assert agent_mod._REQUIRED_BY_AGENT[agent_name] == required
    assert agent_name in agent_mod._MIN_CALLS_BY_AGENT
    assert agent_mod._MIN_CALLS_BY_AGENT[agent_name] <= len(agent_mod._REQUIRED_BY_AGENT[agent_name]) + 2


def test_research_execution_has_its_own_focus_role_not_generic_market_fallback():
    """research_execution silently inherited _FOCUS_ROLES["research"] (generic
    TAM/SAM/SOM market role) via _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])
    since no "research_execution" key existed -- it produced market-research output
    duplicating the "research" lane instead of the execution-strategy/GTM/tech-stack
    output the "custom" stack's StackArtifact entries for it actually expect."""
    from backend.specialists.research import _FOCUS_ROLES, _research_focus_for_agent

    assert "research_execution" in _FOCUS_ROLES
    role_text = _FOCUS_ROLES["research_execution"]
    assert "execution_strategy" in role_text
    assert "recommended_tech_stack" in role_text
    assert role_text != _FOCUS_ROLES["research"]
    assert _research_focus_for_agent("research_execution") == "execution"


@pytest.mark.asyncio
async def test_marketing_content_blog_post_mode_not_forced_into_social_package(mocker):
    """marketing_content's static _REQUIRED_BY_AGENT set only fits Mode F (Social
    Content Package) -- a "write a blog post" goal (Mode A) still got forced through
    3 Reel scripts, 2 TikTok packages, and 3 Meta ad variants it never needed, since
    the gate never looked at which mode the agent's own prompt told it to use."""
    outputs = iter([
        json.dumps({"action": "tool", "tool": "generate_pdf", "args": {"title": "t", "sections": []}}),
        json.dumps({"action": "tool", "tool": "obsidian_log", "args": {}}),
        json.dumps({"action": "done", "output": {"blog_post": "full text", "pdf_path": "/tmp/x.pdf", "summary": "s"}}),
    ])

    def fake_llm(messages, ctx=None):
        return next(outputs)

    agent = Agent(name="marketing_content", role="marketing", tools={
        "generate_pdf": lambda **kw: {"pdf_path": "/tmp/x.pdf"},
        "generate_reel_package": lambda **kw: {"ok": True},
        "generate_tiktok_package": lambda **kw: {"ok": True},
        "generate_meta_ad": lambda **kw: {"ok": True},
        "obsidian_log": lambda **kw: {"ok": True},
    })
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx(goal="write a blog post about our launch"))

    assert result.get("status") != "max_iterations_reached"
    assert result.get("blog_post") == "full text"


@pytest.mark.asyncio
async def test_marketing_content_social_mode_still_requires_full_package(mocker):
    """The default Mode F (no other mode's trigger phrase present) must keep
    requiring the full social-content-package tool set -- this is the one mode
    the original static required-tool set was actually correct for. Agent calls
    generate_pdf + obsidian_log but skips the reel/tiktok/meta_ad steps -- done
    must still be rejected for the missing social tools specifically."""
    done_call = json.dumps({"action": "done", "output": {"summary": "s"}})
    outputs = iter([
        json.dumps({"action": "tool", "tool": "generate_pdf", "args": {"title": "t", "sections": []}}),
        json.dumps({"action": "tool", "tool": "obsidian_log", "args": {}}),
    ] + [done_call] * 10)

    def fake_llm(messages, ctx=None):
        try:
            return next(outputs)
        except StopIteration:
            return done_call

    agent = Agent(name="marketing_content", role="marketing", max_iterations=5, tools={
        "generate_pdf": lambda **kw: {"pdf_path": "/tmp/x.pdf"},
        "generate_reel_package": lambda **kw: {"ok": True},
        "generate_tiktok_package": lambda **kw: {"ok": True},
        "generate_meta_ad": lambda **kw: {"ok": True},
        "obsidian_log": lambda **kw: {"ok": True},
    })
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx(goal="create launch assets for our new product"))

    assert result.get("status") == "max_iterations_reached"
    assert set(result.get("quality_flags", {}).get("missing_tools", [])) == {
        "generate_reel_package", "generate_tiktok_package", "generate_meta_ad",
    }

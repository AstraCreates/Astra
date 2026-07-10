import asyncio
import sys
import types
from unittest.mock import AsyncMock

import pytest

if "openai" not in sys.modules:
    _openai = types.ModuleType("openai")
    _openai.OpenAI = object
    _openai.RateLimitError = type("RateLimitError", (Exception,), {})
    _openai.APIResponseValidationError = type("APIResponseValidationError", (Exception,), {})
    _openai.APIError = type("APIError", (Exception,), {})
    _openai.APITimeoutError = type("APITimeoutError", (Exception,), {})
    _openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
    sys.modules["openai"] = _openai

from backend.core.agent import Agent, AgentContext
from backend.core.orchestrator import Orchestrator


class _FakePlanner:
    name = "planner"
    model = "test"

    def _call_llm(self, _messages, _ctx=None):
        return '{"tasks":[]}'


class _SlowAgent:
    def __init__(self, name: str, active: dict[str, int], peak: dict[str, int]):
        self.name = name
        self.tools = {}
        self._active = active
        self._peak = peak

    async def run(self, _ctx):
        self._active["count"] += 1
        self._peak["count"] = max(self._peak["count"], self._active["count"])
        try:
            await asyncio.sleep(0.05)
            return {"ok": True, "agent": self.name}
        finally:
            self._active["count"] -= 1


@pytest.mark.asyncio
async def test_execute_tool_times_out_and_returns_structured_error(mocker, monkeypatch):
    async def hanging_tool():
        await asyncio.sleep(1)

    monkeypatch.setattr("backend.core.agent._DEFAULT_TOOL_TIMEOUT_SECONDS", 0.01)
    agent = Agent(name="design", role="design", tools={"hang": hanging_tool})
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent._execute_tool(
        "hang",
        {},
        AgentContext(goal="g", founder_id="f1", session_id="s1", shared={}),
    )

    assert result == {"error": "Tool 'hang' timed out after 0.01s", "timed_out": True, "tool": "hang"}


@pytest.mark.asyncio
async def test_continue_run_respects_max_concurrent_agents(mocker, monkeypatch):
    active = {"count": 0}
    peak = {"count": 0}
    planner = _FakePlanner()
    specialists = {
        "legal": _SlowAgent("legal", active, peak),
        "sales": _SlowAgent("sales", active, peak),
        "design": _SlowAgent("design", active, peak),
    }
    orch = Orchestrator(planner=planner, specialists=specialists)
    monkeypatch.setenv("ASTRA_MAX_CONCURRENT_AGENTS_PER_SESSION", "2")

    mocker.patch("backend.core.events.publish", new=AsyncMock())
    mocker.patch.object(orch, "_llm_plan", new=AsyncMock(return_value=[
        {"id": "c1", "agent": "legal", "instruction": "a", "depends_on": []},
        {"id": "c2", "agent": "sales", "instruction": "b", "depends_on": []},
        {"id": "c3", "agent": "design", "instruction": "c", "depends_on": []},
    ]))
    mocker.patch("backend.tools.obsidian_logger.format_vault_context", return_value="")
    mocker.patch("backend.tools.company_brain.company_brain_context", return_value="")
    mocker.patch.object(orch, "_bootstrap_operating_after_run", new=AsyncMock())
    mocker.patch.object(orch, "_sync_session_deliverables", new=AsyncMock())
    mocker.patch.object(orch, "_publish_outcomes", new=AsyncMock())
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_backend_log", return_value=None)
    mocker.patch("backend.core.session_store.get_session_meta", return_value={})
    mocker.patch("backend.core.session_store.save_creative_brief", return_value=None)
    mocker.patch("backend.core.creative.build_creative_brief", return_value={})

    await orch._continue_run_inner(
        instruction="continue",
        founder_id="f1",
        prior_session_id="p1",
        agents=["legal", "sales", "design"],
        session_id="s1",
        exclude_agents=[],
        research_depth=None,
    )

    assert peak["count"] <= 2

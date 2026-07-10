from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.core.orchestrator import Orchestrator


class _FakePlanner:
    name = "planner"
    model = "test"

    def _call_llm(self, _messages, _ctx=None):
        return '{"tasks":[]}'


class _FakeAgent:
    def __init__(self, name, outputs):
        self.name = name
        self.outputs = list(outputs)
        self.tools = {}
        self.calls = 0
        self.model = "test"

    async def run(self, _ctx):
        self.calls += 1
        return self.outputs[min(self.calls - 1, len(self.outputs) - 1)]


@pytest.mark.asyncio
async def test_phase_gate_does_not_requeue_killed_agent(monkeypatch):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{}])
    design = _FakeAgent("design", [{"brand_direction": "ready"}])
    orch = Orchestrator(planner=planner, specialists={"research": research, "design": design})

    publish = AsyncMock()
    monkeypatch.setattr("backend.core.events.publish", publish)
    monkeypatch.setattr("backend.core.orchestrator.candidate_research_agents_for_default_provider", lambda: [("r_market", "research")])
    monkeypatch.setattr("backend.core.orchestrator.is_agent_killed", lambda session_id, agent_name: session_id == "s" and agent_name == "research")
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))
    monkeypatch.setattr(orch, "_generate_company_name", AsyncMock(return_value="Acme"))
    monkeypatch.setattr(orch, "_replan_with_research", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_generate_detailed_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_critical_research_review", AsyncMock(return_value={}))
    monkeypatch.setattr(orch, "_bootstrap_operating_after_run", AsyncMock())
    monkeypatch.setattr(orch, "_sync_session_deliverables", AsyncMock())
    monkeypatch.setattr("backend.tools.obsidian_logger.auto_log_if_missing", lambda *args, **kwargs: False)
    monkeypatch.setattr("backend.tools.obsidian_logger._note_path", lambda *args, **kwargs: Path("/tmp/nonexistent-note.md"))

    async def _fake_deep_verification(*, task, base_verdict, **_kwargs):
        verdict = dict(base_verdict)
        verdict.setdefault("task_id", task["id"])
        verdict.setdefault("agent", task["agent"])
        verdict.setdefault("summary", "Artifact verification did not pass.")
        verdict.setdefault("artifacts", [])
        return verdict

    monkeypatch.setattr("backend.stacks.run_deep_verification", _fake_deep_verification)

    await orch.run(goal="g", founder_id="f", session_id="s")

    assert research.calls == 1
    assert design.calls == 0
    blocked_events = [
        call.args[1]
        for call in publish.await_args_list
        if len(call.args) == 2
        and call.args[1].get("type") == "stack_lane_status"
        and call.args[1].get("agent") == "research"
        and call.args[1].get("status") == "blocked"
    ]
    assert any(event.get("next_actor") == "founder" for event in blocked_events)

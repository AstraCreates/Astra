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


@pytest.mark.asyncio
async def test_phase_gate_lets_downstream_proceed_on_bare_minimum_content(monkeypatch):
    """Very low bar for phase advancement: a task that didn't fully pass
    verification (status='needs_review') but has at least one 'weak' (present,
    thin) artifact should NOT block the whole phase — downstream departments
    should proceed on that thin output rather than stall the entire run
    waiting on one imperfect lane. Contrast with the 'genuinely nothing'
    case above (weak_count=0, passed_count=0), which still correctly blocks."""
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "thin but real findings"}])
    design = _FakeAgent("design", [{"brand_direction": "ready"}])
    orch = Orchestrator(planner=planner, specialists={"research": research, "design": design})

    publish = AsyncMock()
    monkeypatch.setattr("backend.core.events.publish", publish)
    monkeypatch.setattr("backend.core.orchestrator.candidate_research_agents_for_default_provider", lambda: [("r_market", "research")])
    monkeypatch.setattr("backend.core.orchestrator.is_agent_killed", lambda session_id, agent_name: False)
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))
    monkeypatch.setattr(orch, "_generate_company_name", AsyncMock(return_value="Acme"))
    monkeypatch.setattr(orch, "_replan_with_research", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_generate_detailed_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_critical_research_review", AsyncMock(return_value={}))
    monkeypatch.setattr(orch, "_bootstrap_operating_after_run", AsyncMock())
    monkeypatch.setattr(orch, "_sync_session_deliverables", AsyncMock())
    monkeypatch.setattr("backend.tools.obsidian_logger.auto_log_if_missing", lambda *args, **kwargs: False)
    monkeypatch.setattr("backend.tools.obsidian_logger._note_path", lambda *args, **kwargs: Path("/tmp/nonexistent-note.md"))
    # With zero gate_blockers the real _phase_gate falls through to the NORMAL
    # founder-approval checkpoint (create_approval_request + a 2hr wait) — a
    # deliberate feature, not part of what this test is verifying. Resolve it
    # immediately so the test isn't asserting on that unrelated wait.
    monkeypatch.setattr("backend.core.events.approval_decision_wait", AsyncMock(return_value={"decision": "approved"}))
    monkeypatch.setattr("backend.approval_workflows.create_approval_request", lambda **kwargs: None)

    async def _fake_deep_verification(*, task, base_verdict, **_kwargs):
        verdict = dict(base_verdict)
        verdict.setdefault("task_id", task["id"])
        verdict.setdefault("agent", task["agent"])
        verdict["status"] = "needs_review"
        verdict["passed_count"] = 0
        verdict["weak_count"] = 1  # barely enough — one thin-but-present artifact
        verdict["summary"] = "One weak artifact, did not fully pass."
        verdict.setdefault("artifacts", [])
        return verdict

    monkeypatch.setattr("backend.stacks.run_deep_verification", _fake_deep_verification)

    await orch.run(goal="g", founder_id="f", session_id="s")

    assert research.calls == 1  # research itself cleared the low bar, no retry
    # design's own fake output also isn't a full pass under the same fake
    # verification, so it may get revised/retried too (unrelated to what this
    # test verifies) — the only thing under test is that it ran AT ALL, which
    # would be impossible (calls == 0) if research's 'needs_review' had still
    # hard-blocked the whole phase the old way.
    assert design.calls > 0


@pytest.mark.asyncio
async def test_phase_gate_caps_non_research_automatic_revisions(monkeypatch):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "usable research"}])
    design = _FakeAgent("design", [{}])
    web = _FakeAgent("web", [{"url": "https://example.com"}])
    orch = Orchestrator(planner=planner, specialists={"research": research, "design": design, "web": web})

    publish = AsyncMock()
    monkeypatch.setenv("ASTRA_VERIFY_RETRIES", "0")
    monkeypatch.setenv("ASTRA_PHASE_AUTO_REVISIONS", "1")
    monkeypatch.setattr("backend.core.events.publish", publish)
    monkeypatch.setattr("backend.core.orchestrator.candidate_research_agents_for_default_provider", lambda: [("r_market", "research")])
    monkeypatch.setattr("backend.core.orchestrator.is_agent_killed", lambda *_args: False)
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))
    monkeypatch.setattr(orch, "_generate_company_name", AsyncMock(return_value="Acme"))
    monkeypatch.setattr(orch, "_replan_with_research", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_generate_detailed_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "_critical_research_review", AsyncMock(return_value={}))
    monkeypatch.setattr(orch, "_bootstrap_operating_after_run", AsyncMock())
    monkeypatch.setattr(orch, "_sync_session_deliverables", AsyncMock())
    monkeypatch.setattr("backend.tools.obsidian_logger.auto_log_if_missing", lambda *args, **kwargs: False)
    monkeypatch.setattr("backend.tools.obsidian_logger._note_path", lambda *args, **kwargs: Path("/tmp/nonexistent-note.md"))
    monkeypatch.setattr("backend.core.events.approval_decision_wait", AsyncMock(return_value={"decision": "approved"}))
    monkeypatch.setattr("backend.approval_workflows.create_approval_request", lambda **kwargs: None)

    async def _fake_deep_verification(*, task, base_verdict, **_kwargs):
        verdict = dict(base_verdict)
        verdict.update({
            "task_id": task["id"],
            "agent": task["agent"],
            "summary": "nothing produced" if task["agent"] == "design" else "usable",
            "status": "blocked" if task["agent"] == "design" else "passed",
            "passed_count": 0 if task["agent"] == "design" else 1,
            "weak_count": 0,
            "artifacts": [],
        })
        return verdict

    monkeypatch.setattr("backend.stacks.run_deep_verification", _fake_deep_verification)

    await orch.run(goal="g", founder_id="f", session_id="phase-revision-cap")

    assert research.calls == 1
    assert design.calls == 2
    design_blocked = [
        call.args[1]
        for call in publish.await_args_list
        if len(call.args) == 2
        and call.args[1].get("type") == "stack_lane_status"
        and call.args[1].get("agent") == "design"
        and call.args[1].get("status") == "blocked"
    ]
    assert design_blocked[-1]["next_actor"] == "founder"

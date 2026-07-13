import asyncio

import pytest

from backend.control_plane.temporal.contracts import DeepResearchInput
from backend.control_plane.temporal.execution import execute_deep_research


@pytest.mark.asyncio
async def test_execute_deep_research_returns_structured_result(monkeypatch):
    captured = {}

    def _fake_deep_research(query, focus="", cancellation_fence=None, run_id=None, step_id=None):
        captured["query"] = query
        captured["focus"] = focus
        captured["run_id"] = run_id
        captured["step_id"] = step_id
        return {
            "report": "ignored legacy field",
            "sources": [],
            "structured": {"query_id": "q1", "question": query, "claims": [], "evidence": []},
        }

    monkeypatch.setattr("backend.tools.web_search.deep_research", _fake_deep_research)

    result = await execute_deep_research(
        DeepResearchInput(run_id="run_1", step_id="step_1", query_id="q1"),
        get_session_meta_fn=lambda _run_id: {
            "deep_research_queries": {"q1": {"query": "TAM for widget SaaS", "focus": "pricing"}},
        },
    )

    assert result["status"] == "completed"
    assert result["structured"]["question"] == "TAM for widget SaaS"
    assert captured["query"] == "TAM for widget SaaS"
    assert captured["focus"] == "pricing"
    assert captured["run_id"] == "run_1"
    assert captured["step_id"] == "step_1"


@pytest.mark.asyncio
async def test_execute_deep_research_errors_when_query_not_found():
    result = await execute_deep_research(
        DeepResearchInput(run_id="run_1", step_id="step_1", query_id="missing"),
        get_session_meta_fn=lambda _run_id: {"deep_research_queries": {}},
    )
    assert result["status"] == "error"
    assert "missing" in result["error"]


@pytest.mark.asyncio
async def test_execute_deep_research_reports_cancelled_when_deep_research_self_detects_it(monkeypatch):
    # The common/fast cancellation path: deep_research() itself checks
    # cancellation_fence.is_set() at its own checkpoints (per-model attempt,
    # per-angle search) and returns {"error": "cancelled"} well before the
    # outer poll loop's own fence check would ever fire. execute_deep_research
    # must surface that as status="cancelled", not silently report "completed"
    # with an empty structured result (this was a real bug caught while
    # writing this test -- see the raw_result.get("error") == "cancelled"
    # check added alongside it).
    def _fake_deep_research(query, focus="", cancellation_fence=None, run_id=None, step_id=None):
        assert cancellation_fence is not None
        return {"query": query, "report": "", "sources": [], "error": "cancelled"}

    monkeypatch.setattr("backend.tools.web_search.deep_research", _fake_deep_research)

    result = await execute_deep_research(
        DeepResearchInput(run_id="run_1", step_id="step_1", query_id="q1"),
        get_session_meta_fn=lambda _run_id: {
            "deep_research_queries": {"q1": {"query": "cancelled query"}},
        },
    )
    assert result["status"] == "cancelled"
    assert result["structured"] == {}


@pytest.mark.asyncio
async def test_execute_deep_research_outer_loop_cancels_stuck_task(monkeypatch):
    # The fallback path: deep_research() is stuck on something that doesn't
    # check the fence (e.g. blocked in a network call), so the outer poll
    # loop's own fence.is_set() check has to force-cancel the asyncio task
    # rather than waiting for deep_research to notice on its own.
    import backend.control_plane.temporal.execution as execution_mod

    def _stuck_deep_research(query, focus="", cancellation_fence=None, run_id=None, step_id=None):
        import time
        time.sleep(0.05)  # short and deterministic -- nothing left orphaned once this returns
        return {"structured": {"question": query}}

    monkeypatch.setattr("backend.tools.web_search.deep_research", _stuck_deep_research)

    class _ImmediatelyCancelledFence:
        def is_set(self) -> bool:
            return True

    monkeypatch.setattr(execution_mod, "_CancelledFence", lambda: _ImmediatelyCancelledFence())

    result = await execute_deep_research(
        DeepResearchInput(run_id="run_1", step_id="step_1", query_id="q1"),
        get_session_meta_fn=lambda _run_id: {
            "deep_research_queries": {"q1": {"query": "stuck query"}},
        },
    )
    assert result["status"] == "cancelled"

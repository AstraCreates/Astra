from unittest.mock import AsyncMock

import pytest

from backend.config import settings
from backend.core.orchestrator import Orchestrator, candidate_research_agents_for_default_provider


class _FakePlanner:
    name = "planner"
    model = "planner-test"


class _FakeAgent:
    def __init__(self, name, outputs):
        self.name = name
        self.outputs = list(outputs)
        self.tools = {}
        self.calls = 0

    async def run(self, _ctx):
        self.calls += 1
        return self.outputs[min(self.calls - 1, len(self.outputs) - 1)]


@pytest.mark.asyncio
async def test_orchestrator_adds_lane_specific_focus_to_initial_research_tasks(monkeypatch):
    planner = _FakePlanner()
    orch = Orchestrator(
        planner=planner,
        specialists={
            "research": _FakeAgent("research", [{"summary": "researched"}]),
            "research_competitors": _FakeAgent("research_competitors", [{"summary": "competitors"}]),
            "research_gtm": _FakeAgent("research_gtm", [{"summary": "gtm"}]),
            "web": _FakeAgent("web", [{"url": "https://example.com"}]),
        },
    )

    published: list[dict] = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    monkeypatch.setattr("backend.core.events.publish", capture_publish)
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))
    monkeypatch.setattr(orch, "_initial_plan", AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    monkeypatch.setattr(orch, "_replan_with_research", AsyncMock(return_value=[{"id": "w1", "agent": "web", "instruction": "w", "depends_on": []}]))
    monkeypatch.setattr(orch, "_generate_detailed_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr("backend.tools.obsidian_logger._note_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("backend.tools.obsidian_logger.auto_log_if_missing", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("backend.tools.obsidian_logger.obsidian_session_index", lambda *_args, **_kwargs: {"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")

    first_plan = next(event for event in published if event.get("type") == "plan_done")
    tasks_by_agent = {task["agent"]: task for task in first_plan.get("tasks", [])}
    assert "named competitors only" in tasks_by_agent["research_competitors"]["instruction"]
    assert "go-to-market and distribution only" in tasks_by_agent["research_gtm"]["instruction"]


def test_candidate_research_agents_keep_parallel_openrouter_default_even_if_local_endpoint_exists(monkeypatch):
    monkeypatch.setattr(settings, "research_default_provider", "openrouter")
    monkeypatch.setattr(settings, "local_research_base_url", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "local_research_model", "qwen-local")

    assert candidate_research_agents_for_default_provider() == [
        ("r_market", "research"),
        ("r_competitors", "research_competitors"),
        ("r_customers", "research_customers"),
        ("r_gtm", "research_gtm"),
    ]

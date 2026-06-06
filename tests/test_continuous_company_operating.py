import asyncio
import sys
import types
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


def test_company_goal_and_task_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.missions.company_goal import get_company_goal, upsert_company_goal
    from backend.missions.store import create_mission, bulk_upsert_tasks, list_tasks, update_task

    goal = upsert_company_goal(
        "founder_test",
        north_star="Reach weekly active customers",
        company_goal="Operate the company against the weekly active customer goal.",
        source_session_id="sess_1",
        kpis=[{"key": "wac", "label": "Weekly active customers", "target": "100"}],
    )
    assert goal["status"] == "operating"
    assert get_company_goal("founder_test")["north_star"] == "Reach weekly active customers"

    mission = create_mission(
        founder_id="founder_test",
        department="research",
        name="Market truth",
        goal="Keep the market truth current.",
        primary_metric="Weekly active customers",
        objectives=["Refresh segment assumptions"],
        budget={"max_runs_per_day": 2, "max_cost_usd_per_run": 1.0},
        approval_policy="auto",
    )
    tasks = bulk_upsert_tasks(
        mission["id"],
        [
            {"id": "t_root", "title": "Refresh ICP assumptions", "status": "pending", "notes": "Review latest signals"},
            {"id": "t_child", "title": "Interview follow-up", "status": "blocked", "parent_id": "t_root", "notes": "Need founder intro"},
        ],
    )
    assert len(tasks) == 2
    updated = update_task(mission["id"], "t_root", status="done", notes="Closed")
    assert updated["status"] == "done"
    assert any(task["parent_id"] == "t_root" for task in list_tasks(mission["id"]))


def test_bootstrap_operating_system_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.missions.bootstrap import bootstrap_company_operating_system
    from backend.missions.company_goal import get_company_goal
    from backend.missions.store import list_missions

    monkeypatch.setattr(
        "backend.tools.notion_sync.sync_founder_operating_system",
        lambda founder_id: {"ok": False, "skipped": True, "founder_id": founder_id},
    )

    state = {
        "operating_plan": {"outcome": "Launch and operate"},
        "execution_contract": {
            "north_star": "Turn launch outputs into weekly execution.",
            "kpis": [{"key": "pipeline", "label": "Pipeline", "target": "10 meetings"}],
        },
        "workboard": {
            "items": [
                {
                    "agent": "research",
                    "title": "Research cadence",
                    "mission": "Maintain market truth.",
                    "status": "done",
                    "summary": "Initial market map complete.",
                    "ready_artifacts": [{"title": "Market brief"}],
                    "blockers": [],
                    "steps": ["Refresh assumptions weekly"],
                }
            ]
        },
        "digest": {"next_actions": ["Schedule five interviews"]},
        "company_genome": {"company_name": "Astra"},
    }

    first = bootstrap_company_operating_system("session_1", "founder_test", goal="Launch Astra", state=state)
    second = bootstrap_company_operating_system("session_1", "founder_test", goal="Launch Astra", state=state)

    assert first["mission_count"] == 1
    assert second["mission_count"] == 1
    missions = list_missions("founder_test")
    assert len(missions) == 1
    assert len(missions[0]["tasks"]) == len({task["id"] for task in missions[0]["tasks"]})
    assert get_company_goal("founder_test")["source_session_id"] == "session_1"


@pytest.mark.asyncio
async def test_run_mission_injects_company_goal_and_reconciles_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.missions.company_goal import upsert_company_goal
    from backend.missions.store import create_mission, bulk_upsert_tasks, get_mission
    from backend.missions.runner import run_mission

    upsert_company_goal(
        "founder_test",
        north_star="Grow weekly active customers",
        company_goal="Keep every lane moving toward weekly active customers.",
        source_session_id="seed_session",
        kpis=[{"label": "Weekly active customers", "target": "100"}],
    )
    mission = create_mission(
        founder_id="founder_test",
        department="research",
        name="Customer truth",
        goal="Refresh market assumptions weekly.",
        primary_metric="Weekly active customers",
        objectives=["Talk to current users"],
        budget={"max_runs_per_day": 2, "max_cost_usd_per_run": 1.0},
        approval_policy="auto",
    )
    bulk_upsert_tasks(mission["id"], [{"id": "open_1", "title": "Review churn themes", "status": "pending", "notes": "Look at latest calls"}])

    captured = {}

    class FakeAgent:
        async def run(self, ctx):
            captured["goal"] = ctx.goal
            return {
                "summary": "Reviewed churn themes and queued a retention experiment.",
                "next_tasks": [{"title": "Draft retention experiment", "notes": "Turn themes into a test"}],
            }

    class FakeOrchestrator:
        specialists = {"research": FakeAgent()}

    monkeypatch.setitem(sys.modules, "backend.core.factory", types.SimpleNamespace(get_orchestrator=lambda: FakeOrchestrator()))
    monkeypatch.setitem(sys.modules, "backend.core.session_store", types.SimpleNamespace(register_session=lambda **kwargs: None))
    monkeypatch.setattr("backend.tools.notion_sync.sync_founder_operating_system", lambda founder_id: {"ok": False, "skipped": True, "founder_id": founder_id})

    result = await run_mission(mission["id"], session_id="mission_session")

    assert result["success"] is True
    assert "NORTH STAR" in captured["goal"]
    refreshed = get_mission(mission["id"])
    statuses = {task["id"]: task["status"] for task in refreshed["tasks"]}
    assert statuses["open_1"] == "done"
    assert any("retention experiment" in task["title"].lower() for task in refreshed["tasks"])


@pytest.mark.asyncio
async def test_missions_api_supports_company_goal_and_task_patch(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.missions.company_goal import upsert_company_goal
    from backend.missions.store import create_mission, bulk_upsert_tasks

    upsert_company_goal(
        "founder_test",
        north_star="North star",
        company_goal="Operate continuously",
        source_session_id="sess_api",
    )
    mission = create_mission(
        founder_id="founder_test",
        department="ops",
        name="Operating cadence",
        goal="Run weekly review.",
        primary_metric="Execution tempo",
        objectives=[],
        budget={"max_runs_per_day": 2, "max_cost_usd_per_run": 1.0},
        approval_policy="auto",
    )
    bulk_upsert_tasks(mission["id"], [{"id": "task_1", "title": "Run weekly review", "status": "pending", "notes": ""}])

    monkeypatch.setattr("backend.tools.notion_sync.sync_founder_operating_system", lambda founder_id: {"ok": True, "founder_id": founder_id})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        goal_response = await client.get("/api/missions/company-goal", params={"founder_id": "founder_test"})
        patch_response = await client.patch(f"/api/missions/{mission['id']}/tasks/task_1", json={"status": "done", "notes": "Closed in review"})
        sync_response = await client.post("/api/missions/sync-notion", json={"founder_id": "founder_test"})

    assert goal_response.status_code == 200
    assert goal_response.json()["company_goal"]["company_goal"] == "Operate continuously"
    assert patch_response.status_code == 200
    assert patch_response.json()["task"]["status"] == "done"
    assert sync_response.status_code == 200
    assert sync_response.json()["ok"] is True


@pytest.mark.asyncio
async def test_orchestrator_starts_operating_bootstrap_after_goal_done(monkeypatch):
    from backend.core.orchestrator import Orchestrator

    class Planner:
        name = "planner"
        model = "test"

        def _call_llm(self, _messages):
            return '{"tasks":[]}'

    class Agent:
        def __init__(self, output):
            self.output = output
            self.tools = {}
            self.name = "agent"

        async def run(self, _ctx):
            return self.output

    planner = Planner()
    web = Agent({"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"})
    orch = Orchestrator(planner=planner, specialists={"web": web})

    published = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    bootstrap_mock = AsyncMock()
    monkeypatch.setattr("backend.core.events.publish", capture_publish)
    monkeypatch.setattr(orch, "_bootstrap_operating_after_run", bootstrap_mock)
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))

    with patch("backend.tools.obsidian_logger._note_path"), \
         patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False), \
         patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True}):
        await orch.run(goal="g", founder_id="f", session_id="s", constraints={"agents": ["web"], "bypass_planner": True})
        await asyncio.sleep(0)

    assert any(event.get("type") == "goal_done" for event in published)
    bootstrap_mock.assert_awaited()

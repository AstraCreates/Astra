import json
import sys
import time
import types

import pytest

from backend.missions.company_goal import budget_allows, chain_allowed
from backend.missions.goal_engine import _running_session_is_fresh, dispatch_current_goal
from backend.missions.runner import _reconcile_tasks


def _write_meta(meta_path, session_id, *, status="running", created_at=None, founder_id="founder", company_id="company"):
    meta_path(session_id).write_text(json.dumps({
        "session_id": session_id,
        "founder_id": founder_id,
        "company_id": company_id,
        "status": status,
        "created_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }))


def _write_goal(company_goal, *, root_session_id="", operating_sessions=None):
    goal = {
        "founder_id": "founder",
        "company_id": "company",
        "status": "operating",
        "root_session_id": root_session_id,
        "current_goal_id": "goal_1",
        "budget": {"max_runs_per_day": 12},
        "goals": [
            {
                "id": "goal_1",
                "title": "Ship the current goal",
                "status": "active",
                "tasks": [
                    {
                        "id": "task_1",
                        "title": "Complete the main task",
                        "status": "pending",
                        "owner_agents": ["research"],
                    },
                ],
            },
        ],
        "operating_sessions": list(operating_sessions or []),
    }
    company_goal._save(goal)
    return goal


def test_budget_root_cap_ignores_runs_before_current_launch_window():
    goal = {
        "created_at": "2026-01-01T00:00:00Z",
        "root_session_id": "new_root_without_meta",
        "budget": {
            "max_runs_per_day": 12,
            "max_chained_runs_per_root_session": 2,
        },
        "goals": [
            {"kind": "launch", "created_at": "2026-07-06T00:00:00Z"},
        ],
        "operating_sessions": [
            {"session_id": "old_1", "started_at": "2026-01-02T00:00:00Z"},
            {"session_id": "old_2", "started_at": "2026-01-03T00:00:00Z"},
            {"session_id": "new_1", "started_at": "2026-07-06T01:00:00Z"},
        ],
    }

    assert budget_allows(goal) is True
    assert chain_allowed(goal) is True


def test_budget_root_cap_counts_current_window_runs():
    goal = {
        "created_at": "2026-07-06T00:00:00Z",
        "budget": {
            "max_runs_per_day": 12,
            "max_chained_runs_per_root_session": 2,
        },
        "operating_sessions": [
            {"session_id": "run_1", "started_at": "2026-07-06T01:00:00Z"},
            {"session_id": "run_2", "started_at": "2026-07-06T02:00:00Z"},
        ],
    }

    assert budget_allows(goal) is False
    assert chain_allowed(goal) is False


def test_budget_daily_cap_still_blocks_today():
    today = time.strftime("%Y-%m-%d", time.gmtime())
    goal = {
        "created_at": "2026-01-01T00:00:00Z",
        "budget": {
            "max_runs_per_day": 1,
            "max_chained_runs_per_root_session": 20,
        },
        "operating_sessions": [
            {"session_id": "today_1", "started_at": f"{today}T01:00:00Z"},
        ],
    }

    assert budget_allows(goal) is False


def test_budget_root_cap_counts_malformed_timestamps_conservatively():
    goal = {
        "created_at": "2026-07-06T00:00:00Z",
        "budget": {
            "max_runs_per_day": 12,
            "max_chained_runs_per_root_session": 2,
        },
        "operating_sessions": [
            {"session_id": "old_1", "started_at": "2026-01-02T00:00:00Z"},
            {"session_id": "bad_1", "started_at": "not-a-timestamp"},
            {"session_id": "bad_2", "started_at": ""},
        ],
    }

    assert budget_allows(goal) is False
    assert chain_allowed(goal) is False


def test_running_session_is_fresh_honors_stale_cutoff(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("ASTRA_RUN_STALE_SECONDS", "10")

    from backend.core.session_store import meta_path

    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30))
    meta_path("stale_root").write_text(json.dumps({
        "session_id": "stale_root",
        "founder_id": "founder",
        "status": "running",
        "created_at": stale,
    }))

    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta_path("fresh_root").write_text(json.dumps({
        "session_id": "fresh_root",
        "founder_id": "founder",
        "status": "running",
        "created_at": fresh,
    }))

    assert _running_session_is_fresh("stale_root") is False
    assert _running_session_is_fresh("fresh_root") is True


def test_reconcile_tasks_does_not_create_synthetic_followup_task():
    mission = {
        "id": "mission_1",
        "department": "research",
        "approval_policy": "auto",
        "last_run_at": "2026-07-06T00:00:00Z",
        "tasks": [
            {"id": "task_1", "title": "Interview customers", "status": "pending"},
        ],
    }
    result = {"summary": "Finished the customer interview batch."}

    tasks = _reconcile_tasks(mission, result, "session_1")

    assert [task["id"] for task in tasks] == ["task_1"]
    assert tasks[0]["status"] == "done"


@pytest.mark.asyncio
async def test_dispatch_current_goal_ignores_stale_running_root_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("ASTRA_RUN_STALE_SECONDS", "10")

    from backend.core.session_store import meta_path
    from backend.missions import company_goal

    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30))
    _write_meta(meta_path, "root_session", created_at=stale)
    _write_goal(company_goal, root_session_id="root_session")

    calls = []

    class FakeOrchestrator:
        async def continue_run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "backend.core.events",
        types.SimpleNamespace(register_parent_session=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.factory",
        types.SimpleNamespace(get_orchestrator=lambda: FakeOrchestrator()),
    )

    result = await dispatch_current_goal("founder", "company", _pre_session_id="new_session")

    saved = company_goal.get_company_goal("founder", "company")
    assert result == {"ok": True, "session_id": "new_session"}
    assert calls and calls[0]["session_id"] == "new_session"
    assert saved["operating_sessions"][-1]["session_id"] == "new_session"
    assert saved["operating_sessions"][-1]["status"] == "done"


@pytest.mark.asyncio
async def test_dispatch_current_goal_skips_fresh_duplicate_running_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("ASTRA_RUN_STALE_SECONDS", "60")

    from backend.core.session_store import meta_path
    from backend.missions import company_goal

    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_meta(meta_path, "existing_session", created_at=fresh)
    _write_goal(
        company_goal,
        operating_sessions=[
            {
                "session_id": "existing_session",
                "started_at": fresh,
                "status": "running",
                "goal_id": "goal_1",
            },
        ],
    )

    class FakeOrchestrator:
        async def continue_run(self, **_kwargs):
            raise AssertionError("duplicate dispatch should not start orchestrator")

    result = await dispatch_current_goal("founder", "company", _pre_session_id="new_session")

    saved = company_goal.get_company_goal("founder", "company")
    assert result == {"ok": True, "skipped": "already_running", "session_id": "existing_session"}
    assert [rec["session_id"] for rec in saved["operating_sessions"]] == ["existing_session"]


@pytest.mark.asyncio
async def test_dispatch_current_goal_budget_check_and_reservation_use_goal_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.missions import company_goal

    _write_goal(company_goal)
    budget_checked_under_lock = False
    reservation_seen_before_orchestrator = False

    def fake_budget_allows(_goal):
        nonlocal budget_checked_under_lock
        budget_checked_under_lock = company_goal._goal_lock("founder", "company")._is_owned()
        return True

    class FakeOrchestrator:
        async def continue_run(self, **kwargs):
            nonlocal reservation_seen_before_orchestrator
            saved = company_goal.get_company_goal("founder", "company")
            reservation_seen_before_orchestrator = any(
                rec.get("session_id") == kwargs["session_id"] and rec.get("status") == "running"
                for rec in saved.get("operating_sessions") or []
            )

    monkeypatch.setattr(company_goal, "budget_allows", fake_budget_allows)
    monkeypatch.setitem(
        sys.modules,
        "backend.core.events",
        types.SimpleNamespace(register_parent_session=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.factory",
        types.SimpleNamespace(get_orchestrator=lambda: FakeOrchestrator()),
    )

    result = await dispatch_current_goal("founder", "company", _pre_session_id="reserved_session")

    assert result == {"ok": True, "session_id": "reserved_session"}
    assert budget_checked_under_lock is True
    assert reservation_seen_before_orchestrator is True


@pytest.mark.asyncio
async def test_scheduler_does_not_redispatch_stalled_active_goal(monkeypatch):
    from backend.missions import company_goal, scheduler
    from backend.core import session_store

    goal_doc = {
        "founder_id": "founder",
        "company_id": "company",
        "status": "operating",
        "budget": {"max_runs_per_day": 12},
        "operating_sessions": [],
        "current_goal_id": "goal_1",
    }
    current = {
        "id": "goal_1",
        "status": "active",
        "tasks": [{"id": "task_1", "status": "pending"}],
    }
    calls = []

    monkeypatch.setattr(company_goal, "list_company_goals", lambda: [goal_doc])
    monkeypatch.setattr(company_goal, "reconcile_operating_sessions", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(session_store, "has_active_run", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(company_goal, "current_goal", lambda *_args, **_kwargs: current)
    monkeypatch.setattr(company_goal, "_goal_is_complete", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(company_goal, "chain_allowed", lambda *_args, **_kwargs: True)

    async def fake_dispatch(founder_id, company_id):
        calls.append((founder_id, company_id))
        return {"ok": True, "session_id": "session_1"}

    monkeypatch.setattr("backend.missions.goal_engine.dispatch_current_goal", fake_dispatch)

    dispatched = await scheduler._scheduler_tick()

    assert dispatched == 0
    assert calls == []


@pytest.mark.asyncio
async def test_scheduler_recovers_missing_next_goal_proposal_without_redispatch(monkeypatch):
    from backend.missions import company_goal, scheduler
    from backend.core import session_store

    goal_doc = {
        "founder_id": "founder",
        "company_id": "company",
        "status": "operating",
        "budget": {"max_runs_per_day": 12},
        "operating_sessions": [
            {"session_id": "session_1", "goal_id": "goal_1", "started_at": "2026-07-06T00:00:00Z"},
        ],
        "current_goal_id": "goal_1",
    }
    current = {
        "id": "goal_1",
        "status": "done",
        "tasks": [{"id": "task_1", "status": "done"}],
    }
    plan_calls = []
    dispatch_calls = []

    monkeypatch.setattr(company_goal, "list_company_goals", lambda: [goal_doc])
    monkeypatch.setattr(company_goal, "reconcile_operating_sessions", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(session_store, "has_active_run", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(company_goal, "current_goal", lambda *_args, **_kwargs: current)
    monkeypatch.setattr(company_goal, "_goal_is_complete", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(company_goal, "chain_allowed", lambda *_args, **_kwargs: True)

    def fake_plan_next_goal(founder_id, company_id):
        plan_calls.append((founder_id, company_id))
        return {"ok": True}

    monkeypatch.setattr("backend.missions.goal_engine.plan_next_goal", fake_plan_next_goal)

    async def fake_dispatch(founder_id, company_id):
        dispatch_calls.append((founder_id, company_id))
        return {"ok": True, "session_id": "session_2"}

    monkeypatch.setattr("backend.missions.goal_engine.dispatch_current_goal", fake_dispatch)

    dispatched = await scheduler._scheduler_tick()

    assert dispatched == 1
    assert plan_calls == [("founder", "company")]
    assert dispatch_calls == []


def test_get_missions_due_for_run_uses_per_founder_lock(tmp_path, monkeypatch):
    from backend.missions import store

    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    mission = store.create_mission(
        founder_id="founder",
        company_id="company",
        department="research",
        name="Research",
        goal="Learn",
        primary_metric="Interviews",
        objectives=[],
        budget={"max_runs_per_day": 1},
        approval_policy="auto",
    )

    due = store.get_missions_due_for_run()

    assert [item["id"] for item in due] == [mission["id"]]

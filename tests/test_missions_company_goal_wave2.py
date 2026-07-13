import pytest

from backend.api import missions_routes


@pytest.mark.asyncio
async def test_run_company_cycle_delegates_launch_to_goal_engine(monkeypatch):
    monkeypatch.setattr(missions_routes, "_require_company_access", lambda request, founder_id, company_id="", min_role="viewer": "company_1")
    monkeypatch.setattr("backend.missions.company_goal.get_company_goal", lambda founder_id, company_id: {"status": "operating", "root_session_id": "root_1"})
    monkeypatch.setattr("backend.missions.company_goal.current_goal", lambda founder_id, company_id: {"status": "active", "title": "Ship it"})
    monkeypatch.setattr("backend.missions.company_goal.reconcile_operating_sessions", lambda *args, **kwargs: 0)
    monkeypatch.setattr("backend.core.session_store.has_active_run", lambda *args, **kwargs: False)

    launch_calls = []

    def fake_launch(founder_id, company_id=None):
        launch_calls.append((founder_id, company_id))
        return {"ok": True, "session_id": "goal_run_1"}

    monkeypatch.setattr("backend.missions.goal_engine.launch_current_goal_dispatch", fake_launch)

    result = await missions_routes.run_company_cycle(request=object(), background_tasks=None, founder_id="founder_1", company_id="company_1")

    assert result == {"ok": True, "session_id": "goal_run_1", "parent_session_id": "root_1"}
    assert launch_calls == [("founder_1", "company_1")]


@pytest.mark.asyncio
async def test_approve_next_goal_delegates_launch_to_goal_engine(monkeypatch):
    body = missions_routes.ApproveNextGoalBody(founder_id="founder_1", company_id="company_1", approved=True)

    monkeypatch.setattr(missions_routes, "_require_company_access", lambda request, founder_id, company_id="", min_role="viewer": "company_1")
    monkeypatch.setattr("backend.missions.company_goal.approve_current_goal", lambda founder_id, company_id: {"id": "goal_1", "root_session_id": "root_1"})
    monkeypatch.setattr("backend.missions.company_goal.reject_current_goal", lambda *args, **kwargs: False)
    monkeypatch.setattr("backend.missions.company_goal.reconcile_operating_sessions", lambda *args, **kwargs: 0)
    monkeypatch.setattr("backend.core.session_store.has_active_run", lambda *args, **kwargs: False)

    launch_calls = []

    def fake_launch(founder_id, company_id=None):
        launch_calls.append((founder_id, company_id))
        return {"ok": True, "session_id": "goal_run_2"}

    monkeypatch.setattr("backend.missions.goal_engine.launch_current_goal_dispatch", fake_launch)

    result = await missions_routes.approve_next_goal(body=body, background_tasks=None, request=object())

    assert result["ok"] is True
    assert result["session_id"] == "goal_run_2"
    assert launch_calls == [("founder_1", "company_1")]

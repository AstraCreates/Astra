from types import SimpleNamespace

import pytest

from backend.api import missions_routes


@pytest.mark.asyncio
async def test_run_mission_route_registers_background_run_then_schedules_runner(monkeypatch):
    mission = {
        "id": "mission_1",
        "founder_id": "founder_1",
        "company_id": "company_1",
        "department": "research",
        "goal": "Validate demand",
        "status": "active",
        "name": "Demand validation",
    }
    scheduled = []

    class _BG:
        def add_task(self, fn, *args, **kwargs):
            scheduled.append((fn, args, kwargs))

    async def fake_register_background_run(**kwargs):
        return SimpleNamespace(run_id="run_mission_1", session_id="run_mission_1", status="running")

    monkeypatch.setattr(missions_routes, "_mission_for_request", lambda request, mission_id, min_role="viewer": mission)
    monkeypatch.setattr("backend.control_plane.start_run.register_background_run", fake_register_background_run)
    monkeypatch.setattr("backend.missions.runner.run_mission", lambda *args, **kwargs: None)

    result = await missions_routes.run_mission("mission_1", _BG(), request=object())

    assert result == {"ok": True, "session_id": "run_mission_1", "run_id": "run_mission_1", "status": "running"}
    assert scheduled
    _, args, kwargs = scheduled[0]
    assert kwargs["mission_id"] == "mission_1"
    assert kwargs["session_id"] == "run_mission_1"
    assert kwargs["skip_session_registration"] is True

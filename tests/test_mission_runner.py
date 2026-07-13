import sys
import types

import pytest

from backend.missions.runner import run_mission


@pytest.mark.asyncio
async def test_run_mission_uses_supplied_session_id_when_load_fails(monkeypatch):
    store = types.ModuleType("backend.missions.store")

    def get_mission(_mission_id):
        raise RuntimeError("store unavailable")

    store.append_progress_note = lambda *args, **kwargs: None
    store.get_mission = get_mission
    store.increment_run_count = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "backend.missions.store", store)

    result = await run_mission("mission_123", session_id="session_fixed")

    assert result["success"] is False
    assert result["session_id"] == "session_fixed"
    assert "store unavailable" in result["summary"]


@pytest.mark.asyncio
async def test_run_mission_emits_session_events(monkeypatch):
    store = types.ModuleType("backend.missions.store")
    store.append_progress_note = lambda *args, **kwargs: None
    store.get_mission = lambda _mission_id: {
        "id": "mission_123",
        "founder_id": "founder_1",
        "company_id": "company_1",
        "department": "research",
        "name": "Research mission",
        "goal": "Do research",
        "tasks": [{"id": "task_1", "title": "Task", "status": "pending"}],
    }
    store.increment_run_count = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "backend.missions.store", store)

    monkeypatch.setitem(sys.modules, "backend.missions.company_goal", types.SimpleNamespace(get_company_goal=lambda *_a, **_k: {}))

    class FakeAgent:
        async def run(self, ctx):
            return {"summary": "done", "completed_tasks": ["task_1"]}

    class FakeOrchestrator:
        specialists = {"research": FakeAgent()}

    monkeypatch.setitem(sys.modules, "backend.core.factory", types.SimpleNamespace(get_orchestrator=lambda: FakeOrchestrator()))
    monkeypatch.setitem(sys.modules, "backend.core.session_store", types.SimpleNamespace(register_session=lambda **kwargs: None))
    monkeypatch.setitem(sys.modules, "backend.tools.obsidian_logger", types.SimpleNamespace(format_vault_context=lambda *_a, **_k: "", auto_log_if_missing=lambda *_a, **_k: None))
    monkeypatch.setitem(sys.modules, "backend.tools.notion_sync", types.SimpleNamespace(sync_founder_operating_system=lambda *_a, **_k: {"ok": True}))
    monkeypatch.setitem(sys.modules, "backend.core.agent", types.SimpleNamespace(AgentContext=lambda **kwargs: types.SimpleNamespace(**kwargs)))

    events = []

    async def fake_publish(session_id, event):
        events.append((session_id, event))

    monkeypatch.setitem(sys.modules, "backend.core.events", types.SimpleNamespace(publish=fake_publish))

    result = await run_mission("mission_123", session_id="mission_sess", skip_session_registration=True)

    assert result["success"] is True
    assert [event["type"] for _, event in events] == ["agent_start", "agent_done", "goal_done"]

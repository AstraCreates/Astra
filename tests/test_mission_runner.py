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

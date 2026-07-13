from types import SimpleNamespace

import asyncio
import pytest

from backend.api.schemas import RunCreateRequest
from backend.control_plane import start_run as start_run_mod


class _FakeReservation:
    def __init__(self, reservation_id: str):
        self.id = reservation_id


@pytest.mark.asyncio
async def test_start_run_reserves_initial_budget_and_marks_running(monkeypatch):
    reserve_calls = []
    field_updates = []
    registered = []

    async def fake_create_run_with_event(run, *, event_type="run.created", payload=None):
        registered.append((run, event_type, payload))

    class _BudgetService:
        def reserve(self, **kwargs):
            reserve_calls.append(kwargs)
            return _FakeReservation("res-start")

    class _FakeOrchestrator:
        async def run(self, **_kwargs):
            return {"ok": True}

    created_tasks = []

    real_create_task = asyncio.create_task

    def fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(start_run_mod, "screen_goal", lambda _goal: (True, ""))
    monkeypatch.setattr(start_run_mod, "_analyze_goal", lambda _goal: ("", ""))
    monkeypatch.setattr(start_run_mod, "assign_run_features", lambda *_a, **_k: {"engine": "legacy"})
    monkeypatch.setattr(start_run_mod, "get_default_budget_service", lambda: _BudgetService())
    monkeypatch.setattr(start_run_mod, "get_balance", lambda _founder_id: 100)
    monkeypatch.setattr(start_run_mod, "get_orchestrator", lambda: _FakeOrchestrator())
    monkeypatch.setattr(start_run_mod, "durable_create_run_with_event", fake_create_run_with_event)
    async def fake_update_run_fields(run_id, patch):
        field_updates.append((run_id, patch))

    monkeypatch.setattr(start_run_mod, "_update_run_fields", fake_update_run_fields)
    monkeypatch.setattr(start_run_mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda _founder_id: {"org_id": "org_1", "plan": "starter", "entitlements": {"remaining_runs": 10}})
    monkeypatch.setattr("backend.accounts.record_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.session_store.register_session", lambda **kwargs: None)
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.events._get_queue", lambda _sid: None)
    monkeypatch.setattr("backend.core.cancellation.register_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.cancellation.clear", lambda *args, **kwargs: None)

    body = RunCreateRequest(founder_id="founder_1", instruction="Build the app", constraints={})
    result = await start_run_mod.start_run(body, request=None, run_id="run_wave2")

    assert result.status == "running"
    assert reserve_calls and reserve_calls[0]["run_id"] == "run_wave2"
    assert reserve_calls[0]["estimated_max_usd"] == pytest.approx(0.10)
    run, event_type, payload = registered[0]
    assert run.metadata["initial_budget_reservation_id"] == "res-start"
    assert event_type == "run.created"
    assert payload["run_id"] == "run_wave2"
    assert any(patch["status"] == "running" for _, patch in field_updates)

    for task in created_tasks:
        task.cancel()


@pytest.mark.asyncio
async def test_start_run_returns_queued_when_dispatch_cannot_schedule(monkeypatch):
    field_updates = []

    async def fake_create_run_with_event(run, *, event_type="run.created", payload=None):
        return None

    class _BudgetService:
        def reserve(self, **kwargs):
            return _FakeReservation("res-start")

    class _FakeOrchestrator:
        async def run(self, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(start_run_mod, "screen_goal", lambda _goal: (True, ""))
    monkeypatch.setattr(start_run_mod, "_analyze_goal", lambda _goal: ("", ""))
    monkeypatch.setattr(start_run_mod, "assign_run_features", lambda *_a, **_k: {"engine": "legacy"})
    monkeypatch.setattr(start_run_mod, "get_default_budget_service", lambda: _BudgetService())
    monkeypatch.setattr(start_run_mod, "get_balance", lambda _founder_id: 100)
    monkeypatch.setattr(start_run_mod, "get_orchestrator", lambda: _FakeOrchestrator())
    monkeypatch.setattr(start_run_mod, "durable_create_run_with_event", fake_create_run_with_event)
    async def fake_update_run_fields(run_id, patch):
        field_updates.append((run_id, patch))

    monkeypatch.setattr(start_run_mod, "_update_run_fields", fake_update_run_fields)
    monkeypatch.setattr(start_run_mod.asyncio, "create_task", lambda _coro: (_ for _ in ()).throw(RuntimeError("scheduler offline")))
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda _founder_id: {"org_id": "org_1", "plan": "starter", "entitlements": {"remaining_runs": 10}})
    monkeypatch.setattr("backend.accounts.record_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.session_store.register_session", lambda **kwargs: None)
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.events._get_queue", lambda _sid: None)

    body = RunCreateRequest(founder_id="founder_1", instruction="Build the app", constraints={})
    result = await start_run_mod.start_run(body, request=None, run_id="run_queue")

    assert result.status == "queued"
    assert any(patch["status"] == "queued" for _, patch in field_updates)


@pytest.mark.asyncio
async def test_custom_agent_runner_delegates_to_start_run(monkeypatch):
    from backend.custom_agents import runner

    calls = []
    created_tasks = []

    async def fake_start_run(body, request=None, *, run_id=None):
        calls.append(body)
        return SimpleNamespace(session_id="sess_custom", status="running")

    real_create_task = asyncio.create_task

    def fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("backend.control_plane.start_run.start_run", fake_start_run)
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda _founder_id: {"plan": "starter"})
    monkeypatch.setattr("backend.missions.company_goal.get_company_name", lambda *_args, **_kwargs: "Acme")
    monkeypatch.setattr(runner.asyncio, "create_task", fake_create_task)

    session_id = await runner.launch_custom_agent_run(
        founder_id="founder_1",
        spec={"id": "design", "name": "Design Agent", "company_id": "company_1"},
        goal="Make a new hero",
        company_id="company_1",
        kind="user",
    )

    assert session_id == "sess_custom"
    assert calls
    body = calls[0]
    assert body.stack_id == "custom"
    assert body.constraints["custom_agent_id"] == "design"
    assert body.constraints["agents"] == ["design"]

    for task in created_tasks:
        task.cancel()

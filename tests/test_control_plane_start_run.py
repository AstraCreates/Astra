from types import SimpleNamespace

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

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


def _patch_common_start_run_infra(monkeypatch, *, create_task=None):
    """Shared mocks for the concurrency regression tests below: goal screening,
    stack inference, feature assignment, budget reservation, orchestrator,
    durable run persistence, session store, and cancellation bookkeeping. Real
    workspace_store / accounts calls are left untouched so the actual locking
    fix under test executes for real."""

    class _BudgetService:
        def reserve(self, **kwargs):
            return _FakeReservation("res-race")

    class _FakeOrchestrator:
        async def run(self, **_kwargs):
            return {"ok": True}

    async def fake_create_run_with_event(run, *, event_type="run.created", payload=None):
        return None

    async def fake_update_run_fields(run_id, patch):
        return None

    monkeypatch.setattr(start_run_mod, "screen_goal", lambda _goal: (True, ""))
    monkeypatch.setattr(start_run_mod, "_analyze_goal", lambda _goal: ("", ""))
    monkeypatch.setattr(start_run_mod, "assign_run_features", lambda *_a, **_k: {"engine": "legacy"})
    monkeypatch.setattr(start_run_mod, "get_default_budget_service", lambda: _BudgetService())
    monkeypatch.setattr(start_run_mod, "get_balance", lambda _founder_id: 100)
    monkeypatch.setattr(start_run_mod, "get_orchestrator", lambda: _FakeOrchestrator())
    monkeypatch.setattr(start_run_mod, "durable_create_run_with_event", fake_create_run_with_event)
    monkeypatch.setattr(start_run_mod, "_update_run_fields", fake_update_run_fields)
    monkeypatch.setattr("backend.core.session_store.register_session", lambda **kwargs: None)
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.events._get_queue", lambda _sid: None)
    monkeypatch.setattr("backend.core.cancellation.register_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.core.cancellation.clear", lambda *args, **kwargs: None)
    if create_task is not None:
        monkeypatch.setattr(start_run_mod.asyncio, "create_task", create_task)


def test_find_or_create_workspace_concurrent_same_name_creates_one_workspace(tmp_path, monkeypatch):
    """Regression test for Bug 1: two concurrent find-or-create calls for the
    same (founder_id, workspace_name) must resolve to exactly one workspace,
    not two. Exercises backend/core/workspace_store.py's real, file-backed
    store (not mocked) under an injected delay that widens the original
    check-then-act race window, so a missing/broken lock would reliably
    produce two workspaces here instead of merely flaking."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.core import workspace_store as wss

    founder_id = "founder_ws_race"
    name = "Acme Rocket"

    original_find = wss.find_workspace_by_name

    def slow_find(*args, **kwargs):
        result = original_find(*args, **kwargs)
        time.sleep(0.05)  # widen the window between "not found" and "create"
        return result

    monkeypatch.setattr(wss, "find_workspace_by_name", slow_find)

    results: list[dict] = []
    errors: list[Exception] = []
    out_lock = threading.Lock()

    def worker():
        try:
            r = wss.find_or_create_workspace(founder_id, name, goal="Build it", stack_id="idea_to_revenue")
            with out_lock:
                results.append(r)
        except Exception as exc:  # pragma: no cover - failure path surfaced via assertions
            with out_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    assert len(results) == 5
    workspace_ids = {r["workspace_id"] for r in results}
    assert len(workspace_ids) == 1, f"expected one workspace, got {workspace_ids}"
    assert len(wss.list_workspaces(founder_id)) == 1


def test_start_run_concurrent_same_workspace_name_creates_one_workspace(tmp_path, monkeypatch):
    """Regression test for Bug 1 at the start_run() call boundary: two
    concurrent start_run() calls for the same founder + workspace_name must
    end up sharing one workspace_id, and exactly one workspace must exist on
    disk afterwards. Runs each start_run() call on its own OS thread (each
    driving its own asyncio event loop) so the race is real, not merely
    interleaved coroutine scheduling on a single loop."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    from backend.core import workspace_store as wss

    original_find = wss.find_workspace_by_name

    def slow_find(*args, **kwargs):
        result = original_find(*args, **kwargs)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(wss, "find_workspace_by_name", slow_find)
    _patch_common_start_run_infra(monkeypatch)
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda _f: {"org_id": "org_ws_race", "plan": "starter", "entitlements": {"remaining_runs": 10}})
    monkeypatch.setattr("backend.accounts.check_and_consume_run", lambda *a, **k: {"org_id": "org_ws_race"})

    founder_id = "founder_ws_race_full"
    body1 = RunCreateRequest(founder_id=founder_id, instruction="Build A", workspace_name="Acme Rocket", constraints={})
    body2 = RunCreateRequest(founder_id=founder_id, instruction="Build B", workspace_name="Acme Rocket", constraints={})

    results: list[SimpleNamespace] = []
    errors: list[Exception] = []
    out_lock = threading.Lock()

    def run_in_thread(body, run_id):
        try:
            result = asyncio.run(start_run_mod.start_run(body, request=None, run_id=run_id))
            with out_lock:
                results.append(result)
        except Exception as exc:  # pragma: no cover - failure path surfaced via assertions
            with out_lock:
                errors.append(exc)

    t1 = threading.Thread(target=run_in_thread, args=(body1, "run_ws_race_1"))
    t2 = threading.Thread(target=run_in_thread, args=(body2, "run_ws_race_2"))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert results[0].workspace_id
    assert results[0].workspace_id == results[1].workspace_id
    assert len(wss.list_workspaces(founder_id)) == 1


def test_check_and_consume_run_concurrent_single_remaining_run_only_one_succeeds(tmp_path, monkeypatch):
    """Regression test for Bug 2: with exactly 1 remaining run, two concurrent
    check_and_consume_run() calls must not both succeed. Exercises the real,
    file-backed backend/accounts.py store under an injected delay inside the
    locked critical section's _load() so a broken/removed lock would reliably
    let both callers observe remaining_runs > 0."""
    monkeypatch.chdir(tmp_path)

    from backend import accounts

    founder_id = "founder_budget_race"
    org = accounts.get_or_create_org(founder_id)
    accounts.update_subscription(org["org_id"], actor_id="system", plan="starter")
    data = accounts._load(org["org_id"])
    data["usage"] = {
        "period": time.strftime("%Y-%m", time.gmtime()),
        "runs": 24,  # starter plan allows 25/month -> exactly 1 remaining
        "connector_syncs": 0,
        "approval_decisions": 0,
    }
    accounts._save(data)

    entitled = accounts.with_entitlements(accounts._load(org["org_id"]))
    assert entitled["entitlements"]["remaining_runs"] == 1

    original_load = accounts._load

    def slow_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(accounts, "_load", slow_load)

    successes: list[dict] = []
    failures: list[Exception] = []
    out_lock = threading.Lock()

    def worker():
        try:
            r = accounts.check_and_consume_run(founder_id, org["org_id"])
            with out_lock:
                successes.append(r)
        except accounts.RunLimitExceeded as exc:
            with out_lock:
                failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(successes) == 1
    assert len(failures) == 1

    final = accounts.with_entitlements(accounts._load(org["org_id"]))
    assert final["entitlements"]["remaining_runs"] == 0


def test_start_run_concurrent_last_run_only_one_succeeds(tmp_path, monkeypatch):
    """Regression test for Bug 2 at the start_run() call boundary: a founder
    with exactly 1 remaining run/credit must not have two concurrent
    start_run() calls both succeed. Uses the real backend/accounts.py store
    (sandboxed to tmp_path) and real OS threads so the fix's locking is
    genuinely exercised."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "vault"))
    monkeypatch.chdir(tmp_path)

    from backend import accounts

    founder_id = "founder_budget_race_full"
    org = accounts.get_or_create_org(founder_id)
    accounts.update_subscription(org["org_id"], actor_id="system", plan="starter")
    data = accounts._load(org["org_id"])
    data["usage"] = {
        "period": time.strftime("%Y-%m", time.gmtime()),
        "runs": 24,
        "connector_syncs": 0,
        "approval_decisions": 0,
    }
    accounts._save(data)

    original_load = accounts._load

    def slow_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(accounts, "_load", slow_load)
    _patch_common_start_run_infra(monkeypatch)

    body1 = RunCreateRequest(founder_id=founder_id, instruction="Build A", constraints={})
    body2 = RunCreateRequest(founder_id=founder_id, instruction="Build B", constraints={})

    results: list[SimpleNamespace] = []
    errors: list[HTTPException] = []
    out_lock = threading.Lock()

    def run_in_thread(body, run_id):
        try:
            result = asyncio.run(start_run_mod.start_run(body, request=None, run_id=run_id))
            with out_lock:
                results.append(result)
        except HTTPException as exc:
            with out_lock:
                errors.append(exc)

    t1 = threading.Thread(target=run_in_thread, args=(body1, "run_budget_race_1"))
    t2 = threading.Thread(target=run_in_thread, args=(body2, "run_budget_race_2"))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert len(results) == 1
    assert len(errors) == 1
    assert errors[0].status_code == 402

    final = accounts.with_entitlements(accounts._load(org["org_id"]))
    assert final["entitlements"]["remaining_runs"] == 0

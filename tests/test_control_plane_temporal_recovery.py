import asyncio
import sys
import types

import pytest

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    temporalio = None


@pytest.mark.asyncio
async def test_dispatch_reset_client_cache_forces_new_connection(monkeypatch):
    import backend.control_plane.temporal.dispatch as dispatch

    seen = []

    class _FakeClient:
        def __init__(self, name):
            self.name = name

    async def _fake_connect():
        client = _FakeClient(f"client_{len(seen) + 1}")
        seen.append(client)
        return client

    dispatch.reset_client_cache()
    monkeypatch.setattr(dispatch, "_get_client", _fake_connect)

    first = await dispatch._get_client()
    dispatch.reset_client_cache()
    second = await dispatch._get_client()

    assert first is not second
    assert [client.name for client in seen] == ["client_1", "client_2"]


@pytest.mark.asyncio
async def test_query_workflow_state_returns_none_when_queries_fail(monkeypatch):
    import backend.control_plane.temporal.dispatch as dispatch

    class _FakeHandle:
        async def query(self, name):
            raise RuntimeError(f"query failed: {name}")

    class _FakeClient:
        def get_workflow_handle(self, workflow_id):
            return _FakeHandle()

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(dispatch, "_get_client", _fake_get_client)
    result = await dispatch.query_workflow_state("run_recovery")
    assert result is None


@pytest.mark.asyncio
async def test_cancel_run_returns_false_when_handle_is_unavailable(monkeypatch):
    import backend.control_plane.temporal.dispatch as dispatch

    class _FakeClient:
        def get_workflow_handle(self, workflow_id):
            raise RuntimeError("server unavailable")

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(dispatch, "_get_client", _fake_get_client)
    result = await dispatch.cancel_run("run_cancelled")
    assert result is False


@pytest.mark.asyncio
async def test_workflow_cancel_during_waiting_approval_preserves_cancelled_terminal_state(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod

    observations = []

    class _Handle:
        def __init__(self):
            self.cancelled = False
            self._done = False

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True
            self._done = True

        def __await__(self):
            async def _result():
                raise asyncio.CancelledError()

            return _result().__await__()

    handle = _Handle()

    async def _fake_execute_activity(activity_fn, *args, **kwargs):
        if getattr(activity_fn, "__qualname__", "").startswith("ObserveRunActivity"):
            activity_args = kwargs.get("args") or (args[0] if args else [])
            observations.append(activity_args[1] if len(activity_args) > 1 else {})
        return True

    real_sleep = asyncio.sleep
    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    monkeypatch.setattr(workflows_mod.workflow, "start_activity", lambda *args, **kwargs: handle)
    monkeypatch.setattr(workflows_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = workflows_mod.AstraRunWorkflow()
    wf._state.waiting_approval = {"approval_id": "approval_wait"}

    async def _drive():
        task = asyncio.create_task(wf.run(workflows_mod.RunInput(run_id="run_wait_cancel")))
        await asyncio.sleep(0)
        await wf.cancel()
        return await task

    result = await _drive()

    assert result.status == "cancelled"
    assert handle.cancelled is True
    assert observations[-1]["workflow_status"] == "cancelled"


@pytest.mark.asyncio
async def test_duplicate_update_run_status_activity_is_effectively_idempotent(tmp_path, monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.config.settings.supabase_url", "", raising=False)
    monkeypatch.setattr("backend.config.settings.supabase_key", "", raising=False)

    from backend.control_plane.temporal.activities import UpdateRunStatusActivity
    from backend.core.session_store import append_event, get_session_meta, merge_session_meta, register_session

    register_session("run_dupe", "founder_1", "Goal", visible=True)
    register_session("run_dupe__shadow", "founder_1", "Goal", visible=False, kind="shadow")
    merge_session_meta("run_dupe", shadow_comparison_status="pending")
    merge_session_meta("run_dupe__shadow", shadow_parent_run_id="run_dupe", shadow_mode=True)
    append_event("run_dupe", 1, {"type": "goal_done"})
    append_event("run_dupe__shadow", 1, {"type": "goal_done"})

    first = await UpdateRunStatusActivity.update("run_dupe__shadow", "succeeded")
    second = await UpdateRunStatusActivity.update("run_dupe__shadow", "succeeded")

    meta = get_session_meta("run_dupe") or {}
    assert first is True
    assert second is True
    assert meta["shadow_comparison_status"] == "completed"


@pytest.mark.asyncio
async def test_publish_event_activity_avoids_duplicate_durable_append(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from backend.control_plane.temporal.activities import PublishEventActivity

    appended = []
    published = []

    class _FakeEventRepo:
        def append(self, run_id, event_type, payload):
            appended.append((run_id, event_type, dict(payload)))
            return 7

    async def _fake_publish(run_id, event, *, persist_durable=True):
        published.append((run_id, dict(event), persist_durable))

    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunEventRepository", lambda: _FakeEventRepo())
    monkeypatch.setattr("backend.core.events.publish", _fake_publish)

    ok = await PublishEventActivity.publish("run_1", "run_started", {"hello": "world"})

    assert ok is True
    assert appended == [("run_1", "run_started", {"hello": "world"})]
    assert published == [("run_1", {"type": "run_started", "run_id": "run_1", "sequence": 7, "hello": "world"}, False)]


@pytest.mark.asyncio
async def test_observe_run_activity_routes_live_publish_without_duplicate_durable_append(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from backend.control_plane.temporal.activities import ObserveRunActivity

    appended = []
    published = []
    updated = []

    class _FakeEventRepo:
        def append(self, run_id, event_type, payload):
            appended.append((run_id, event_type, dict(payload)))
            return 11

    class _FakeRun:
        metadata = {"existing": True}

    class _FakeRunRepo:
        def get(self, run_id):
            return _FakeRun()

        def update_fields(self, run_id, patch):
            updated.append((run_id, dict(patch)))

    async def _fake_publish(run_id, event, *, persist_durable=True):
        published.append((run_id, dict(event), persist_durable))

    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunEventRepository", lambda: _FakeEventRepo())
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", lambda: _FakeRunRepo())
    monkeypatch.setattr("backend.core.events.publish", _fake_publish)

    ok = await ObserveRunActivity.record("run_2", {"workflow_status": "running", "active_step": "legacy_orchestrator"})

    assert ok is True
    assert appended and appended[0][1] == "run.observed"
    assert published == [("run_2", {"type": "run.observed", "run_id": "run_2", "sequence": 11, "workflow_status": "running", "active_step": "legacy_orchestrator", "waiting_approval": None, "cancellation_requested": False, "shadow_mode": False, "metadata": {}}, False)]
    assert updated and updated[0][0] == "run_2"


@pytest.mark.asyncio
async def test_local_workflow_recovery_environment_placeholder():
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    from backend.control_plane.temporal.testing import local_workflow_environment

    async with local_workflow_environment() as env:
        assert env is not None

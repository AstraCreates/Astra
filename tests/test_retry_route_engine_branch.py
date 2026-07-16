"""Regression test: POST /runs/{run_id}/steps/{step_key}/retry unconditionally
called the legacy rerun_agent() regardless of which engine actually owns the
run. For a Temporal-routed run, the real orchestrator/workflow execution
lives in the temporal-worker container, not the API process -- rerun_agent()
spawning a bare asyncio task there created a disconnected, untracked
duplicate agent run that was never part of the actual run, while looking
like it worked. The route must signal the real running workflow instead.
"""
import pytest
from starlette.requests import Request

from backend.api import routes
from backend.api.schemas import RunStepRetryRequest
from backend.control_plane.models import Run, RunStep


@pytest.mark.asyncio
async def test_retry_signals_temporal_workflow_instead_of_legacy_rerun(monkeypatch):
    rerun_agent_calls = []
    signaled = []

    class _RunRepo:
        def get(self, run_id):
            assert run_id == "run_1"
            return Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="g", engine="temporal")

    class _RunStepRepo:
        def create_attempt(self, step):
            return step

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    async def _fake_rerun_agent(*_args, **_kwargs):
        rerun_agent_calls.append(True)
        return {"ok": True}

    async def _fake_temporal_retry_step(run_id, *, step_key, requested_by=None, note=None):
        signaled.append((run_id, step_key, requested_by, note))
        return True

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr(routes, "rerun_agent", _fake_rerun_agent)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunStepRepository", _RunStepRepo)
    monkeypatch.setattr("backend.control_plane.temporal.dispatch.retry_step", _fake_temporal_retry_step)

    request = Request({"type": "http", "headers": []})
    body = RunStepRetryRequest(founder_id="founder_1", instruction="try again")

    result = await routes.retry_run_step("run_1", "web", body, request)

    assert rerun_agent_calls == []  # legacy path never invoked for a Temporal run
    assert signaled == [("run_1", "web", "founder_1", "try again")]
    assert result["ok"] is True
    assert result["engine"] == "temporal"
    assert result["dispatch"]["signaled"] is True


@pytest.mark.asyncio
async def test_retry_uses_legacy_rerun_for_non_temporal_run(monkeypatch):
    rerun_agent_calls = []
    signaled = []

    class _RunRepo:
        def get(self, run_id):
            return Run(id="run_2", owner_id="founder_1", org_id="founder_1", goal="g", engine="legacy")

    class _RunStepRepo:
        def create_attempt(self, step):
            return step

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    async def _fake_rerun_agent(*_args, **_kwargs):
        rerun_agent_calls.append(True)
        return {"ok": True, "status": "started"}

    async def _fake_temporal_retry_step(*_args, **_kwargs):
        signaled.append(True)
        return True

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr(routes, "rerun_agent", _fake_rerun_agent)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunStepRepository", _RunStepRepo)
    monkeypatch.setattr("backend.control_plane.temporal.dispatch.retry_step", _fake_temporal_retry_step)

    request = Request({"type": "http", "headers": []})
    body = RunStepRetryRequest(founder_id="founder_1", instruction="")

    result = await routes.retry_run_step("run_2", "web", body, request)

    assert signaled == []  # Temporal signal path never invoked for a legacy run
    assert rerun_agent_calls == [True]
    assert result["dispatch"]["ok"] is True


@pytest.mark.asyncio
async def test_retry_raises_502_when_temporal_signal_fails(monkeypatch):
    class _RunRepo:
        def get(self, run_id):
            return Run(id="run_3", owner_id="founder_1", org_id="founder_1", goal="g", engine="temporal")

    class _RunStepRepo:
        def create_attempt(self, step):
            return step

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    async def _fake_temporal_retry_step(*_args, **_kwargs):
        return False  # workflow not found / signal failed

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunStepRepository", _RunStepRepo)
    monkeypatch.setattr("backend.control_plane.temporal.dispatch.retry_step", _fake_temporal_retry_step)

    request = Request({"type": "http", "headers": []})
    body = RunStepRetryRequest(founder_id="founder_1")

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await routes.retry_run_step("run_3", "web", body, request)
    assert exc_info.value.status_code == 502

"""Regression test: POST /runs/{run_id}/cancel unconditionally set status to
"cancelling" regardless of whether a live task actually existed to cancel.

Confirmed production bug, two variants:
1. Cancelling/restarting an already-finished run overwrote its terminal
   status (succeeded/failed/cancelled) back to "cancelling" -- with no live
   task left to run, nothing would ever transition it further, so it sat
   stuck forever. The frontend's 30s poll for a terminal status always timed
   out, reporting "Restart failed: Could not stop the original run."
2. Even for a run that hadn't finished, cancellation.request_kill()'s return
   value (whether it actually found and cancelled a live asyncio task) was
   discarded -- if the task wasn't tracked under that exact run_id (a
   mismatch, a race, or it had already exited), the run got the same
   "cancelling" status with nothing left to resolve it, same permanent hang.
"""
import pytest
from starlette.requests import Request

from backend.api import routes
from backend.control_plane.models import Run


@pytest.mark.asyncio
async def test_cancel_already_terminal_run_does_not_overwrite_its_status(monkeypatch):
    class _RunRepo:
        def get(self, run_id):
            return Run(id=run_id, owner_id="f", org_id="f", goal="g", engine="legacy", status="failed")

        def update_status(self, *_a, **_k):
            raise AssertionError("must not overwrite an already-terminal run's status")

        def update_fields(self, *_a, **_k):
            raise AssertionError("must not overwrite an already-terminal run's status")

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)

    request = Request({"type": "http", "headers": []})
    result = await routes.cancel_run_route("run_1", request)

    assert result == {"ok": True, "run_id": "run_1", "status": "failed"}


@pytest.mark.asyncio
async def test_cancel_with_no_live_task_resolves_to_cancelled_not_stuck_cancelling(monkeypatch):
    updates = []

    class _RunRepo:
        def get(self, run_id):
            return Run(id=run_id, owner_id="f", org_id="f", goal="g", engine="legacy", status="running")

        def update_status(self, run_id, status, **kwargs):
            updates.append(("status", run_id, status))

        def update_fields(self, run_id, patch):
            updates.append(("fields", run_id, patch))

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    async def _reconcile(*_args, **_kwargs):
        pass

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr(routes, "_reconcile_orphaned_agents", _reconcile)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)
    monkeypatch.setattr("backend.core.session_store.get_session_meta", lambda *_a, **_k: {})
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.core.cancellation.request_kill", lambda *_a, **_k: False)

    request = Request({"type": "http", "headers": []})
    result = await routes.cancel_run_route("run_2", request)

    assert result["status"] == "cancelled"
    assert ("fields", "run_2", {"status": "cancelled"}) not in updates  # completed_at also present
    assert any(u[0] == "fields" and u[1] == "run_2" and u[2].get("status") == "cancelled" for u in updates)


@pytest.mark.asyncio
async def test_cancel_with_live_task_sets_transient_cancelling(monkeypatch):
    updates = []

    class _RunRepo:
        def get(self, run_id):
            return Run(id=run_id, owner_id="f", org_id="f", goal="g", engine="legacy", status="running")

        def update_status(self, run_id, status, **kwargs):
            updates.append((run_id, status))

        def update_fields(self, run_id, patch):
            updates.append((run_id, patch))

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)
    monkeypatch.setattr("backend.core.session_store.get_session_meta", lambda *_a, **_k: {})
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.core.cancellation.request_kill", lambda *_a, **_k: True)

    request = Request({"type": "http", "headers": []})
    result = await routes.cancel_run_route("run_3", request)

    assert result == {"ok": True, "run_id": "run_3", "status": "cancelling"}
    assert ("run_3", "cancelling") in updates

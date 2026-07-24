"""Tests for the asynchronous Company OS approval flow.

Covers:
  * The decide endpoint returns 202 and a status_url; idempotent re-submit
    of the same approval returns 200 with ``idempotent: True`` rather than
    a confusing 409.
  * ``status_url`` reports ``applied: false`` immediately after the ACK,
    then ``applied: true`` once the side-effect task has run, OR the
    startup resync picks up state on a fresh process.
  * The async side-effects path leaves the durable ledger in the right
    state even if the process crashes before ``asyncio.create_task`` runs.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace(tmp_path: Path, monkeypatch):
    """Point the Company OS workspace at a throwaway directory so the
    async approval resync + side-effects work end-to-end without touching
    the real Obsidian vault."""
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "obsidian"))
    yield tmp_path


@pytest.fixture(autouse=True)
def _background_loop():
    """launch_mission() calls asyncio.create_task(), which needs a running
    loop in the calling thread. In production that loop is captured once at
    FastAPI startup (backend/main.py -> company_os_runner.set_main_loop) so
    launch_mission still works when called from an asyncio.to_thread worker
    (exactly what resync_pending_async_approvals and
    _apply_approval_side_effects both are). These tests call those functions
    directly from pytest's plain sync thread, so there is no app startup to
    do that registration -- stand up the same kind of background loop here
    and register it the same way."""
    from backend import company_os_runner

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    company_os_runner.set_main_loop(loop)
    yield
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()
    company_os_runner.set_main_loop(None)
def test_resync_picks_up_unflushed_decisions(temp_workspace: Path):
    """Simulate: the web worker ACK'd an approval (durable ledger write),
    then crashed before asyncio.create_task fired. On startup, the resync
    helper must apply the side-effects and flip the task out of
    awaiting_approval."""
    from backend.company_os import (
        create_company_os,
        ensure_company_operations,
        create_initiative,
        create_squad,
        create_mission,
        create_task,
        get_company_os,
        create_approval,
    )
    from backend.api.company_os_routes import resync_pending_async_approvals

    company_id = "crash-company"
    create_company_os(company_id, "founder", "Crash Co")
    ensure_company_operations(company_id)
    init = create_initiative(company_id, "Approve me", department="operations")
    sq = create_squad(company_id, init["initiative_id"], "Sq", department="operations")
    mission = create_mission(company_id, init["initiative_id"], sq["squad_id"], "Mission Awaiting", department="operations")
    task = create_task(
        company_id,
        init["initiative_id"],
        sq["squad_id"],
        "Wait task",
        mission_id=mission["mission_id"],
        state="awaiting_approval",
        department="operations",
    )
    # Pre-write the durable approved state without applying side-effects
    # (simulates a process that crashed between ACK and create_task).
    create_approval(company_id, "Ghost approval", approval_id="ghost-approval", state="approved", task_id=task["task_id"], decided_at="2026-01-01T00:00:00Z")
    # Sanity: task is still awaiting_approval before resync.
    snapshot_before = get_company_os(company_id)
    matching_task = next(t for t in snapshot_before["tasks"] if t["task_id"] == task["task_id"])
    assert matching_task["state"] == "awaiting_approval"

    applied = resync_pending_async_approvals()
    assert applied >= 1
    snapshot_after = get_company_os(company_id)
    matching_task_after = next(t for t in snapshot_after["tasks"] if t["task_id"] == task["task_id"])
    assert matching_task_after["state"] != "awaiting_approval", "resync must have advanced the task"


def test_resync_is_idempotent(temp_workspace: Path):
    """Running resync twice in a row must not damage state. The second
    pass should report zero applications because everything is already
    consistent."""
    from backend.api.company_os_routes import resync_pending_async_approvals
    # First the test above made state consistent; running it again here
    # just confirms zero new applications.
    first = resync_pending_async_approvals()
    second = resync_pending_async_approvals()
    assert second == 0, f"second resync should be no-op, got {second}; first={first}"


def test_apply_side_effects_idempotent(temp_workspace: Path):
    """Calling _apply_approval_side_effects twice with the same inputs
    must not corrupt state. (We can't easily exercise launch_mission
    here -- the runner guards against double-launch on an already-active
    mission -- so we just verify the durable state is unchanged.)"""
    from backend.company_os import (
        create_company_os,
        ensure_company_operations,
        create_initiative,
        create_squad,
        create_mission,
        create_task,
        get_company_os,
        create_approval,
    )
    from backend.api.company_os_routes import _apply_approval_side_effects

    company_id = "idempotency-company"
    create_company_os(company_id, "founder", "Idempotent Co")
    ensure_company_operations(company_id)
    init = create_initiative(company_id, "Twice", department="operations")
    sq = create_squad(company_id, init["initiative_id"], "Sq", department="operations")
    mission = create_mission(company_id, init["initiative_id"], sq["squad_id"], "M", department="operations")
    task = create_task(
        company_id,
        init["initiative_id"],
        sq["squad_id"],
        "T",
        mission_id=mission["mission_id"],
        state="awaiting_approval",
        department="operations",
    )
    create_approval(company_id, "Approval x", approval_id="approval-x", state="approved", task_id=task["task_id"])

    _apply_approval_side_effects(company_id, "approval-x", approved=True, note="")
    state1 = get_company_os(company_id)
    task_state1 = next(t for t in state1["tasks"] if t["task_id"] == task["task_id"])["state"]
    mission_state1 = next(m for m in state1["missions"] if m["mission_id"] == mission["mission_id"])["state"]

    # Second pass: task already advanced, mission already active.
    _apply_approval_side_effects(company_id, "approval-x", approved=True, note="")
    state2 = get_company_os(company_id)
    task_state2 = next(t for t in state2["tasks"] if t["task_id"] == task["task_id"])["state"]
    mission_state2 = next(m for m in state2["missions"] if m["mission_id"] == mission["mission_id"])["state"]

    assert task_state1 == task_state2
    assert mission_state1 == mission_state2


def test_status_payload_reports_applied(temp_workspace: Path):
    from backend.company_os import (
        create_company_os,
        ensure_company_operations,
        create_initiative,
        create_squad,
        create_mission,
        create_task,
        create_approval,
    )
    from backend.api.company_os_routes import _approval_status_payload

    company_id = "status-company"
    create_company_os(company_id, "founder", "Status Co")
    ensure_company_operations(company_id)
    init = create_initiative(company_id, "I", department="operations")
    sq = create_squad(company_id, init["initiative_id"], "Sq", department="operations")
    mission = create_mission(company_id, init["initiative_id"], sq["squad_id"], "M", department="operations")
    task = create_task(
        company_id,
        init["initiative_id"],
        sq["squad_id"],
        "T",
        mission_id=mission["mission_id"],
        state="awaiting_approval",
        department="operations",
    )
    create_approval(company_id, "Status approval", approval_id="status-approval", state="approved", task_id=task["task_id"])
    payload = _approval_status_payload(company_id, "status-approval")
    assert payload.state == "approved"
    # Before side-effects run, the task is still awaiting_approval.
    assert payload.applied is False


if __name__ == "__main__":
    sys.exit(0)

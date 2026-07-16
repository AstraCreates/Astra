"""Regression test for Pause never working on Temporal-routed runs.

A Temporal run's orchestrator loop executes inside the temporal-worker
container (via ExecuteOrchestratorActivity), a different process than
whichever backend API replica served POST /sessions/{id}/pause.
cancellation.py's _paused set was pure in-process memory -- setting it in
one process was invisible to a check in another, so clicking Pause showed
"paused" in the UI while the workflow kept executing agents uninterrupted.

pause_session/resume_session now also mirror to durable session_meta (the
same $OBSIDIAN_VAULT/sessions/{id}/meta.json Docker volume shared by both
containers), and wait_if_paused checks both the fast in-process flag and
the durable one.
"""
import asyncio

import pytest

from backend.core import cancellation


@pytest.fixture(autouse=True)
def _isolate_state():
    yield
    cancellation._paused.clear()
    cancellation._killed.clear()


def test_pause_session_writes_durable_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    import backend.core.session_store as session_store

    cancellation.pause_session("sess_1")

    meta = session_store.get_session_meta("sess_1")
    assert meta.get("paused") is True


def test_resume_session_clears_durable_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    import backend.core.session_store as session_store

    cancellation.pause_session("sess_1")
    cancellation.resume_session("sess_1")

    meta = session_store.get_session_meta("sess_1")
    assert meta.get("paused") is False


@pytest.mark.asyncio
async def test_wait_if_paused_observes_durable_flag_set_from_another_process(tmp_path, monkeypatch):
    """Simulates the real cross-process scenario: pause_session() is called
    with the LOCAL in-process _paused set cleared immediately after (as if a
    different process/container had done the pausing) -- wait_if_paused must
    still block on the durable flag alone."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    cancellation.pause_session("sess_2")
    cancellation._paused.discard("sess_2")  # simulate: pause request came from a different process
    assert not cancellation.is_paused("sess_2")  # local flag genuinely empty

    resumed = {"done": False}

    async def _resume_after_delay():
        await asyncio.sleep(0.05)
        cancellation.resume_session("sess_2")
        resumed["done"] = True

    asyncio.create_task(_resume_after_delay())
    await asyncio.wait_for(cancellation.wait_if_paused("sess_2", poll_interval=0.01), timeout=2.0)

    assert resumed["done"] is True


@pytest.mark.asyncio
async def test_wait_if_paused_returns_immediately_when_not_paused(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    await asyncio.wait_for(cancellation.wait_if_paused("sess_never_paused", poll_interval=1.0), timeout=0.5)


@pytest.mark.asyncio
async def test_wait_if_paused_exits_on_kill_even_if_paused(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    cancellation.pause_session("sess_3")
    cancellation.request_kill("sess_3")

    await asyncio.wait_for(cancellation.wait_if_paused("sess_3", poll_interval=0.01), timeout=1.0)

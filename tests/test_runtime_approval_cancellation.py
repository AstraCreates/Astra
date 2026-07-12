import asyncio
import pytest

from backend.core import cancellation, events


def _clear_runtime(session_id: str) -> None:
    events._event_log.pop(session_id, None)
    events._event_counters.pop(session_id, None)
    events._approval_decisions.pop(session_id, None)
    events._approval_ledger_rebuilt.discard(session_id)
    events._completed.discard(session_id)
    cancellation.clear(session_id)


@pytest.mark.asyncio
async def test_approval_wait_times_out_fail_closed_and_consumes_once():
    session_id = "approval-once"
    _clear_runtime(session_id)
    assert await events.approval_decision_wait(session_id, "req-1", "digest-1", timeout=0) is None

    decision = {
        "type": "stack_approval_decision",
        "request_id": "req-1",
        "approval_id": "req-1",
        "action_digest": "digest-1",
        "decision": "approved",
    }
    events.approval_decision_push(session_id, "req-1", "digest-1", decision)
    assert await events.approval_decision_wait(session_id, "req-1", "digest-1", timeout=0.01) == decision
    assert await events.approval_decision_wait(session_id, "req-1", "digest-1", timeout=0) is None
    with pytest.raises(ValueError, match="request_id/action_digest"):
        events.approval_decision_push(session_id, "req-1", "different-digest", decision)


@pytest.mark.asyncio
async def test_approval_wait_rebuilds_only_matching_decision_after_restart(monkeypatch):
    session_id = "approval-restart"
    _clear_runtime(session_id)
    monkeypatch.setattr("backend.core.session_store.load_events", lambda _session_id: None)
    monkeypatch.setattr("backend.approval_workflows.get_approval_workflow", lambda _session_id: {"requests": [
        {"id": "stale-request", "action_digest": "stale-digest", "status": "approved"},
        {"id": "current-request", "action_digest": "current-digest", "status": "skipped"},
    ]})
    recovered = await events.approval_decision_wait(
        session_id, "current-request", "current-digest", timeout=0.01
    )
    assert recovered == {
        "type": "stack_approval_decision",
        "gate_key": None,
        "request_id": "current-request",
        "approval_id": "current-request",
        "action_digest": "current-digest",
        "decision": "skipped",
        "note": "",
        "_recovered_from_ledger": True,
    }
    assert await events.approval_decision_wait(
        session_id, "stale-request", "current-digest", timeout=0
    ) is None


def test_restore_sorts_and_deduplicates_event_ids(monkeypatch):
    session_id = "ordered-replay"
    _clear_runtime(session_id)
    monkeypatch.setattr("backend.core.session_store.load_events", lambda _session_id: [
        (3, {"type": "agent_done", "agent": "design"}),
        (1, {"type": "goal_start"}),
        (3, {"type": "agent_start", "agent": "stale-duplicate"}),
        (2, {"type": "goal_done"}),
    ])

    restored, done = events._restore_session(session_id)

    assert restored is True
    assert done is True
    assert [event_id for event_id, _ in events._event_log[session_id]] == [1, 2, 3]
    assert events._event_log[session_id][-1][1]["type"] == "agent_done"


@pytest.mark.asyncio
async def test_parent_forwarded_events_are_persisted(monkeypatch):
    child_id = "child-persist"
    parent_id = "parent-persist"
    _clear_runtime(child_id)
    _clear_runtime(parent_id)
    persisted: list[tuple[str, int, dict]] = []
    monkeypatch.setattr(
        "backend.core.session_store.append_event",
        lambda session_id, event_id, event: persisted.append((session_id, event_id, event)),
    )
    monkeypatch.setattr(events, "_redis_append", lambda *_args: None)
    events.register_parent_session(child_id, parent_id)

    await events.publish(child_id, {"type": "agent_done", "agent": "research", "result": {"summary": "done"}})

    forwarded = [event for session_id, _, event in persisted if session_id == parent_id]
    assert len(forwarded) == 1
    assert forwarded[0]["_forwarded_from"] == child_id
    assert events._event_log[parent_id][-1][1]["_forwarded_from"] == child_id


@pytest.mark.asyncio
async def test_late_agent_start_cannot_overwrite_a_terminal_session(monkeypatch):
    session_id = "terminal-session"
    _clear_runtime(session_id)
    monkeypatch.setattr("backend.core.session_store.append_event", lambda *_args: None)
    monkeypatch.setattr(events, "_redis_append", lambda *_args: None)

    await events.publish(session_id, {"type": "goal_done", "results": {}})
    await events.publish(session_id, {"type": "agent_start", "agent": "late"})

    assert [event["type"] for _, event in events._event_log[session_id]] == ["goal_done"]


@pytest.mark.asyncio
async def test_concurrent_rerun_claim_and_kill_cancels_every_active_attempt():
    session_id = "rerun-kill"
    _clear_runtime(session_id)
    attempt_id = cancellation.claim_attempt(session_id, "design")
    assert attempt_id is not None
    assert cancellation.claim_attempt(session_id, "design") is None

    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(work())
    cancellation.register_task(session_id, task, attempt_id=attempt_id, agent_name="design")
    await started.wait()
    assert cancellation.request_kill(session_id) is True
    assert cancellation.cancellation_fence(session_id, "design").is_set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancellation.cancellation_fence(session_id, "design").is_set()
    cancellation.release_attempt(session_id, attempt_id)


def test_sync_tool_fence_blocks_before_side_effect():
    session_id = "sync-tool-fence"
    _clear_runtime(session_id)
    cancellation.request_kill(session_id)
    called = False

    def risky_tool():
        nonlocal called
        called = True

    with pytest.raises(asyncio.CancelledError):
        cancellation.run_sync_with_fence(session_id, "ops", risky_tool, {})
    assert called is False


@pytest.mark.asyncio
async def test_compatibility_approval_callers_reject_ambiguous_old_payloads():
    from backend.astra_mcp import _approve
    from backend.copilot import _tool_decide_approval_gate

    assert _approve({"session_id": "s", "action_key": "public_deploy"})["ok"] is False
    result = await _tool_decide_approval_gate(
        "founder", "s", {"gate_key": "public_deploy", "decision": "approved"}
    )
    assert result["ok"] is False
    assert "request_id and expected_action_digest" in result["error"]

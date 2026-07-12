"""
In-process event bus for streaming agent progress to SSE clients.
One asyncio.Queue per session_id. Agent/orchestrator publish; SSE endpoint consumes.
All events are buffered so reconnecting clients can replay missed events.
Events are also persisted to Redis so sessions survive backend restarts.
"""
import asyncio
import json
import logging
import time
from collections import deque
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_sessions: dict[str, asyncio.Queue] = {}
_completed: set[str] = set()  # sessions that finished — reconnect gets immediate replay + close
_steer: dict[str, list[str]] = {}  # inbound founder directives per session
_input_responses: dict[str, dict] = {}  # request_id → founder input response
_approval_decisions: dict[str, dict[str, dict]] = {}  # session_id -> request_id -> decision event

# Persistent event log per session: list of (event_id, event_dict)
_event_log: dict[str, list[tuple[int, dict]]] = {}
_event_counters: dict[str, int] = {}
_publish_locks: dict[str, asyncio.Lock] = {}
_approval_ledger_rebuilt: set[str] = set()

_MAX_BUFFER = 2000  # max events kept per session
_REDIS_TTL = 8 * 3600  # 8 hours
# child_session_id → parent_session_id for agent-status event forwarding
_parent_map: dict[str, str] = {}
_RUNTIME_EVENT_TYPES = {
    "agent_budget_update", "agent_budget_exhausted",
    "tool_guardrail_warning", "tool_guardrail_blocked", "tool_unavailable",
    "context_compression_started", "context_compression_completed",
    "context_compression_failed", "subagent_spawned", "subagent_started",
    "subagent_progress", "subagent_action_requested", "subagent_rejected", "subagent_completed",
    "subagent_failed", "subagent_interrupted",
    "web_task_started", "web_task_state", "web_task_needs_user",
    "web_task_resumed", "web_task_completed", "web_task_failed",
}
_SECRET_KEYS = ("token", "secret", "password", "api_key", "authorization")


# ── Redis helpers ──────────────────────────────────────────────────────────────

_redis_client = None
_redis_failed_at = 0.0


def _redis():
    """Return a cached, pooled Redis client (or None if unavailable).

    Previously this opened a fresh connection and ping()'d on every call —
    once per event, so a new TCP connection per event under load. redis-py's
    client is thread-safe and pools connections internally, so we cache it and
    only reconnect on failure (with a short cooldown to avoid hammering)."""
    global _redis_client, _redis_failed_at
    if _redis_client is not None:
        return _redis_client
    if time.time() - _redis_failed_at < 5:
        return None  # recently failed — don't retry-storm
    try:
        import redis as _redis_lib
        from backend.config import settings
        r = _redis_lib.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=5,
            health_check_interval=30, max_connections=64,
        )
        r.ping()
        _redis_client = r
        return r
    except Exception:
        _redis_failed_at = time.time()
        return None


def _redis_reset() -> None:
    global _redis_client
    _redis_client = None


def _redis_append(session_id: str, event_id: int, event: dict) -> None:
    try:
        r = _redis()
        if not r:
            return
        key = f"events:{session_id}"
        r.rpush(key, json.dumps({"id": event_id, "event": event}))
        r.expire(key, _REDIS_TTL)
    except Exception:
        _redis_reset()


def _redis_load(session_id: str) -> list[tuple[int, dict]] | None:
    """Load event log from Redis. Returns None if not found."""
    try:
        r = _redis()
        if not r:
            return None
        raw = r.lrange(f"events:{session_id}", 0, -1)
        if not raw:
            return None
        result = []
        for item_str in raw:
            item = json.loads(item_str)
            result.append((int(item["id"]), item["event"]))
        return result
    except Exception:
        return None


def _redis_active_sessions() -> list[str]:
    """Return session_ids that have events in Redis but no goal_done — interrupted runs."""
    try:
        r = _redis()
        if not r:
            return []
        keys = list(r.scan_iter("events:*", count=100))
        interrupted = []
        for key in keys:
            sid = key.split(":", 1)[1]
            raw = r.lrange(key, 0, -1)
            events = [json.loads(x)["event"] for x in raw]
            is_done = any(e.get("type") in ("goal_done", "goal_error") for e in events)
            if not is_done:
                interrupted.append(sid)
        return interrupted
    except Exception:
        return []


# ── Core event bus ─────────────────────────────────────────────────────────────

def _get_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _sessions:
        _sessions[session_id] = asyncio.Queue()
    return _sessions[session_id]


def _next_id(session_id: str) -> int:
    _event_counters[session_id] = _event_counters.get(session_id, 0) + 1
    return _event_counters[session_id]


def _publish_lock(session_id: str) -> asyncio.Lock:
    lock = _publish_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _publish_locks[session_id] = lock
    return lock


def _buffer(session_id: str, event_id: int, event: dict) -> None:
    if session_id not in _event_log:
        _event_log[session_id] = []
    log = _event_log[session_id]
    log.append((event_id, event))
    _capture_approval_decision(session_id, event)
    if len(log) > _MAX_BUFFER:
        log.pop(0)


def _capture_approval_decision(session_id: str, event: dict) -> None:
    """Mirror approval decision events into the in-memory wait store."""
    if event.get("type") != "stack_approval_decision":
        return
    request_id = event.get("request_id") or event.get("approval_id")
    action_digest = event.get("action_digest") or event.get("expected_action_digest")
    if not request_id or not action_digest:
        return
    _approval_decisions.setdefault(session_id, {})[str(request_id)] = event


def _rebuild_approval_decisions(session_id: str, events: list[tuple[int, dict]]) -> None:
    """Reconstruct approval wait state from a restored event log."""
    for _, event in events:
        _capture_approval_decision(session_id, event)


def _rebuild_approval_decisions_from_ledger(session_id: str) -> None:
    """Recover final approval decisions even if a crash preceded event publication."""
    try:
        from backend.approval_workflows import FINAL_APPROVAL_STATUSES, get_approval_workflow
        workflow = get_approval_workflow(session_id) or {}
        decisions = _approval_decisions.setdefault(session_id, {})
        for request in workflow.get("requests") or []:
            decision = str(request.get("decision") or request.get("status") or "")
            request_id = str(request.get("id") or request.get("approval_id") or "")
            action_digest = str(request.get("action_digest") or "")
            if decision not in FINAL_APPROVAL_STATUSES or not request_id or not action_digest:
                continue
            decisions.setdefault(request_id, {
                "type": "stack_approval_decision",
                "gate_key": request.get("gate_key"),
                "request_id": request_id,
                "approval_id": request.get("approval_id") or request_id,
                "action_digest": action_digest,
                "decision": decision,
                "note": request.get("note") or "",
                "_recovered_from_ledger": True,
            })
    except Exception as exc:
        logger.warning("Unable to rebuild approval decisions from ledger for %s: %s", session_id, exc)
    finally:
        _approval_ledger_rebuilt.add(session_id)


_SESSION_LOG_PATH = "/tmp/astra_session.log"
_KEY_EVENT_TYPES = {
    "goal_start", "goal_done", "goal_error",
    "agent_start", "agent_done", "agent_error",
    "agent_tool_call", "agent_thinking", "agent_action",
    "agent_unknown_action",
    "plan_done", "company_name", "goal_expanded",
    "stack_selected",
    "web_task_started", "web_task_completed", "web_task_failed",
}


def _write_session_log(session_id: str, event: dict) -> None:
    etype = event.get("type", "")
    if etype not in _KEY_EVENT_TYPES:
        return
    try:
        ts = event.get("ts_iso", "")
        agent = event.get("agent", event.get("founder_id", ""))
        extra = ""
        if etype in ("agent_tool_call", "agent_action"):
            tool = event.get("tool", event.get("action", ""))
            args = event.get("args", event.get("task", event.get("detail", "")))
            extra = f" tool={tool} args={str(args)[:80]}"
        elif etype == "agent_done":
            result = event.get("result", event.get("output", {}))
            keys = list(result.keys()) if isinstance(result, dict) else str(result)[:40]
            extra = f" result_keys={keys}"
        elif etype == "agent_error":
            extra = f" error={str(event.get('error', ''))[:120]}"
        elif etype == "goal_start":
            extra = f" goal={str(event.get('goal', ''))[:100]}"
        elif etype == "company_name":
            extra = f" name={event.get('name', '')}"
        elif etype == "plan_done":
            tasks = event.get("tasks", [])
            extra = f" agents=[{', '.join(t.get('agent','') for t in tasks)}]"
        elif etype == "agent_thinking":
            extra = f" hint={event.get('hint', '')[:60]}"
        elif etype == "agent_unknown_action":
            extra = f" action={event.get('action')} keys={event.get('parsed_keys')} raw={event.get('raw_snippet','')[:60]}"
        line = f"[{ts}] {session_id[:8]} {etype:<22} {agent}{extra}\n"
        with open(_SESSION_LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass


def _strip_base64(event: dict) -> dict:
    """Strip large base64 fields from events before putting them in the SSE queue.
    Base64 images can be 300KB-1MB each and cause browser crashes when streamed.
    The full data is preserved in the JSONL store — only the SSE stream is stripped.
    """
    import re as _re
    result = event.get("result")
    if not isinstance(result, dict):
        return event
    # Check if any value looks like base64 image data (>10KB)
    has_large_b64 = any(
        isinstance(v, str) and len(v) > 10_000 and _re.match(r'^[A-Za-z0-9+/=]+$', v[:100])
        for v in result.values()
    )
    if not has_large_b64:
        return event
    # Strip base64 but keep metadata
    clean_result = {}
    for k, v in result.items():
        if isinstance(v, str) and len(v) > 10_000 and _re.match(r'^[A-Za-z0-9+/=]+$', v[:100]):
            clean_result[k] = f"[base64:{len(v)}chars]"
        elif isinstance(v, dict) and isinstance(v.get("base64"), str) and len(v["base64"]) > 10_000:
            clean_result[k] = {**v, "base64": f"[base64:{len(v['base64'])}chars]"}
        else:
            clean_result[k] = v
    return {**event, "result": clean_result, "_base64_stripped": True}


def _persist_goal_status_memory(session_id: str, event: dict) -> None:
    """Best-effort Company Brain mirror for goal task status changes."""
    try:
        etype = event.get("type")
        if etype not in {"agent_start", "agent_done"}:
            return
        agent = str(event.get("agent") or "")
        if not agent:
            return
        from backend.core.session_store import get_session_meta
        session_meta = get_session_meta(session_id) or {}
        founder_id = str(session_meta.get("founder_id") or event.get("founder_id") or "")
        if not founder_id:
            return
        from backend.missions.company_goal import current_goal
        company_id = str(session_meta.get("company_id") or founder_id)
        goal = current_goal(founder_id, company_id) or {}
        owned = [
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "status": task.get("status"),
                "owner_agents": task.get("owner_agents", []),
                "done_agents": task.get("done_agents", []),
            }
            for task in goal.get("tasks") or []
            if agent in (task.get("owner_agents") or [])
        ]
        if not owned:
            return
        from backend.tools.company_brain import add_company_brain_record
        status = "started" if etype == "agent_start" else "finished"
        add_company_brain_record(
            founder_id=founder_id,
            source="astra_goal_system",
            title=f"{agent} {status} company-goal work",
            content=json.dumps({
                "session_id": session_id,
                "agent": agent,
                "event": etype,
                "current_goal_id": goal.get("id", ""),
                "current_goal_title": goal.get("title", ""),
                "tasks": owned,
            }, indent=2, default=str),
            kind="goal_status",
            canonical=False,
            stale_risk="low",
            metadata={
                "session_id": session_id,
                "company_id": str(session_meta.get("company_id") or founder_id),
                "agent": agent,
                "event": etype,
            },
        )
    except Exception:
        pass


def _bound_runtime_event(event: dict) -> dict:
    if event.get("type") not in _RUNTIME_EVENT_TYPES:
        return event

    def clean(key: str, value):
        if any(part in key.lower() for part in _SECRET_KEYS):
            return "[redacted]"
        if isinstance(value, str):
            return value[:4000] + ("...[truncated]" if len(value) > 4000 else "")
        if isinstance(value, dict):
            return {str(k): clean(str(k), v) for k, v in list(value.items())[:60]}
        if isinstance(value, list):
            return [clean(key, item) for item in value[:30]]
        return value

    return {str(key): clean(str(key), value) for key, value in event.items()}


async def publish(session_id: str, event: dict) -> None:
    event = _bound_runtime_event(dict(event))
    if session_id in _completed and event.get("type") == "agent_start":
        logger.warning("Ignoring late agent_start for completed session %s", session_id)
        return
    async with _publish_lock(session_id):
        event.setdefault("ts_unix", time.time())
        event.setdefault("ts_iso", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event["ts_unix"])))
        event_id = _next_id(session_id)
        _buffer(session_id, event_id, event)
        _write_session_log(session_id, event)
        # Await per-session persistence before the next event is assigned, so JSONL
        # cannot record a later event ID ahead of an earlier one.
        from backend.core.session_store import append_event as _ss_append
        await asyncio.to_thread(_ss_append, session_id, event_id, event)
        await asyncio.to_thread(_redis_append, session_id, event_id, event)
        try:
            from backend.run_ledger import record_run_event
            asyncio.create_task(asyncio.to_thread(record_run_event, session_id, event_id, event))
        except Exception:
            pass
        # Strip base64 before putting into SSE queue to prevent browser crashes
        sse_event = _strip_base64(event)
        try:
            # Durable control-plane event log (Wave 1). Dual-write, best-effort,
            # fire-and-forget -- silently no-ops if this session has no matching
            # astra_runs row (pre-Wave-1 session, or durable_create_run failed).
            # Stripped payload (not raw event) to avoid bloating Supabase storage
            # with base64 image blobs the SSE path already excludes.
            from backend.control_plane.supabase_repositories import durable_append_event
            asyncio.create_task(durable_append_event(session_id, str(event.get("type") or ""), sse_event))
        except Exception:
            pass
        await _get_queue(session_id).put((event_id, sse_event))
        if event.get("type") in ("goal_done", "goal_error"):
            _completed.add(session_id)
    # Forward agent status events to parent session so the root session view shows
    # live agent states from child sessions (e.g. dispatch_current_goal sub-runs).
    _etype = event.get("type")
    if _etype in {"agent_start", "agent_done", "agent_error"}:
        parent_sid = _parent_map.get(session_id)
        if parent_sid:
            forwarded = dict(sse_event, _forwarded_from=session_id)
            await publish(parent_sid, forwarded)
    # Event-driven goal ticking: when an agent finishes, mark the company goal's
    # tasks it owns (no timer). Cheap + best-effort; offloaded so it never blocks.
    _etype = event.get("type")
    if _etype in ("agent_done", "agent_start") and event.get("agent"):
        try:
            from backend.missions.goal_engine import tick_from_agent, mark_running
            _agent = str(event.get("agent"))
            if _etype == "agent_done":
                # Pass the agent's actual output so the goal engine can refuse to
                # check off a task the agent didn't really deliver (partial/error/
                # hollow output). The done payload lives under "result" (normal
                # path) or "output" (forced-synthesis path).
                _out = event.get("result")
                if _out is None:
                    _out = event.get("output")
                loop.run_in_executor(None, tick_from_agent, session_id, _agent, _out)
            else:
                loop.run_in_executor(None, mark_running, session_id, _agent)
            loop.run_in_executor(None, _persist_goal_status_memory, session_id, dict(event))
        except Exception:
            pass


_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def register_parent_session(child_sid: str, parent_sid: str) -> None:
    """Forward agent status events from child_sid to parent_sid's SSE stream."""
    if child_sid and parent_sid and child_sid != parent_sid:
        _parent_map[child_sid] = parent_sid


def reopen_session(session_id: str) -> None:
    """Remove completion marker so re-run agents can stream new events.
    Call before publishing agent_start on a session that previously errored/completed."""
    _completed.discard(session_id)


def publish_sync(session_id: str, event: dict) -> None:
    """Fire-and-forget from sync/thread context using the main event loop."""
    try:
        loop = _main_loop or asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(publish(session_id, event), loop)
    except RuntimeError:
        # No running loop (tests/scripts) — buffer synchronously
        event.setdefault("ts_unix", __import__("time").time())
        _buffer(session_id, _next_id(session_id), event)
    except Exception:
        pass


def input_response_push(request_id: str, data: dict) -> None:
    """Store founder's input response so the waiting agent can pick it up."""
    _input_responses[request_id] = data


async def input_response_wait(request_id: str, timeout: float = 300.0) -> dict | None:
    """Block until the founder submits input for this request_id (max 5 min)."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if request_id in _input_responses:
            return _input_responses.pop(request_id)
        await asyncio.sleep(0.5)
    return None


def approval_decision_push(session_id: str, request_id: str, expected_action_digest: str, decision: dict) -> None:
    """Store one request-bound founder decision for exactly one waiting action."""
    if not request_id or not expected_action_digest:
        raise ValueError("request_id and expected_action_digest are required for approval decisions")
    actual_request_id = str(decision.get("request_id") or decision.get("approval_id") or "")
    actual_digest = str(decision.get("action_digest") or decision.get("expected_action_digest") or "")
    if actual_request_id != request_id or actual_digest != expected_action_digest:
        raise ValueError("approval decision request_id/action_digest does not match the addressed request")
    _approval_decisions.setdefault(session_id, {})[request_id] = dict(decision)


async def approval_decision_wait(
    session_id: str,
    request_id: str,
    expected_action_digest: str,
    timeout: float = 300.0,
) -> dict | None:
    """Consume only a matching request-bound approval decision, once."""
    if not request_id or not expected_action_digest:
        raise ValueError("request_id and expected_action_digest are required for approval waits")
    import time
    if session_id not in _event_log:
        _restore_session(session_id)
    if session_id in _event_log and session_id not in _approval_decisions:
        _rebuild_approval_decisions(session_id, _event_log.get(session_id, []))
    if session_id not in _approval_ledger_rebuilt:
        _rebuild_approval_decisions_from_ledger(session_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        decision = _approval_decisions.get(session_id, {}).get(request_id)
        if decision and str(decision.get("action_digest") or decision.get("expected_action_digest") or "") == expected_action_digest:
            return _approval_decisions[session_id].pop(request_id)
        await asyncio.sleep(0.5)
    return None


# Drop buffered directives never consumed within this window — a directive targeted
# at an agent that already finished (or never runs) would otherwise leak forever.
_STEER_TTL = 1800.0


def _steer_fresh(item) -> bool:
    if isinstance(item, str):
        return True  # legacy plain string — no ts, keep
    return (time.time() - item.get("ts", 0)) < _STEER_TTL


def steer_push(session_id: str, message: str, agent_name: str = "") -> None:
    """Buffer a founder directive. agent_name="" = broadcast to all agents."""
    bucket = [it for it in _steer.get(session_id, []) if _steer_fresh(it)]  # GC stale on write
    bucket.append({"msg": message, "agent": agent_name.lower().strip(), "ts": time.time()})
    _steer[session_id] = bucket


def steer_pull(session_id: str, agent_name: str = "") -> list[str]:
    """Drain steer messages for this agent (broadcast + agent-targeted)."""
    name = agent_name.lower().strip()
    all_items = _steer.pop(session_id, [])
    kept = []
    out = []
    for item in all_items:
        if isinstance(item, str):
            out.append(item)  # legacy plain-string messages
        elif not _steer_fresh(item):
            continue  # expired — drop
        elif not item.get("agent") or item["agent"] == name:
            out.append(item["msg"])
        else:
            kept.append(item)  # targeted at a different agent — put back
    if kept:
        _steer[session_id] = kept
    return out


def steer_pending(session_id: str) -> list[dict]:
    """Fresh, undelivered directives still buffered for a session (for delivery feedback)."""
    return [it for it in _steer.get(session_id, []) if isinstance(it, dict) and _steer_fresh(it)]


def _fmt(event_id: int, event: dict) -> str:
    return f"id: {event_id}\ndata: {json.dumps(event)}\n\n"


def _restore_session(session_id: str) -> tuple[bool, bool]:
    """Try to restore session — JSONL first (durable), Redis as fallback.
    Returns (restored: bool, is_done: bool). Does NOT create asyncio objects (thread-safe).
    """
    from backend.core.session_store import load_events as _ss_load
    events = _ss_load(session_id) or _redis_load(session_id)
    if not events:
        return False, False
    deduplicated: dict[int, dict] = {}
    for event_id, event in sorted(events, key=lambda item: item[0]):
        deduplicated.setdefault(int(event_id), event)
    restored_events = list(deduplicated.items())
    _event_log[session_id] = restored_events
    _event_counters[session_id] = max(deduplicated, default=0)
    _rebuild_approval_decisions(session_id, restored_events)
    done = any(e.get("type") in ("goal_done", "goal_error") for _, e in restored_events)
    if done:
        _completed.add(session_id)
    return True, done


# Events that establish agent state — safe to replay on fresh connect without flooding the log
_STATE_EVENTS = frozenset({
    "goal_start", "plan_done", "goal_expanded", "detailed_plan", "company_name",
    "stack_selected", "stack_operating_plan", "stack_manifest", "stack_execution_contract", "stack_execution_blueprint", "stack_lane_status", "stack_approval_queue", "approval_request", "stack_approval_decision", "company_genome", "stack_artifact", "stack_artifact_verification", "saferun_action", "saferun_result", "outcome_recorded",
    "agent_start", "agent_done", "agent_error", "mirror_verdict",
    "goal_done", "goal_error",
})


async def stream_events(session_id: str, last_event_id: int | None = None) -> AsyncIterator[str]:
    """Async generator yielding SSE-formatted strings.
    - Auto-reconnect (Last-Event-ID header): replays only missed events.
    - Fresh connect (no Last-Event-ID): replays state-establishing events to rebuild UI
      without duplicating action log entries already in localStorage.
    - Falls back to Redis if session not in memory — survives backend restarts.
    """
    # Not in memory — try Redis restore before declaring expired
    if session_id not in _sessions and session_id not in _completed and session_id not in _event_log:
        restored, _ = await asyncio.to_thread(_restore_session, session_id)
        if not restored:
            yield _fmt(0, {"type": "session_expired"})
            return
        # Queue must be created on event loop thread, not inside the executor thread
        if session_id not in _sessions and session_id not in _completed:
            _sessions[session_id] = asyncio.Queue()

    # Replay buffered events
    if session_id in _event_log:
        if last_event_id is not None:
            # Auto-reconnect: replay only events missed since last seen
            for eid, ev in _event_log[session_id]:
                if eid > last_event_id:
                    yield _fmt(eid, _strip_base64(ev))
        else:
            # Fresh connect: replay state events only — skips action/thinking noise
            # that would duplicate log entries already restored from localStorage
            for eid, ev in _event_log[session_id]:
                if ev.get("type") in _STATE_EVENTS:
                    yield _fmt(eid, _strip_base64(ev))

    # Already completed — send closed signal immediately (after replay).
    # Use the actual terminal event type (goal_done vs goal_error) from the log.
    if session_id in _completed:
        _log = _event_log.get(session_id, [])
        _terminal = next(
            (e for _, e in reversed(_log) if e.get("type") in ("goal_done", "goal_error")),
            {"type": "goal_done"},
        )
        yield _fmt(_event_counters.get(session_id, 0), _terminal)
        return

    q = _get_queue(session_id)
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=30)
        except asyncio.TimeoutError:
            yield "data: {\"type\": \"ping\"}\n\n"
            continue

        event_id, event = item
        yield _fmt(event_id, event)
        if event.get("type") in ("goal_done", "goal_error"):
            _sessions.pop(session_id, None)
            _completed.add(session_id)
            break

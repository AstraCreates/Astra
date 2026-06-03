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
_approval_decisions: dict[str, dict[str, dict]] = {}  # session_id -> gate_key -> decision event

# Persistent event log per session: list of (event_id, event_dict)
_event_log: dict[str, list[tuple[int, dict]]] = {}
_event_counters: dict[str, int] = {}

_MAX_BUFFER = 2000  # max events kept per session
_REDIS_TTL = 8 * 3600  # 8 hours


# ── Redis helpers ──────────────────────────────────────────────────────────────

def _redis():
    """Return a connected Redis client or None if unavailable."""
    try:
        import redis as _redis_lib
        from backend.config import settings
        r = _redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _redis_append(session_id: str, event_id: int, event: dict) -> None:
    try:
        r = _redis()
        if not r:
            return
        key = f"events:{session_id}"
        r.rpush(key, json.dumps({"id": event_id, "event": event}))
        r.expire(key, _REDIS_TTL)
    except Exception:
        pass


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
        keys = r.keys("events:*")
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
    gate_key = event.get("gate_key")
    if not gate_key:
        return
    _approval_decisions.setdefault(session_id, {})[str(gate_key)] = event


def _rebuild_approval_decisions(session_id: str, events: list[tuple[int, dict]]) -> None:
    """Reconstruct approval wait state from a restored event log."""
    for _, event in events:
        _capture_approval_decision(session_id, event)


_SESSION_LOG_PATH = "/tmp/astra_session.log"
_KEY_EVENT_TYPES = {
    "goal_start", "goal_done", "goal_error",
    "agent_start", "agent_done", "agent_error",
    "agent_tool_call", "agent_thinking", "agent_action",
    "agent_unknown_action",
    "plan_done", "company_name", "goal_expanded",
    "stack_selected",
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


async def publish(session_id: str, event: dict) -> None:
    event.setdefault("ts_unix", time.time())
    event.setdefault("ts_iso", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event["ts_unix"])))
    event_id = _next_id(session_id)
    _buffer(session_id, event_id, event)
    _write_session_log(session_id, event)
    loop = asyncio.get_running_loop()
    # Persist full event (with base64) to JSONL store
    from backend.core.session_store import append_event as _ss_append
    loop.run_in_executor(None, _ss_append, session_id, event_id, event)
    # Also persist to Redis (fast in-flight buffer)
    loop.run_in_executor(None, _redis_append, session_id, event_id, event)
    try:
        from backend.run_ledger import record_run_event
        loop.run_in_executor(None, record_run_event, session_id, event_id, event)
    except Exception:
        pass
    # Strip base64 before putting into SSE queue to prevent browser crashes
    sse_event = _strip_base64(event)
    await _get_queue(session_id).put((event_id, sse_event))


_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


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


def approval_decision_push(session_id: str, gate_key: str, decision: dict) -> None:
    """Store a founder approval decision for SafeRun-gated tool execution."""
    _approval_decisions.setdefault(session_id, {})[gate_key] = decision


async def approval_decision_wait(session_id: str, gate_key: str, timeout: float = 300.0) -> dict | None:
    """Wait for a founder decision on a stack approval gate."""
    import time
    if session_id in _event_log:
        _rebuild_approval_decisions(session_id, _event_log.get(session_id, []))
    deadline = time.time() + timeout
    while time.time() < deadline:
        decision = _approval_decisions.get(session_id, {}).get(gate_key)
        if decision:
            return decision
        await asyncio.sleep(0.5)
    return None


def steer_push(session_id: str, message: str) -> None:
    """Buffer a founder directive for the agent loop to pick up."""
    if session_id not in _steer:
        _steer[session_id] = []
    _steer[session_id].append(message)


def steer_pull(session_id: str) -> list[str]:
    """Drain and return all pending steer messages for this session."""
    msgs = _steer.pop(session_id, [])
    return msgs


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
    _event_log[session_id] = events
    _event_counters[session_id] = max(eid for eid, _ in events)
    _rebuild_approval_decisions(session_id, events)
    done = any(e.get("type") in ("goal_done", "goal_error") for _, e in events)
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
                    yield _fmt(eid, ev)
        else:
            # Fresh connect: replay state events only — skips action/thinking noise
            # that would duplicate log entries already restored from localStorage
            for eid, ev in _event_log[session_id]:
                if ev.get("type") in _STATE_EVENTS:
                    yield _fmt(eid, ev)

    # Already completed — send closed signal immediately (after replay)
    if session_id in _completed:
        yield _fmt(_event_counters.get(session_id, 0), {"type": "goal_done"})
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

"""
In-process event bus for streaming agent progress to SSE clients.
One asyncio.Queue per session_id. Agent/orchestrator publish; SSE endpoint consumes.
All events are buffered so reconnecting clients can replay missed events.
Events are also persisted to Redis so sessions survive backend restarts.
"""
import asyncio
import json
import logging
from collections import deque
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_sessions: dict[str, asyncio.Queue] = {}
_completed: set[str] = set()  # sessions that finished — reconnect gets immediate replay + close
_steer: dict[str, list[str]] = {}  # inbound founder directives per session

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
    if len(log) > _MAX_BUFFER:
        log.pop(0)


async def publish(session_id: str, event: dict) -> None:
    event_id = _next_id(session_id)
    _buffer(session_id, event_id, event)
    # Fire-and-forget Redis write (don't block the event loop)
    asyncio.get_running_loop().run_in_executor(None, _redis_append, session_id, event_id, event)
    await _get_queue(session_id).put((event_id, event))


def publish_sync(session_id: str, event: dict) -> None:
    """Fire-and-forget from sync context (runs in same event loop)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(publish(session_id, event))
    except Exception:
        pass


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
    """Try to restore session from Redis into memory.
    Returns (restored: bool, is_done: bool). Does NOT create asyncio objects (thread-safe).
    """
    events = _redis_load(session_id)
    if not events:
        return False, False
    _event_log[session_id] = events
    _event_counters[session_id] = max(eid for eid, _ in events)
    is_done = any(e.get("type") in ("goal_done", "goal_error") for _, e in events)
    if is_done:
        _completed.add(session_id)
    return True, is_done


# Events that establish agent state — safe to replay on fresh connect without flooding the log
_STATE_EVENTS = frozenset({
    "goal_start", "plan_done", "goal_expanded", "detailed_plan",
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

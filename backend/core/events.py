"""
In-process event bus for streaming agent progress to SSE clients.
One asyncio.Queue per session_id. Agent/orchestrator publish; SSE endpoint consumes.
All events are buffered so reconnecting clients can replay missed events.
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


async def stream_events(session_id: str, last_event_id: int | None = None) -> AsyncIterator[str]:
    """Async generator yielding SSE-formatted strings.
    If last_event_id is provided, replays all buffered events after that id first.
    """
    # Unknown session (server restart / old session) — tell client it's done
    if session_id not in _sessions and session_id not in _completed and session_id not in _event_log:
        yield _fmt(0, {"type": "session_expired"})
        return

    # Replay missed events if client reconnects with Last-Event-ID
    if last_event_id is not None and session_id in _event_log:
        for eid, ev in _event_log[session_id]:
            if eid > last_event_id:
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

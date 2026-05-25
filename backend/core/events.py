"""
In-process event bus for streaming agent progress to SSE clients.
One asyncio.Queue per session_id. Agent/orchestrator publish; SSE endpoint consumes.
"""
import asyncio
import json
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_sessions: dict[str, asyncio.Queue] = {}
_completed: set[str] = {}  # sessions that finished — reconnect gets immediate closed signal
_steer: dict[str, list[str]] = {}  # inbound founder directives per session


def _get_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _sessions:
        _sessions[session_id] = asyncio.Queue()
    return _sessions[session_id]


async def publish(session_id: str, event: dict) -> None:
    await _get_queue(session_id).put(event)


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


async def stream_events(session_id: str) -> AsyncIterator[str]:
    """Async generator yielding SSE-formatted strings."""
    # Unknown session (server restart / old session) — tell client it's done
    if session_id not in _sessions and session_id not in _completed:
        yield "data: {\"type\": \"session_expired\"}\n\n"
        return

    # Already completed — send closed signal immediately
    if session_id in _completed:
        yield "data: {\"type\": \"goal_done\"}\n\n"
        return

    q = _get_queue(session_id)
    while True:
        try:
            event = await asyncio.wait_for(q.get(), timeout=30)
        except asyncio.TimeoutError:
            yield "data: {\"type\": \"ping\"}\n\n"
            continue
        yield f"data: {json.dumps(event)}\n\n"
        if event.get("type") in ("goal_done", "goal_error"):
            _sessions.pop(session_id, None)
            _completed.add(session_id)
            break

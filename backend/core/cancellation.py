"""Session kill switch.

Tracks the asyncio task running each session so it can be cancelled
immediately, plus a cooperative 'killed' flag the orchestrator checks
between agent steps (in-flight work in worker threads can't be force-killed,
so the flag stops the loop from continuing once the cancel lands).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid

logger = logging.getLogger(__name__)

_tasks: dict[str, dict[str, asyncio.Task]] = {}
_killed: set[str] = set()
_paused: set[str] = set()
_killed_agents: set[str] = set()  # "session_id::agent_name" — stop ONE agent, not the run
_attempt_agents: dict[tuple[str, str], str] = {}
_fences: dict[str, threading.Event] = {}
_lock = threading.RLock()


def _agent_key(session_id: str, agent_name: str) -> str:
    return f"{session_id}::{(agent_name or '').lower().strip()}"


def claim_attempt(session_id: str, agent_name: str) -> str | None:
    """Atomically reserve one run+agent slot before scheduling a rerun."""
    normalized_agent = (agent_name or "").lower().strip()
    if not normalized_agent:
        raise ValueError("agent_name is required to claim a rerun attempt")
    key = (session_id, normalized_agent)
    with _lock:
        existing = _attempt_agents.get(key)
        if existing:
            return None
        if not _tasks.get(session_id):
            _killed.discard(session_id)
            _fences.setdefault(session_id, threading.Event()).clear()
        attempt_id = f"{normalized_agent}:{uuid.uuid4()}"
        _attempt_agents[key] = attempt_id
        return attempt_id


def register_task(session_id: str, task: asyncio.Task, *, attempt_id: str | None = None, agent_name: str = "") -> str:
    """Track an attempt without replacing other active attempts for a session."""
    attempt_id = attempt_id or f"run:{uuid.uuid4()}"
    normalized_agent = (agent_name or "").lower().strip()
    with _lock:
        _tasks.setdefault(session_id, {})[attempt_id] = task
        _fences.setdefault(session_id, threading.Event())
        if normalized_agent:
            _attempt_agents[(session_id, normalized_agent)] = attempt_id
    task.add_done_callback(lambda _task: release_attempt(session_id, attempt_id))
    return attempt_id


def release_attempt(session_id: str, attempt_id: str) -> None:
    """Release only the completed attempt; sibling attempts remain cancellable."""
    with _lock:
        attempts = _tasks.get(session_id, {})
        attempts.pop(attempt_id, None)
        if not attempts:
            _tasks.pop(session_id, None)
        for key, value in list(_attempt_agents.items()):
            if key[0] == session_id and value == attempt_id:
                _attempt_agents.pop(key, None)
        if session_id not in _tasks:
            _paused.discard(session_id)
            prefix = f"{session_id}::"
            for key in [key for key in _killed_agents if key.startswith(prefix)]:
                _killed_agents.discard(key)


def clear(session_id: str) -> None:
    """Compatibility cleanup that never drops a still-active sibling attempt."""
    with _lock:
        for attempt_id, task in list(_tasks.get(session_id, {}).items()):
            if task.done():
                release_attempt(session_id, attempt_id)


def request_kill_agent(session_id: str, agent_name: str) -> None:
    """Flag ONE agent in a session to stop at its next loop step. Unlike request_kill
    this leaves the rest of the run alive — the agent's loop checks is_agent_killed()
    each iteration and exits cleanly (in-flight tool work in a worker thread still
    finishes, but no further steps run)."""
    _killed_agents.add(_agent_key(session_id, agent_name))
    logger.info("Stop agent: %s in session %s flagged", agent_name, session_id)


def is_agent_killed(session_id: str, agent_name: str) -> bool:
    return session_id in _killed or _agent_key(session_id, agent_name) in _killed_agents


def pause_session(session_id: str) -> None:
    _paused.add(session_id)
    logger.info("Pause: session %s paused", session_id)


def resume_session(session_id: str) -> None:
    _paused.discard(session_id)
    logger.info("Pause: session %s resumed", session_id)


def is_paused(session_id: str) -> bool:
    return session_id in _paused


async def wait_if_paused(session_id: str, poll_interval: float = 1.0) -> None:
    """Async-sleep until the session is no longer paused or is killed."""
    while is_paused(session_id) and not is_killed(session_id):
        await asyncio.sleep(poll_interval)


def is_killed(session_id: str) -> bool:
    return session_id in _killed


def cancellation_fence(session_id: str, agent_name: str = "") -> threading.Event:
    """Persistent cooperative fence available to tools that opt in."""
    with _lock:
        fence = _fences.setdefault(session_id, threading.Event())
        if is_agent_killed(session_id, agent_name):
            fence.set()
        return fence


def check_fence(session_id: str, agent_name: str = "") -> None:
    """Fail before entering a tool boundary when a session/agent was cancelled."""
    if cancellation_fence(session_id, agent_name).is_set():
        raise asyncio.CancelledError(f"session {session_id} was cancelled before tool execution")


def run_sync_with_fence(session_id: str, agent_name: str, fn, args: dict):
    """Check in the worker thread immediately before invoking synchronous tool code."""
    check_fence(session_id, agent_name)
    return fn(**args)


def request_kill(session_id: str) -> bool:
    """Mark the session killed and cancel its task immediately.

    Returns True if a running task was found and cancelled.
    """
    with _lock:
        _killed.add(session_id)
        _fences.setdefault(session_id, threading.Event()).set()
        tasks = [task for task in _tasks.get(session_id, {}).values() if not task.done()]
    try:
        from backend.runtime.delegation import interrupt_session_subagents
        interrupt_session_subagents(session_id)
    except Exception:
        pass
    if tasks:
        for task in tasks:
            task.cancel()
        logger.info("Kill switch: cancelled %d active attempt(s) for session %s", len(tasks), session_id)
        return True
    logger.info("Kill switch: session %s flagged (no live task to cancel)", session_id)
    return False

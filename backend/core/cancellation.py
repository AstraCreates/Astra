"""Session kill switch.

Tracks the asyncio task running each session so it can be cancelled
immediately, plus a cooperative 'killed' flag the orchestrator checks
between agent steps (in-flight work in worker threads can't be force-killed,
so the flag stops the loop from continuing once the cancel lands).
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}
_killed: set[str] = set()
_paused: set[str] = set()
_killed_agents: set[str] = set()  # "session_id::agent_name" — stop ONE agent, not the run


def _agent_key(session_id: str, agent_name: str) -> str:
    return f"{session_id}::{(agent_name or '').lower().strip()}"


def register_task(session_id: str, task: asyncio.Task) -> None:
    _tasks[session_id] = task


def clear(session_id: str) -> None:
    _tasks.pop(session_id, None)
    _killed.discard(session_id)
    _paused.discard(session_id)
    prefix = f"{session_id}::"
    for k in [k for k in _killed_agents if k.startswith(prefix)]:
        _killed_agents.discard(k)


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


def request_kill(session_id: str) -> bool:
    """Mark the session killed and cancel its task immediately.

    Returns True if a running task was found and cancelled.
    """
    _killed.add(session_id)
    try:
        from backend.runtime.delegation import interrupt_session_subagents
        interrupt_session_subagents(session_id)
    except Exception:
        pass
    task = _tasks.get(session_id)
    if task is not None and not task.done():
        task.cancel()
        logger.info("Kill switch: cancelled session %s", session_id)
        return True
    logger.info("Kill switch: session %s flagged (no live task to cancel)", session_id)
    return False

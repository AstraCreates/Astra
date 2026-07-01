"""Compact per-agent runtime state store.

Stores the agent scratchpad outside the conversation transcript so the loop can
inject only a small snapshot each turn instead of retaining long histories in
messages. Uses Redis when available and falls back to in-process memory.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from backend.config import settings

_PREFIX = "astra:agent_state:"
_TTL_SECONDS = 6 * 60 * 60
_MEMORY: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_REDIS_CLIENT = None
_REDIS_FAILED_AT = 0.0


def _redis():
    global _REDIS_CLIENT, _REDIS_FAILED_AT
    if _REDIS_CLIENT not in (None, False):
        return _REDIS_CLIENT
    now = time.monotonic()
    if _REDIS_CLIENT is False and now - _REDIS_FAILED_AT < 30.0:
        return None
    try:
        import redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _REDIS_CLIENT = client
        return client
    except Exception:
        _REDIS_CLIENT = False
        _REDIS_FAILED_AT = now
        return None


def _key(session_id: str, agent_name: str, task_id: str = "") -> str:
    return f"{_PREFIX}{session_id}:{agent_name}:{task_id or 'root'}"


def _default_state() -> dict[str, Any]:
    return {
        "plan": "",
        "recent_tools": [],
        "tool_memory": {},
        "artifacts": [],
        "blockers": [],
        "next_steps": ["Read the task brief, then execute the next highest-value step."],
    }


def load_agent_state(session_id: str, agent_name: str, task_id: str = "") -> dict[str, Any]:
    key = _key(session_id, agent_name, task_id)
    client = _redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return {**_default_state(), **parsed}
        except Exception:
            pass
    with _LOCK:
        return {**_default_state(), **_MEMORY.get(key, {})}


def save_agent_state(session_id: str, agent_name: str, task_id: str, state: dict[str, Any]) -> None:
    key = _key(session_id, agent_name, task_id)
    compact = {
        "plan": str(state.get("plan") or "")[:1200],
        "recent_tools": list(state.get("recent_tools") or [])[-8:],
        "tool_memory": {
            str(k)[:80]: list(v or [])[-4:]
            for k, v in dict(state.get("tool_memory") or {}).items()
        },
        "artifacts": list(state.get("artifacts") or [])[-8:],
        "blockers": list(state.get("blockers") or [])[-6:],
        "next_steps": list(state.get("next_steps") or [])[-6:],
    }
    client = _redis()
    if client is not None:
        try:
            client.setex(key, _TTL_SECONDS, json.dumps(compact, default=str))
            return
        except Exception:
            pass
    with _LOCK:
        _MEMORY[key] = compact


def state_snapshot(
    session_id: str,
    agent_name: str,
    task_id: str = "",
    *,
    sections: tuple[str, ...] = ("plan", "recent_tools", "artifacts", "blockers", "next_steps"),
) -> dict[str, Any]:
    state = load_agent_state(session_id, agent_name, task_id)
    return {name: state.get(name) for name in sections}


def relevant_state_snapshot(
    session_id: str,
    agent_name: str,
    task_id: str = "",
    *,
    query: str = "",
    sections: tuple[str, ...] = ("plan", "recent_tools", "artifacts", "blockers", "next_steps"),
) -> dict[str, Any]:
    state = load_agent_state(session_id, agent_name, task_id)
    q = " ".join(str(query or "").lower().split())
    tool_memory = dict(state.get("tool_memory") or {})
    selected_tools: list[str] = []
    if q:
        for tool_name in tool_memory:
            if tool_name.lower() in q or any(token and token in tool_name.lower() for token in q.split()):
                selected_tools.append(tool_name)
    if not selected_tools:
        selected_tools = list(tool_memory.keys())[-2:]
    selected_recent: list[str] = []
    for tool_name in selected_tools:
        selected_recent.extend(list(tool_memory.get(tool_name) or [])[-2:])
    if not selected_recent:
        selected_recent = list(state.get("recent_tools") or [])[-3:]
    snapshot = {
        "plan": state.get("plan"),
        "recent_tools": selected_recent[-4:],
        "artifacts": list(state.get("artifacts") or [])[-4:],
        "blockers": list(state.get("blockers") or [])[-3:],
        "next_steps": list(state.get("next_steps") or [])[-3:],
    }
    return {name: snapshot.get(name) for name in sections}


def reset_agent_state(session_id: str, agent_name: str, task_id: str = "") -> None:
    key = _key(session_id, agent_name, task_id)
    client = _redis()
    if client is not None:
        try:
            client.delete(key)
        except Exception:
            pass
    with _LOCK:
        _MEMORY.pop(key, None)

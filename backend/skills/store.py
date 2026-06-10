"""Skills store — reusable guidance packages attached to agents.

Storage layout:
  $OBSIDIAN_VAULT/skills/{founder_id}/index.json
    {
      "<skill_id>": {
        "id": "...",
        "founder_id": "...",
        "name": "...",
        "description": "...",
        "content": "...",       # markdown
        "agent_keys": [...],    # which agents this skill is attached to
        "created_at": "...",
        "is_builtin": false
      },
      ...
    }

Thread-safe via a single process-level Lock.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _skills_dir(founder_id: str) -> Path:
    d = _vault() / "skills" / founder_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(founder_id: str) -> Path:
    return _skills_dir(founder_id) / "index.json"


# ---------------------------------------------------------------------------
# Low-level index I/O
# ---------------------------------------------------------------------------

def _load_index(founder_id: str) -> dict[str, Any]:
    p = _index_path(founder_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_index(founder_id: str, index: dict[str, Any]) -> None:
    _index_path(founder_id).write_text(
        json.dumps(index, indent=2, sort_keys=True)
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_skill(
    founder_id: str,
    name: str,
    description: str = "",
    content: str = "",
    agent_keys: list[str] | None = None,
    is_builtin: bool = False,
) -> dict[str, Any]:
    """Create a new skill and persist it. Returns the skill dict."""
    skill_id = uuid.uuid4().hex[:20]
    skill: dict[str, Any] = {
        "id": skill_id,
        "founder_id": founder_id,
        "name": name,
        "description": description,
        "content": content,
        "agent_keys": agent_keys or [],
        "created_at": _now(),
        "is_builtin": is_builtin,
        "status": "active",
        "version": 1,
        "version_history": [],
    }
    with _lock:
        index = _load_index(founder_id)
        index[skill_id] = skill
        _save_index(founder_id, index)
    logger.info("Skill created: %s (founder=%s, name=%r)", skill_id, founder_id, name)
    return skill


def get_skill(founder_id: str, skill_id: str) -> dict[str, Any] | None:
    """Return a single skill or None if not found."""
    with _lock:
        index = _load_index(founder_id)
    return index.get(skill_id)


def list_skills(founder_id: str) -> list[dict[str, Any]]:
    """Return all skills for a founder, newest first."""
    with _lock:
        index = _load_index(founder_id)
    skills = list(index.values())
    skills.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return skills


def update_skill(
    founder_id: str,
    skill_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    content: str | None = None,
    agent_keys: list[str] | None = None,
    version: int | None = None,
    version_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Patch a skill's mutable fields. Returns updated skill or None if missing."""
    with _lock:
        index = _load_index(founder_id)
        skill = index.get(skill_id)
        if skill is None:
            return None
        if name is not None:
            skill["name"] = name
        if description is not None:
            skill["description"] = description
        if content is not None:
            skill["content"] = content
        if agent_keys is not None:
            skill["agent_keys"] = agent_keys
        if version is not None:
            skill["version"] = version
        if version_history is not None:
            skill["version_history"] = version_history
        index[skill_id] = skill
        _save_index(founder_id, index)
    return skill


def delete_skill(founder_id: str, skill_id: str) -> bool:
    """Delete a skill. Returns True if it existed, False if not found."""
    with _lock:
        index = _load_index(founder_id)
        if skill_id not in index:
            return False
        del index[skill_id]
        _save_index(founder_id, index)
    logger.info("Skill deleted: %s (founder=%s)", skill_id, founder_id)
    return True


def attach_skill(founder_id: str, skill_id: str, agent_key: str) -> dict[str, Any] | None:
    """Attach a skill to an agent. Idempotent. Returns updated skill or None."""
    with _lock:
        index = _load_index(founder_id)
        skill = index.get(skill_id)
        if skill is None:
            return None
        keys: list[str] = skill.get("agent_keys") or []
        if agent_key not in keys:
            keys.append(agent_key)
        skill["agent_keys"] = keys
        index[skill_id] = skill
        _save_index(founder_id, index)
    return skill


def detach_skill(founder_id: str, skill_id: str, agent_key: str) -> dict[str, Any] | None:
    """Detach a skill from an agent. Idempotent. Returns updated skill or None."""
    with _lock:
        index = _load_index(founder_id)
        skill = index.get(skill_id)
        if skill is None:
            return None
        keys: list[str] = skill.get("agent_keys") or []
        skill["agent_keys"] = [k for k in keys if k != agent_key]
        index[skill_id] = skill
        _save_index(founder_id, index)
    return skill


def get_skills_for_agent(founder_id: str, agent_key: str) -> list[dict[str, Any]]:
    """Return all skills attached to a specific agent key, ordered by created_at."""
    skills = list_skills(founder_id)
    return [s for s in skills if agent_key in (s.get("agent_keys") or [])]

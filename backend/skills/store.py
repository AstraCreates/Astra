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

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.core.json_store import read_json, update_json, write_json_atomic

logger = logging.getLogger(__name__)

_lock = threading.RLock()


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
    data = read_json(_index_path(founder_id), {})
    return data if isinstance(data, dict) else {}


def _save_index(founder_id: str, index: dict[str, Any]) -> None:
    write_json_atomic(_index_path(founder_id), index, sort_keys=True)


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
        def apply(index: object) -> dict[str, Any]:
            updated = index if isinstance(index, dict) else {}
            updated[skill_id] = skill
            return updated

        update_json(_index_path(founder_id), {}, apply, sort_keys=True)
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
    updated_skill: dict[str, Any] | None = None

    with _lock:
        def apply(index: object) -> dict[str, Any]:
            nonlocal updated_skill
            updated = index if isinstance(index, dict) else {}
            skill = updated.get(skill_id)
            if skill is None:
                return updated
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
            updated[skill_id] = skill
            updated_skill = skill
            return updated

        update_json(_index_path(founder_id), {}, apply, sort_keys=True)
    return updated_skill


def delete_skill(founder_id: str, skill_id: str) -> bool:
    """Delete a skill. Returns True if it existed, False if not found."""
    deleted = False

    with _lock:
        def apply(index: object) -> dict[str, Any]:
            nonlocal deleted
            updated = index if isinstance(index, dict) else {}
            deleted = skill_id in updated
            if deleted:
                del updated[skill_id]
            return updated

        update_json(_index_path(founder_id), {}, apply, sort_keys=True)
    if deleted:
        logger.info("Skill deleted: %s (founder=%s)", skill_id, founder_id)
    return deleted


def attach_skill(founder_id: str, skill_id: str, agent_key: str) -> dict[str, Any] | None:
    """Attach a skill to an agent. Idempotent. Returns updated skill or None."""
    updated_skill: dict[str, Any] | None = None

    with _lock:
        def apply(index: object) -> dict[str, Any]:
            nonlocal updated_skill
            updated = index if isinstance(index, dict) else {}
            skill = updated.get(skill_id)
            if skill is None:
                return updated
            keys: list[str] = skill.get("agent_keys") or []
            if agent_key not in keys:
                keys.append(agent_key)
            skill["agent_keys"] = keys
            updated[skill_id] = skill
            updated_skill = skill
            return updated

        update_json(_index_path(founder_id), {}, apply, sort_keys=True)
    return updated_skill


def detach_skill(founder_id: str, skill_id: str, agent_key: str) -> dict[str, Any] | None:
    """Detach a skill from an agent. Idempotent. Returns updated skill or None."""
    updated_skill: dict[str, Any] | None = None

    with _lock:
        def apply(index: object) -> dict[str, Any]:
            nonlocal updated_skill
            updated = index if isinstance(index, dict) else {}
            skill = updated.get(skill_id)
            if skill is None:
                return updated
            keys: list[str] = skill.get("agent_keys") or []
            skill["agent_keys"] = [k for k in keys if k != agent_key]
            updated[skill_id] = skill
            updated_skill = skill
            return updated

        update_json(_index_path(founder_id), {}, apply, sort_keys=True)
    return updated_skill


def get_skills_for_agent(founder_id: str, agent_key: str) -> list[dict[str, Any]]:
    """Return all skills attached to a specific agent key, ordered by created_at."""
    skills = list_skills(founder_id)
    return [s for s in skills if agent_key in (s.get("agent_keys") or [])]

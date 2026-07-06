"""Thread-safe per-founder model override store.

Files live at:
  $OBSIDIAN_VAULT/model_settings/{founder_id}.json

Each file is a flat JSON object: { agent_key -> model_name }
A special key "global" maps to /data/astra_docs/model_settings/global.json.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.core.json_store import read_json, update_json

logger = logging.getLogger(__name__)


def _store_dir() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    return Path(vault) / "model_settings"


def _founder_path(founder_id: str) -> Path:
    return _store_dir() / f"{founder_id}.json"


def _load(founder_id: str) -> dict[str, str]:
    data = read_json(_founder_path(founder_id), {})
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


def _normalize_overrides(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def set_model_override(founder_id: str, agent_key: str, model: str) -> None:
    """Set a model override for a specific agent for a founder."""

    def apply(overrides: object) -> dict[str, str]:
        normalized = _normalize_overrides(overrides)
        normalized[agent_key] = model
        return normalized

    update_json(_founder_path(founder_id), {}, apply, sort_keys=True)
    logger.info("Model override set: founder=%s agent=%s model=%s", founder_id, agent_key, model)


def get_model_override(founder_id: str, agent_key: str) -> str | None:
    """Return the overridden model for an agent, or None if not set."""
    return _load(founder_id).get(agent_key)


def get_all_overrides(founder_id: str) -> dict[str, str]:
    """Return all model overrides for a founder: { agent_key -> model }."""
    return dict(_load(founder_id))


def clear_override(founder_id: str, agent_key: str) -> bool:
    """Remove a model override. Returns True if it existed, False otherwise."""
    existed = False

    def apply(overrides: object) -> dict[str, str]:
        nonlocal existed
        normalized = _normalize_overrides(overrides)
        existed = agent_key in normalized
        if existed:
            del normalized[agent_key]
        return normalized

    update_json(_founder_path(founder_id), {}, apply, sort_keys=True)
    if existed:
        logger.info("Model override cleared: founder=%s agent=%s", founder_id, agent_key)
    return existed

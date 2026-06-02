"""Thread-safe per-founder model override store.

Files live at:
  $OBSIDIAN_VAULT/model_settings/{founder_id}.json

Each file is a flat JSON object: { agent_key -> model_name }
A special key "global" maps to /data/astra_docs/model_settings/global.json.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _store_dir() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    d = Path(vault) / "model_settings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _founder_path(founder_id: str) -> Path:
    return _store_dir() / f"{founder_id}.json"


def _load(founder_id: str) -> dict[str, str]:
    p = _founder_path(founder_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        return {}
    except Exception:
        return {}


def _save(founder_id: str, overrides: dict[str, str]) -> None:
    p = _founder_path(founder_id)
    p.write_text(json.dumps(overrides, indent=2, sort_keys=True))


def set_model_override(founder_id: str, agent_key: str, model: str) -> None:
    """Set a model override for a specific agent for a founder."""
    with _lock:
        overrides = _load(founder_id)
        overrides[agent_key] = model
        _save(founder_id, overrides)
    logger.info("Model override set: founder=%s agent=%s model=%s", founder_id, agent_key, model)


def get_model_override(founder_id: str, agent_key: str) -> str | None:
    """Return the overridden model for an agent, or None if not set."""
    with _lock:
        overrides = _load(founder_id)
    return overrides.get(agent_key)


def get_all_overrides(founder_id: str) -> dict[str, str]:
    """Return all model overrides for a founder: { agent_key -> model }."""
    with _lock:
        return dict(_load(founder_id))


def clear_override(founder_id: str, agent_key: str) -> bool:
    """Remove a model override. Returns True if it existed, False otherwise."""
    with _lock:
        overrides = _load(founder_id)
        existed = agent_key in overrides
        if existed:
            del overrides[agent_key]
            _save(founder_id, overrides)
    if existed:
        logger.info("Model override cleared: founder=%s agent=%s", founder_id, agent_key)
    return existed

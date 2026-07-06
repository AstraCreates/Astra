"""Deployment store — persists staging/production deployment state per session.

Storage layout:
  /data/astra_docs/deployments/
    index.json                 — { session_id -> deployment_record } for fast listing
    {session_id}.json          — individual deployment record (redundant for safety)

Each deployment record:
  {
    "session_id": str,
    "founder_id": str,
    "staging_url": str,
    "prod_url": str | null,
    "staged_at": ISO8601,
    "published_at": ISO8601 | null,
    "status": "staged" | "published" | "none"
  }
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from backend.core.json_store import read_json, write_json_atomic

logger = logging.getLogger(__name__)

_lock = threading.RLock()


# ── Storage paths ──────────────────────────────────────────────────────────────

def _deployments_dir() -> Path:
    base = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    return base / "deployments"


def _index_path() -> Path:
    return _deployments_dir() / "index.json"


def _record_path(session_id: str) -> Path:
    return _deployments_dir() / f"{session_id}.json"


# ── Index helpers ──────────────────────────────────────────────────────────────

def _load_index() -> dict[str, Any]:
    data = read_json(_index_path(), {})
    return data if isinstance(data, dict) else {}


def _save_index(index: dict[str, Any]) -> None:
    write_json_atomic(_index_path(), index, sort_keys=True)


# ── Public API ─────────────────────────────────────────────────────────────────

def record_deployment(session_id: str, founder_id: str, staging_url: str) -> dict:
    """Create or update a deployment record with a new staging URL.

    Idempotent — calling again with a different staging_url updates the record
    and resets status to 'staged'.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record: dict[str, Any] = {
        "session_id": session_id,
        "founder_id": founder_id,
        "staging_url": staging_url,
        "prod_url": None,
        "staged_at": now,
        "published_at": None,
        "status": "staged",
    }
    with _lock:
        # Preserve existing prod_url / published_at if this is an update
        existing = _load_single(session_id)
        if existing and existing.get("prod_url"):
            record["prod_url"] = existing["prod_url"]
            record["published_at"] = existing.get("published_at")
            record["status"] = existing.get("status", "staged")

        write_json_atomic(_record_path(session_id), record)
        index = _load_index()
        index[session_id] = record
        _save_index(index)

    logger.info("record_deployment: session=%s staging_url=%s", session_id, staging_url)
    return record


def publish_deployment(session_id: str, prod_url: str) -> dict | None:
    """Promote a staged deployment to production.

    Updates status to 'published', sets prod_url and published_at.
    Returns the updated record, or None if the session has no deployment record.
    """
    with _lock:
        record = _load_single(session_id)
        if record is None:
            logger.warning("publish_deployment: no record for session=%s", session_id)
            return None

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["prod_url"] = prod_url
        record["published_at"] = now
        record["status"] = "published"

        write_json_atomic(_record_path(session_id), record)
        index = _load_index()
        index[session_id] = record
        _save_index(index)

    logger.info("publish_deployment: session=%s prod_url=%s", session_id, prod_url)
    return record


def get_deployment(session_id: str) -> dict | None:
    """Return the deployment record for a session, or None if not found."""
    with _lock:
        return _load_single(session_id)


def list_deployments(founder_id: str) -> list[dict]:
    """Return all deployment records for a founder, newest first."""
    with _lock:
        index = _load_index()
    records = [v for v in index.values() if v.get("founder_id") == founder_id]
    records.sort(key=lambda r: r.get("staged_at", ""), reverse=True)
    return records


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_single(session_id: str) -> dict | None:
    """Load a single record. Tries per-session file first, falls back to index."""
    p = _record_path(session_id)
    if p.exists():
        record = read_json(p, None)
        if isinstance(record, dict):
            return record
    # Fallback: check index
    index = _load_index()
    return index.get(session_id)

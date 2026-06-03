"""Durable session store.

Every session gets a directory in the persistent Docker volume:
  $OBSIDIAN_VAULT/sessions/{session_id}/
    events.jsonl       — full event log, one JSON object per line
    meta.json          — session metadata (goal, founder, stack, timestamps, status)

A global index is maintained at:
  $OBSIDIAN_VAULT/sessions/index.json

This survives backend restarts indefinitely (no TTL, no cap).
Recovery on startup scans JSONL files — Redis is used only as a fast
in-flight buffer for the current run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ── Paths ──────────────────────────────────────────────────────────────────────

def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    path.mkdir(parents=True, exist_ok=True)
    return path

def session_dir(session_id: str) -> Path:
    d = _vault() / "sessions" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def events_path(session_id: str) -> Path:
    return session_dir(session_id) / "events.jsonl"

def meta_path(session_id: str) -> Path:
    return session_dir(session_id) / "meta.json"

def _index_path() -> Path:
    (_vault() / "sessions").mkdir(parents=True, exist_ok=True)
    return _vault() / "sessions" / "index.json"


# ── Index ──────────────────────────────────────────────────────────────────────

def _load_index() -> dict[str, Any]:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def _save_index(index: dict[str, Any]) -> None:
    _index_path().write_text(json.dumps(index, indent=2, sort_keys=True))


# ── Session registration ───────────────────────────────────────────────────────

def register_session(
    session_id: str,
    founder_id: str,
    goal: str,
    stack_id: str = "",
    company_name: str = "",
    agents: list[str] | None = None,
) -> None:
    meta = {
        "session_id": session_id,
        "founder_id": founder_id,
        "goal": goal,
        "stack_id": stack_id,
        "company_name": company_name,
        "agents": agents or [],
        "status": "running",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "completed_at": None,
        "artifact_count": 0,
    }
    with _lock:
        meta_path(session_id).write_text(json.dumps(meta, indent=2))
        index = _load_index()
        index[session_id] = {k: meta[k] for k in ("session_id", "founder_id", "goal", "stack_id", "status", "created_at", "completed_at")}
        _save_index(index)


def update_session_status(session_id: str, status: str, artifact_count: int | None = None) -> None:
    with _lock:
        p = meta_path(session_id)
        try:
            meta = json.loads(p.read_text()) if p.exists() else {"session_id": session_id}
        except Exception:
            meta = {"session_id": session_id}
        meta["status"] = status
        if status in ("done", "error"):
            meta["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if artifact_count is not None:
            meta["artifact_count"] = artifact_count
        p.write_text(json.dumps(meta, indent=2))
        # Update index
        index = _load_index()
        if session_id in index:
            index[session_id]["status"] = status
            index[session_id]["completed_at"] = meta.get("completed_at")
            _save_index(index)


# ── Event persistence ──────────────────────────────────────────────────────────

def append_event(session_id: str, event_id: int, event: dict) -> None:
    """Append one event to the session's JSONL file. Thread-safe."""
    line = json.dumps({"id": event_id, "event": event}, separators=(",", ":")) + "\n"
    try:
        with _lock:
            with events_path(session_id).open("a") as f:
                f.write(line)
        # Mark done/error in meta
        etype = event.get("type")
        if etype == "goal_done":
            update_session_status(session_id, "done")
        elif etype == "goal_error":
            update_session_status(session_id, "error")
        elif etype == "stack_artifact":
            _increment_artifacts(session_id)
    except Exception as exc:
        logger.warning("session_store.append_event failed for %s: %s", session_id, exc)


def _increment_artifacts(session_id: str) -> None:
    p = meta_path(session_id)
    try:
        meta = json.loads(p.read_text()) if p.exists() else {}
        meta["artifact_count"] = meta.get("artifact_count", 0) + 1
        p.write_text(json.dumps(meta, indent=2))
    except Exception:
        pass


def load_events(session_id: str) -> list[tuple[int, dict]] | None:
    """Load full event log from JSONL. Returns None if not found."""
    p = events_path(session_id)
    if not p.exists() or p.stat().st_size == 0:
        return None
    result = []
    try:
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                result.append((int(obj["id"]), obj["event"]))
        return result if result else None
    except Exception as exc:
        logger.warning("session_store.load_events failed for %s: %s", session_id, exc)
        return None


def is_done(session_id: str) -> bool:
    """Check if a session completed by inspecting meta.json."""
    p = meta_path(session_id)
    if not p.exists():
        return False
    try:
        meta = json.loads(p.read_text())
        return meta.get("status") in ("done", "error")
    except Exception:
        return False


# ── Session listing ────────────────────────────────────────────────────────────

def list_sessions(founder_id: str | None = None, limit: int = 100) -> list[dict]:
    """Return sessions from the index, newest first."""
    with _lock:
        index = _load_index()
    sessions = list(index.values())
    if founder_id:
        sessions = [s for s in sessions if s.get("founder_id") == founder_id]
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions[:limit]


def delete_session(session_id: str) -> bool:
    """Permanently remove a session's directory and index entry. Returns True if anything was removed."""
    import shutil
    removed = False
    with _lock:
        d = _vault() / "sessions" / session_id
        if d.exists():
            try:
                shutil.rmtree(d)
                removed = True
            except Exception as exc:
                logger.warning("session_store.delete_session rmtree failed for %s: %s", session_id, exc)
        index = _load_index()
        if session_id in index:
            del index[session_id]
            _save_index(index)
            removed = True
    return removed


def get_session_meta(session_id: str) -> dict | None:
    p = meta_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def scan_interrupted() -> list[str]:
    """Return session IDs that were running when the backend last died."""
    with _lock:
        index = _load_index()
    return [sid for sid, s in index.items() if s.get("status") == "running"]

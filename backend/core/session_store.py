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

# Global lock guards ONLY the shared index.json. Per-session data (events.jsonl,
# meta.json) is guarded by per-session locks so concurrent sessions don't
# serialize their event writes through a single global lock — the main
# contention point when many users run at once.
_index_lock = threading.Lock()
_session_locks: dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()


def _session_lock(session_id: str) -> threading.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        with _session_locks_guard:
            lock = _session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                _session_locks[session_id] = lock
    return lock


# Back-compat alias (older call sites used the single global lock).
_lock = _index_lock


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
    workspace_id: str | None = None,
    chapter_id: str | None = None,
    parent_session_id: str = "",
    kind: str = "",
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
        "workspace_id": workspace_id or "",
        "chapter_id": chapter_id or "",
        # parent_session_id links an operating/continuation run back to its launch
        # session; kind is "launch" | "operating" | "" so the UI can nest them.
        "parent_session_id": parent_session_id or "",
        "kind": kind or "",
        "credits_used": 0,
    }
    with _session_lock(session_id):
        meta_path(session_id).write_text(json.dumps(meta, indent=2))
    with _index_lock:
        index = _load_index()
        index[session_id] = {k: meta[k] for k in ("session_id", "founder_id", "goal", "stack_id", "status", "created_at", "completed_at", "parent_session_id", "kind")}
        _save_index(index)


def update_session_status(session_id: str, status: str, artifact_count: int | None = None) -> None:
    with _session_lock(session_id):
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
    # Update the shared index under its own lock.
    with _index_lock:
        index = _load_index()
        if session_id in index:
            index[session_id]["status"] = status
            index[session_id]["completed_at"] = meta.get("completed_at")
            _save_index(index)


# ── Event persistence ──────────────────────────────────────────────────────────

def append_event(session_id: str, event_id: int, event: dict) -> None:
    """Append one event to the session's JSONL file. Thread-safe per session."""
    line = json.dumps({"id": event_id, "event": event}, separators=(",", ":")) + "\n"
    try:
        # Per-session lock: appends for different sessions run concurrently.
        with _session_lock(session_id):
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


def add_session_credits(session_id: str, credits: int) -> None:
    """Accumulate credits spent by this session (durable, in meta.json). Lets the UI
    show per-session — and, summed by goal, per-goal — credit spend."""
    if not credits:
        return
    try:
        with _session_lock(session_id):
            p = meta_path(session_id)
            meta = json.loads(p.read_text()) if p.exists() else {"session_id": session_id}
            meta["credits_used"] = int(meta.get("credits_used", 0)) + int(credits)
            p.write_text(json.dumps(meta, indent=2))
    except Exception as exc:
        logger.debug("add_session_credits failed for %s: %s", session_id, exc)


def get_session_credits(session_id: str) -> int:
    meta = get_session_meta(session_id) or {}
    try:
        return int(meta.get("credits_used", 0))
    except Exception:
        return 0


def _increment_artifacts(session_id: str) -> None:
    try:
        with _session_lock(session_id):
            p = meta_path(session_id)
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
        pending = ""
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                candidate = line if not pending else f"{pending}\\n{line}"
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    pending = candidate
                    continue
                pending = ""
                result.append((int(obj["id"]), obj["event"]))
        if pending:
            logger.warning("session_store.load_events ignored malformed trailing event for %s", session_id)
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


def has_active_run(founder_id: str, stale_seconds: int | None = None) -> bool:
    """True if the founder has a session genuinely RUNNING right now. A "running"
    session older than the stale window is ignored — otherwise a run that crashed
    without flipping its status (no restart to reconcile it) would block goal
    recovery forever. stale_seconds defaults to ASTRA_RUN_STALE_SECONDS (4h)."""
    if stale_seconds is None:
        stale_seconds = int(os.environ.get("ASTRA_RUN_STALE_SECONDS", "14400"))
    now = time.time()
    for s in list_sessions(founder_id, 30):
        if s.get("status") != "running":
            continue
        ts = s.get("created_at") or ""
        try:
            epoch = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except Exception:
            return True  # unknown age → assume active (safe: avoid duplicate dispatch)
        if (now - epoch) < stale_seconds:
            return True
    return False


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

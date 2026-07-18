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

import calendar
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

def _safe_session_id(session_id: str) -> str:
    return "".join(c for c in session_id if c.isalnum() or c in ("_", "-"))[:128] or "unknown"


def session_dir(session_id: str) -> Path:
    d = _vault() / "sessions" / _safe_session_id(session_id)
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
    p = _index_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True))
    tmp.replace(p)  # atomic on POSIX; best-effort on Windows


def _index_record_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        k: meta.get(k)
        for k in (
            "session_id",
            "founder_id",
            "company_id",
            "workspace_id",
            "goal",
            "stack_id",
            "status",
            "created_at",
            "completed_at",
            "parent_session_id",
            "kind",
        )
    }


def _reconcile_index_from_meta(session_id: str, meta: dict[str, Any] | None = None) -> None:
    meta = meta or get_session_meta(session_id)
    if not meta or not bool(meta.get("visible", True)):
        return
    record = _index_record_from_meta(meta)
    with _index_lock:
        index = _load_index()
        if index.get(session_id) != record:
            index[session_id] = record
            _save_index(index)


def _rebuild_index_sessions() -> dict[str, Any]:
    sessions_root = _vault() / "sessions"
    rebuilt: dict[str, Any] = {}
    if not sessions_root.exists():
        return rebuilt
    for candidate in sessions_root.iterdir():
        if not candidate.is_dir():
            continue
        meta = get_session_meta(candidate.name)
        if not meta or not bool(meta.get("visible", True)):
            continue
        rebuilt[candidate.name] = _index_record_from_meta(meta)
    return rebuilt


def _with_company_id(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized.setdefault(
        "company_id",
        str(normalized.get("workspace_id") or normalized.get("founder_id") or ""),
    )
    return normalized


# ── Session registration ───────────────────────────────────────────────────────

def register_session(
    session_id: str,
    founder_id: str,
    goal: str,
    stack_id: str = "",
    company_name: str = "",
    agents: list[str] | None = None,
    workspace_id: str | None = None,
    company_id: str | None = None,
    chapter_id: str | None = None,
    parent_session_id: str = "",
    kind: str = "",
    visible: bool = True,
) -> None:
    resolved_company_id = company_id or workspace_id or founder_id
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
        "company_id": resolved_company_id,
        "chapter_id": chapter_id or "",
        # parent_session_id links an operating/continuation run back to its launch
        # session; kind is "launch" | "operating" | "" so the UI can nest them.
        "parent_session_id": parent_session_id or "",
        "kind": kind or "",
        "credits_used": 0,
        "visible": bool(visible),
    }
    with _session_lock(session_id):
        meta_path(session_id).write_text(json.dumps(meta, indent=2))
    if visible:
        _reconcile_index_from_meta(session_id, meta)


def update_session_status(
    session_id: str, status: str, artifact_count: int | None = None, *, error: str | None = None,
) -> None:
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
        if error is not None:
            meta["error"] = error
        p.write_text(json.dumps(meta, indent=2))
    # Update the shared index under its own lock.
    with _index_lock:
        index = _load_index()
        current = index.get(session_id, {})
        current.update(_index_record_from_meta(meta))
        index[session_id] = current
        _save_index(index)


def merge_session_meta(session_id: str, **fields) -> None:
    """Merge arbitrary fields into a session's meta (e.g. needs_review, review_reason)."""
    if not fields:
        return
    with _session_lock(session_id):
        p = meta_path(session_id)
        try:
            meta = json.loads(p.read_text()) if p.exists() else {"session_id": session_id}
        except Exception:
            meta = {"session_id": session_id}
        meta.update(fields)
        p.write_text(json.dumps(meta, indent=2))


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
            _notify_run_done(session_id, success=True)
        elif etype == "goal_error":
            update_session_status(session_id, "error", error=str(event.get("error") or "") or None)
            _notify_run_done(session_id, success=False)
        elif etype == "stack_artifact":
            _increment_artifacts(session_id)
        _maybe_phase_1_dual_write_legacy_event(session_id, event_id, event)
    except Exception as exc:
        logger.warning("session_store.append_event failed for %s: %s", session_id, exc)


def _maybe_phase_1_dual_write_legacy_event(session_id: str, event_id: int, event: dict) -> None:
    """Mirror every legacy event for an opted-in internal cohort, never customers."""
    try:
        from backend.company_os import create_company_os, get_company_os
        from backend.company_os_integrity import record_phase_1_failure
        from backend.company_os_phase1 import dual_write_legacy_activity, is_internal_test_cohort

        meta = get_session_meta(session_id) or {}
        company_id = str(meta.get("company_id") or meta.get("founder_id") or "")
        if not company_id or not is_internal_test_cohort(company_id):
            return
        if get_company_os(company_id) is None:
            create_company_os(company_id, str(meta.get("founder_id") or ""), str(meta.get("company_name") or "Company"))
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        dual_write_legacy_activity(company_id, {
            "type": "artifact.created",
            "legacy_activity_id": f"legacy-event:{session_id}:{event_id}",
            "artifact_id": f"legacy-event-{session_id}-{event_id}",
            "name": f"Legacy event: {event.get('type', 'unknown')}",
            "content": payload,
            "legacy_session_id": session_id,
            "legacy_event_id": event_id,
            "legacy_event_type": event.get("type"),
        })
    except Exception as exc:
        logger.warning("Company OS Phase 1 event dual-write failed for session=%s: %s", session_id, exc)
        try:
            if 'company_id' in locals() and company_id:
                record_phase_1_failure(company_id, str(exc))
        except Exception:
            pass


def _notify_run_done(session_id: str, success: bool) -> None:
    try:
        meta = get_session_meta(session_id) or {}
        if not bool(meta.get("visible", True)) or str(meta.get("kind") or "") == "shadow":
            return
        founder_id = meta.get("founder_id", "")
        if not founder_id:
            return
        goal = (meta.get("goal", "Run") or "Run")[:60]
        title = "Run complete ✓" if success else "Run failed"
        from backend.notifications.push import notify_founder
        notify_founder(founder_id, title, goal)
    except Exception as exc:
        logger.debug("_notify_run_done failed: %s", exc)


def save_creative_brief(session_id: str, brief: dict) -> None:
    if not brief:
        return
    try:
        with _session_lock(session_id):
            p = meta_path(session_id)
            meta = json.loads(p.read_text()) if p.exists() else {"session_id": session_id}
            meta["creative_brief"] = brief
            p.write_text(json.dumps(meta, indent=2))
    except Exception as exc:
        logger.debug("save_creative_brief failed for %s: %s", session_id, exc)


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


def add_headroom_savings(session_id: str, tokens_saved: int, tokens_before: int) -> None:
    if not session_id or not tokens_saved:
        return
    try:
        with _session_lock(session_id):
            p = meta_path(session_id)
            meta = json.loads(p.read_text()) if p.exists() else {"session_id": session_id}
            meta["headroom_tokens_saved"] = meta.get("headroom_tokens_saved", 0) + tokens_saved
            meta["headroom_tokens_before"] = meta.get("headroom_tokens_before", 0) + tokens_before
            p.write_text(json.dumps(meta, indent=2))
    except Exception as exc:
        logger.debug("add_headroom_savings failed for %s: %s", session_id, exc)


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
                candidate = line if not pending else f"{pending}\n{line}"
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

def list_sessions(
    founder_id: str | None = None,
    limit: int = 100,
    company_id: str | None = None,
) -> list[dict]:
    """Return sessions from the index, newest first."""
    with _lock:
        rebuilt = _rebuild_index_sessions()
        with _index_lock:
            index = _load_index()
            if rebuilt and index != rebuilt:
                index = rebuilt
                _save_index(index)
            elif rebuilt:
                index = rebuilt
    sessions = [_with_company_id(session) for session in index.values()]
    if founder_id:
        sessions = [s for s in sessions if s.get("founder_id") == founder_id]
    if company_id:
        sessions = [s for s in sessions if s.get("company_id") == company_id]
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions[:limit]


def has_active_run(
    founder_id: str,
    stale_seconds: int | None = None,
    company_id: str | None = None,
) -> bool:
    """True if the founder has a session genuinely RUNNING right now. A "running"
    session older than the stale window is ignored — otherwise a run that crashed
    without flipping its status (no restart to reconcile it) would block goal
    recovery forever. stale_seconds defaults to ASTRA_RUN_STALE_SECONDS (4h)."""
    if stale_seconds is None:
        stale_seconds = int(os.environ.get("ASTRA_RUN_STALE_SECONDS", "14400"))
    now = time.time()
    for s in list_sessions(founder_id, 30, company_id):
        if s.get("status") != "running":
            continue
        ts = s.get("created_at") or ""
        try:
            epoch = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            return True  # unknown age → assume active (safe: avoid duplicate dispatch)
        if (now - epoch) < stale_seconds:
            return True
    return False


def reconcile_orphaned_sessions(stale_seconds: int | None = None) -> list[str]:
    """Startup sweep: a session left "running"/"queued" when the backend process
    died or restarted has no in-memory task to ever flip its status again --
    nothing currently revisits it (has_active_run() only ignores stale entries
    for its one caller, it doesn't fix them). Mark anything past the staleness
    window as "error" with an explanatory reason so it stops showing as
    perpetually in-flight. Returns the list of reconciled session IDs."""
    if stale_seconds is None:
        stale_seconds = int(os.environ.get("ASTRA_RUN_STALE_SECONDS", "14400"))
    now = time.time()
    reconciled: list[str] = []
    for s in list_sessions(limit=10_000):
        status = s.get("status")
        if status not in ("running", "queued"):
            continue
        session_id = s.get("session_id") or s.get("id")
        if not session_id:
            continue
        ts = s.get("created_at") or ""
        try:
            epoch = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            continue  # unknown age -- leave alone rather than guess
        if (now - epoch) < stale_seconds:
            continue
        update_session_status(
            session_id, "error",
            error=(
                f"Orphaned: session was still {status!r} after a backend restart "
                "with no active process found (reconciled by startup sweep)."
            ),
        )
        reconciled.append(session_id)
    return reconciled


def delete_session(session_id: str) -> bool:
    """Permanently remove a session's directory and index entry. Returns True if anything was removed."""
    import shutil
    removed = False
    # rmtree outside the index lock — can take seconds on large dirs and would
    # otherwise block every list_sessions / _load_index call globally.
    d = _vault() / "sessions" / session_id
    if d.exists():
        try:
            shutil.rmtree(d)
            removed = True
        except Exception as exc:
            logger.warning("session_store.delete_session rmtree failed for %s: %s", session_id, exc)
    with _index_lock:
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
        return _with_company_id(json.loads(p.read_text()))
    except Exception:
        return None


def scan_interrupted() -> list[str]:
    """Return session IDs that were running when the backend last died."""
    with _lock:
        index = _load_index()
    return [sid for sid, s in index.items() if s.get("status") == "running"]

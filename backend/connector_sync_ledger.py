"""Durable per-connector sync state.

This tracks source-level import/webhook outcomes and cursors independently from
the Company Brain graph. It gives Astra the operational substrate needed for
delta sync, retries, and connector-specific health reporting.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_ledger_locks: dict[str, threading.RLock] = {}
_ledger_locks_guard = threading.Lock()


def _ledger_lock(founder_id: str) -> threading.RLock:
    lock = _ledger_locks.get(founder_id)
    if lock is None:
        with _ledger_locks_guard:
            lock = _ledger_locks.get(founder_id)
            if lock is None:
                lock = threading.RLock()
                _ledger_locks[founder_id] = lock
    return lock


def _root() -> Path:
    root = Path(".astra/connector_sync")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(founder_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", founder_id)[:120] or "founder"
    return _root() / f"{safe}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load(founder_id: str) -> dict[str, Any]:
    path = _path(founder_id)
    if not path.exists():
        return {"founder_id": founder_id, "sources": {}, "updated_at": _now()}
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {"founder_id": founder_id, "sources": {}, "updated_at": _now()}
    data.setdefault("founder_id", founder_id)
    data.setdefault("sources", {})
    return data


def _save(founder_id: str, data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = _now()
    path = _path(founder_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("connector_sync", founder_id, data)
    except Exception:
        pass
    return data


def record_connector_sync(
    founder_id: str,
    source: str,
    *,
    status: str,
    imported: int = 0,
    changed_records: int = 0,
    cursor: str | None = None,
    error: str = "",
    mode: str = "import",
) -> dict[str, Any]:
    with _ledger_lock(founder_id):
        data = _load(founder_id)
        sources = data.setdefault("sources", {})
        current = sources.get(source) or {
            "source": source,
            "status": "idle",
            "cursor": "",
            "last_success_at": None,
            "last_error_at": None,
            "last_error": "",
            "total_imported": 0,
            "total_changed_records": 0,
            "webhook_events": 0,
            "history": [],
        }
        now = _now()
        current["status"] = status
        current["last_run_at"] = now
        current["mode"] = mode
        current["last_imported"] = int(imported or 0)
        current["last_changed_records"] = int(changed_records or 0)
        current["total_imported"] = int(current.get("total_imported") or 0) + max(0, int(imported or 0))
        current["total_changed_records"] = int(current.get("total_changed_records") or 0) + max(0, int(changed_records or 0))
        if cursor is not None:
            current["cursor"] = cursor
        if status == "ok":
            current["last_success_at"] = now
            current["last_error"] = ""
        elif status == "error":
            current["last_error_at"] = now
            current["last_error"] = error
        if mode == "webhook":
            current["webhook_events"] = int(current.get("webhook_events") or 0) + 1
        history = list(current.get("history") or [])
        history.insert(0, {
            "at": now,
            "status": status,
            "mode": mode,
            "imported": imported,
            "changed_records": changed_records,
            "cursor": cursor if cursor is not None else current.get("cursor", ""),
            "error": error,
        })
        current["history"] = history[:50]
        sources[source] = current
        _save(founder_id, data)
        return current


def record_connector_webhook(
    founder_id: str,
    source: str,
    *,
    event_id: str = "",
    event_type: str = "",
    changed_records: int = 0,
    cursor: str | None = None,
) -> dict[str, Any]:
    return record_connector_sync(
        founder_id,
        source,
        status="ok",
        imported=1,
        changed_records=changed_records,
        cursor=cursor or event_id or None,
        mode="webhook",
    )


def get_connector_sync_status(founder_id: str) -> dict[str, Any]:
    return _load(founder_id)


def get_connector_cursor(founder_id: str, source: str) -> str:
    source_state = (_load(founder_id).get("sources") or {}).get(source) or {}
    return str(source_state.get("cursor") or "")


def connector_sync_metrics() -> dict[str, Any]:
    ledgers = []
    for path in sorted(_root().glob("*.json")):
        try:
            ledgers.append(json.loads(path.read_text()))
        except Exception:
            continue
    sources = [source for ledger in ledgers for source in (ledger.get("sources") or {}).values()]
    return {
        "connector_ledgers": len(ledgers),
        "connector_sources": len(sources),
        "connector_sources_error": sum(1 for source in sources if source.get("status") == "error"),
        "connector_webhook_events": sum(int(source.get("webhook_events") or 0) for source in sources),
    }

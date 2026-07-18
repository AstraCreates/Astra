"""Phase 2 legacy execution drain for the Company OS hard replacement."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.json_store import json_file_lock

_NONTERMINAL = {"queued", "running", "stalled", "cancelling", "paused", "pending"}


async def inventory_legacy_work() -> dict[str, Any]:
    """Inspect every local legacy session and its Temporal workflow when applicable."""
    from backend.core.session_store import list_sessions

    sessions = await asyncio.to_thread(list_sessions, None, 100_000, None)
    active = []
    for session in sessions:
        if str(session.get("status", "")).lower() not in _NONTERMINAL:
            continue
        item = {"session_id": session.get("session_id") or session.get("id"), "company_id": session.get("company_id"),
                "founder_id": session.get("founder_id"), "engine": session.get("engine", "legacy"), "status": session.get("status")}
        if item["engine"] == "temporal" and item["session_id"]:
            try:
                from backend.control_plane.temporal.dispatch import get_workflow_status
                item["temporal"] = await get_workflow_status(str(item["session_id"]))
            except Exception as exc:
                item["temporal_error"] = str(exc)
        active.append(item)
    return {"checked_at": _now(), "active": active, "active_count": len(active), "clear": not active}


async def force_drain_legacy_work(*, operator_id: str, confirmation: str) -> dict[str, Any]:
    """Explicitly terminate all nonterminal legacy work and persist a receipt."""
    if confirmation != "TERMINATE LEGACY WORK":
        raise ValueError("confirmation must equal TERMINATE LEGACY WORK")
    before = await inventory_legacy_work()
    terminated = []
    from backend.core import cancellation
    from backend.core.session_store import update_session_status
    for item in before["active"]:
        session_id = str(item["session_id"])
        temporal_cancelled = False
        if item.get("engine") == "temporal":
            try:
                from backend.control_plane.temporal.dispatch import cancel_run
                temporal_cancelled = bool(await cancel_run(session_id))
            except Exception as exc:
                item["temporal_cancel_error"] = str(exc)
        local_cancelled = cancellation.request_kill(session_id)
        await asyncio.to_thread(update_session_status, session_id, "killed", error="Phase 2 forced termination: Company OS hard replacement.")
        terminated.append({**item, "temporal_cancelled": temporal_cancelled, "local_cancelled": local_cancelled, "terminal_status": "killed"})
    after = await inventory_legacy_work()
    receipt = {"kind": "phase_2_legacy_drain", "at": _now(), "operator_id": operator_id, "before": before,
               "terminated": terminated, "after": after, "passed": after["clear"]}
    _append_receipt(receipt)
    return receipt


def read_phase_2_receipts() -> list[dict[str, Any]]:
    path = _receipt_path()
    if not path.exists():
        return []
    with json_file_lock(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_receipt(receipt: dict[str, Any]) -> None:
    path = _receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with json_file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True) + "\n")
            handle.flush()


def _receipt_path() -> Path:
    return Path(os.environ.get("ASTRA_WORKSPACE", Path.cwd() / "workspace")) / "company" / "phase-2-legacy-drain.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

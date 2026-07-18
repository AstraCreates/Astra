"""Continuous Phase 1 integrity checks for explicitly enrolled internal companies."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_stop: asyncio.Event | None = None
_status: dict[str, Any] = {"running": False, "interval_seconds": 3600, "last_tick_at": None, "last_result": [], "last_error": ""}


def run_phase_1_integrity_tick() -> list[dict[str, Any]]:
    """Rebuild derived projections and append a recovery drill for every cohort company."""
    from backend.company_os_integrity import run_recovery_drill
    from backend.company_os_phase1 import list_internal_test_cohort
    from backend.company_os_projection import rebuild_company_projections

    results = []
    for entry in list_internal_test_cohort():
        company_id = str(entry["company_id"])
        try:
            projection = rebuild_company_projections(company_id)
            recovery = run_recovery_drill(company_id)
            results.append({"company_id": company_id, "ok": bool(recovery.get("passed")), "projection": projection, "recovery": recovery})
        except Exception as exc:
            logger.warning("Company OS Phase 1 integrity tick failed for %s: %s", company_id, exc)
            results.append({"company_id": company_id, "ok": False, "error": str(exc)})
    return results


async def _loop(interval_seconds: int) -> None:
    while _stop and not _stop.is_set():
        try:
            result = await asyncio.to_thread(run_phase_1_integrity_tick)
            _status.update({"last_tick_at": datetime.now(timezone.utc).isoformat(), "last_result": result, "last_error": ""})
        except Exception as exc:
            logger.warning("Company OS Phase 1 scheduler tick failed: %s", exc)
            _status["last_error"] = str(exc)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def start_company_os_phase_1_scheduler(interval_seconds: int = 3600) -> dict[str, Any]:
    """Start the singleton local Phase 1 evidence scheduler; empty cohorts are a no-op."""
    global _task, _stop
    if _task and not _task.done():
        return get_company_os_phase_1_scheduler_status()
    _stop = asyncio.Event()
    interval = max(60, int(interval_seconds))
    _status.update({"running": True, "interval_seconds": interval, "last_error": ""})
    _task = asyncio.create_task(_loop(interval))
    return get_company_os_phase_1_scheduler_status()


async def stop_company_os_phase_1_scheduler() -> dict[str, Any]:
    if _stop:
        _stop.set()
    if _task:
        await asyncio.wait_for(_task, timeout=5)
    _status["running"] = False
    return get_company_os_phase_1_scheduler_status()


def get_company_os_phase_1_scheduler_status() -> dict[str, Any]:
    return {"ok": True, "scheduler": {**_status, "running": bool(_task and not _task.done())}}

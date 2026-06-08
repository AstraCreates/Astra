"""Background scheduler for company-brain continuous sync."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.tools.company_brain import run_due_company_brain_syncs

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_status: dict[str, Any] = {
    "running": False,
    "interval_seconds": 60,
    "last_tick_at": None,
    "last_result": None,
    "last_error": "",
}


async def _loop(interval_seconds: int) -> None:
    global _status
    while _stop_event and not _stop_event.is_set():
        try:
            from backend.tools.company_brain import _now
            result = await asyncio.to_thread(run_due_company_brain_syncs)
            _status.update({
                "running": True,
                "interval_seconds": interval_seconds,
                "last_tick_at": _now(),
                "last_result": result,
                "last_error": "",
            })
        except Exception as exc:
            logger.warning("Company brain scheduler tick failed: %s", exc)
            _status.update({"last_error": str(exc)})
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue


def start_company_brain_scheduler(interval_seconds: int = 60) -> dict[str, Any]:
    """Start the singleton background scheduler if it is not already running."""
    global _task, _stop_event, _status
    if _task and not _task.done():
        return get_company_brain_scheduler_status()
    _stop_event = asyncio.Event()
    _status.update({
        "running": True,
        "interval_seconds": max(10, int(interval_seconds or 60)),
        "last_error": "",
    })
    _task = asyncio.create_task(_loop(_status["interval_seconds"]))
    return get_company_brain_scheduler_status()


async def stop_company_brain_scheduler() -> dict[str, Any]:
    """Stop the singleton background scheduler."""
    global _task, _stop_event, _status
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (Exception, asyncio.CancelledError):
            _task.cancel()
    _status["running"] = False
    return get_company_brain_scheduler_status()


def get_company_brain_scheduler_status() -> dict[str, Any]:
    alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

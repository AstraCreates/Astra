"""Background scheduler for company-brain continuous sync."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
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
    "mode": "legacy",
    "schedule_id": "",
}
_TEMPORAL_SCHEDULE_ID = "astra-company-brain-sync"


def _temporal_scheduler_enabled() -> bool:
    return os.getenv("ASTRA_TEMPORAL_COMPANY_BRAIN_SCHEDULE", "1") != "0"


async def _ensure_temporal_schedule(interval_seconds: int) -> dict[str, Any]:
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleSpec,
    )

    from backend.control_plane.temporal.contracts import TASK_QUEUE
    from backend.control_plane.temporal.dispatch import _get_client

    client = await _get_client()
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "AstraCompanyBrainTick",
            id="astra-company-brain-tick",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(seconds=max(10, int(interval_seconds or 60))))],
        ),
    )
    try:
        await client.create_schedule(_TEMPORAL_SCHEDULE_ID, schedule)
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise
    _status.update({
        "running": True,
        "interval_seconds": max(10, int(interval_seconds or 60)),
        "last_error": "",
        "mode": "temporal",
        "schedule_id": _TEMPORAL_SCHEDULE_ID,
    })
    return get_company_brain_scheduler_status()


async def _delete_temporal_schedule() -> None:
    from backend.control_plane.temporal.dispatch import _get_client

    client = await _get_client()
    handle = client.get_schedule_handle(_TEMPORAL_SCHEDULE_ID)
    await handle.delete()


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
    interval = max(10, int(interval_seconds or 60))
    if _temporal_scheduler_enabled():
        try:
            asyncio.create_task(_ensure_temporal_schedule(interval))
            _status.update({
                "running": True,
                "interval_seconds": interval,
                "last_error": "",
                "mode": "temporal",
                "schedule_id": _TEMPORAL_SCHEDULE_ID,
            })
            return get_company_brain_scheduler_status()
        except Exception as exc:
            logger.warning("company_brain_scheduler: temporal schedule bootstrap failed, falling back to legacy: %s", exc)
            _status["last_error"] = str(exc)
    if _task and not _task.done():
        return get_company_brain_scheduler_status()
    _stop_event = asyncio.Event()
    _status.update({
        "running": True,
        "interval_seconds": interval,
        "last_error": "",
        "mode": "legacy",
        "schedule_id": "",
    })
    _task = asyncio.create_task(_loop(_status["interval_seconds"]))
    return get_company_brain_scheduler_status()


async def stop_company_brain_scheduler() -> dict[str, Any]:
    """Stop the singleton background scheduler."""
    global _task, _stop_event, _status
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        try:
            await _delete_temporal_schedule()
        except Exception as exc:
            logger.warning("company_brain_scheduler: temporal schedule delete failed: %s", exc)
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (Exception, asyncio.CancelledError):
            _task.cancel()
    _status.update({"running": False, "schedule_id": ""})
    return get_company_brain_scheduler_status()


def get_company_brain_scheduler_status() -> dict[str, Any]:
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        alive = bool(_status.get("running"))
    else:
        alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

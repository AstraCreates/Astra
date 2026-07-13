"""Background scheduler for recurring custom agents.

Each tick:
  1. Loads every custom agent (across founders) with an enabled schedule.
  2. Runs those whose next_run_at is in the past.
  3. Stamps last_run_at + rolls next_run_at forward.
  4. Never crashes the loop.

Public API:
    start_custom_agents_scheduler(interval_seconds=900)
    stop_custom_agents_scheduler()
    get_custom_agents_scheduler_status() -> dict
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_status: dict[str, Any] = {
    "running": False,
    "interval_seconds": 900,
    "last_tick_at": None,
    "last_runs_launched": 0,
    "last_error": "",
    "mode": "legacy",
    "schedule_id": "",
}
_TEMPORAL_SCHEDULE_ID = "astra-custom-agents-recurring"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _temporal_scheduler_enabled() -> bool:
    return os.getenv("ASTRA_TEMPORAL_CUSTOM_AGENTS_SCHEDULE", "1") != "0"


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
            "AstraCustomAgentsTick",
            id="astra-custom-agents-tick",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(seconds=max(60, int(interval_seconds or 900))))],
        ),
    )
    try:
        await client.create_schedule(_TEMPORAL_SCHEDULE_ID, schedule)
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise
    _status.update({
        "running": True,
        "interval_seconds": max(60, int(interval_seconds or 900)),
        "last_error": "",
        "mode": "temporal",
        "schedule_id": _TEMPORAL_SCHEDULE_ID,
    })
    return get_custom_agents_scheduler_status()


async def _delete_temporal_schedule() -> None:
    from backend.control_plane.temporal.dispatch import _get_client

    client = await _get_client()
    handle = client.get_schedule_handle(_TEMPORAL_SCHEDULE_ID)
    await handle.delete()


async def _tick() -> int:
    """Run all due scheduled custom agents. Returns count launched."""
    from backend.custom_agents import store
    from backend.custom_agents.runner import launch_custom_agent_run
    from backend.core.session_store import has_active_run

    try:
        scheduled = await asyncio.to_thread(store.all_scheduled_agents)
    except Exception as exc:
        logger.warning("custom_agents_scheduler: load failed: %s", exc)
        return 0

    launched = 0
    for spec in scheduled:
        if not store.is_due(spec):
            continue
        founder_id = spec.get("founder_id", "")
        company_id = spec.get("company_id") or founder_id
        if not founder_id:
            continue
        # Don't stack a new run if one for this company is already in flight.
        try:
            if await asyncio.to_thread(has_active_run, founder_id, company_id=company_id):
                continue
        except Exception:
            pass
        try:
            await launch_custom_agent_run(founder_id=founder_id, spec=spec, company_id=company_id, kind="scheduled")
            await asyncio.to_thread(store.mark_ran, founder_id, spec["id"])
            launched += 1
            logger.info("custom_agents_scheduler: launched %s (founder=%s)", spec["id"], founder_id)
        except Exception as exc:
            logger.error("custom_agents_scheduler: launch failed for %s: %s", spec.get("id"), exc, exc_info=True)

    return launched


async def _loop(interval_seconds: int) -> None:
    global _status
    while _stop_event and not _stop_event.is_set():
        tick_start = time.monotonic()
        launched = 0
        error_msg = ""
        try:
            launched = await _tick()
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("custom_agents_scheduler: tick raised: %s", exc)
        _status.update({
            "running": True,
            "interval_seconds": interval_seconds,
            "last_tick_at": _now_iso(),
            "last_runs_launched": launched,
            "last_error": error_msg,
        })
        elapsed = time.monotonic() - tick_start
        wait = max(0.0, interval_seconds - elapsed)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            continue


def start_custom_agents_scheduler(interval_seconds: int = 900) -> dict[str, Any]:
    """Start the singleton custom-agents scheduler. Safe to call repeatedly."""
    global _task, _stop_event, _status
    interval = max(60, int(interval_seconds or 900))
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
            return get_custom_agents_scheduler_status()
        except Exception as exc:
            logger.warning("custom_agents_scheduler: temporal schedule bootstrap failed, falling back to legacy: %s", exc)
            _status["last_error"] = str(exc)
    if _task and not _task.done():
        return get_custom_agents_scheduler_status()
    _stop_event = asyncio.Event()
    _status.update({"running": True, "interval_seconds": interval, "last_error": "", "mode": "legacy", "schedule_id": ""})
    _task = asyncio.create_task(_loop(interval))
    logger.info("custom_agents_scheduler: started (interval=%ds)", interval)
    return get_custom_agents_scheduler_status()


async def stop_custom_agents_scheduler() -> dict[str, Any]:
    global _task, _stop_event, _status
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        try:
            await _delete_temporal_schedule()
        except Exception as exc:
            logger.warning("custom_agents_scheduler: temporal schedule delete failed: %s", exc)
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except Exception:
            _task.cancel()
    _status.update({"running": False, "schedule_id": ""})
    return get_custom_agents_scheduler_status()


def get_custom_agents_scheduler_status() -> dict[str, Any]:
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        alive = bool(_status.get("running"))
    else:
        alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

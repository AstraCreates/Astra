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
import time
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
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    if _task and not _task.done():
        return get_custom_agents_scheduler_status()
    interval = max(60, int(interval_seconds or 900))
    _stop_event = asyncio.Event()
    _status.update({"running": True, "interval_seconds": interval, "last_error": ""})
    _task = asyncio.create_task(_loop(interval))
    logger.info("custom_agents_scheduler: started (interval=%ds)", interval)
    return get_custom_agents_scheduler_status()


async def stop_custom_agents_scheduler() -> dict[str, Any]:
    global _task, _stop_event, _status
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except Exception:
            _task.cancel()
    _status["running"] = False
    return get_custom_agents_scheduler_status()


def get_custom_agents_scheduler_status() -> dict[str, Any]:
    alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

"""Background scheduler for autonomous mission execution.

Runs active missions on a periodic interval. Each tick:
  1. Loads all missions due for execution from the store.
  2. Checks per-mission budget (max_runs_per_day) against today's run_count.
  3. Skips missions with approval_policy == "require_approval" (manual trigger only).
  4. Dispatches run_mission() for each eligible mission.
  5. Logs progress and errors — never crashes the event loop.

Public API
----------
    start_missions_scheduler(interval_seconds=3600)
    stop_missions_scheduler()
    get_missions_scheduler_status() -> dict
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
    "interval_seconds": 3600,
    "last_tick_at": None,
    "last_missions_run": 0,
    "last_error": "",
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_utc() -> str:
    """Return today's date (UTC) as YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.gmtime())


def _runs_today(mission: dict) -> int:
    """Count how many progress notes were appended today (UTC).

    Each completed run appends exactly one progress note, so the count of
    today's notes is a reliable proxy for today's run count.
    """
    today = _today_utc()
    notes: list[dict] = mission.get("progress_notes") or []
    return sum(1 for n in notes if (n.get("timestamp") or "").startswith(today))


def _budget_allows(mission: dict) -> bool:
    """Return True if the mission has not exceeded its daily run budget."""
    budget: dict = mission.get("budget") or {}
    max_runs: int = int(budget.get("max_runs_per_day") or 1)
    return _runs_today(mission) < max_runs


async def _scheduler_tick() -> int:
    """Run all missions that are due and within budget.

    Returns:
        Number of missions dispatched in this tick.
    """
    from backend.missions.store import get_missions_due_for_run
    from backend.missions.runner import run_mission

    try:
        due_missions: list[dict] = await asyncio.to_thread(get_missions_due_for_run)
    except Exception as exc:
        logger.warning("missions_scheduler: failed to load due missions: %s", exc)
        return 0

    if not due_missions:
        logger.debug("missions_scheduler: no missions due for execution")
        return 0

    dispatched = 0
    for mission in due_missions:
        mission_id: str = mission.get("id", "<unknown>")
        mission_name: str = mission.get("name", mission_id)
        approval_policy: str = mission.get("approval_policy", "auto")

        # Respect approval policy — require_approval missions must be triggered manually
        if approval_policy == "require_approval":
            logger.debug(
                "missions_scheduler: skipping mission=%s (require_approval)", mission_id
            )
            continue

        # Respect daily budget
        if not _budget_allows(mission):
            logger.info(
                "missions_scheduler: skipping mission=%s name=%r — daily budget exhausted",
                mission_id, mission_name,
            )
            continue

        logger.info(
            "missions_scheduler: dispatching mission=%s name=%r department=%s",
            mission_id, mission_name, mission.get("department"),
        )

        try:
            result = await run_mission(mission_id)
            success = result.get("success", False)
            summary = (result.get("summary") or "")[:200]
            cost = result.get("cost_usd", 0.0)
            logger.info(
                "missions_scheduler: mission=%s success=%s cost_usd=%.4f summary=%r",
                mission_id, success, cost, summary,
            )
            dispatched += 1
        except Exception as exc:
            # Never let a single bad mission crash the scheduler
            logger.error(
                "missions_scheduler: unhandled error running mission=%s: %s",
                mission_id, exc, exc_info=True,
            )

    return dispatched


async def _loop(interval_seconds: int) -> None:
    """Main scheduler loop — runs ticks and waits between them."""
    global _status
    while _stop_event and not _stop_event.is_set():
        tick_start = time.monotonic()
        missions_run = 0
        error_msg = ""

        try:
            missions_run = await _scheduler_tick()
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("missions_scheduler: tick raised unexpectedly: %s", exc)

        _status.update({
            "running": True,
            "interval_seconds": interval_seconds,
            "last_tick_at": _now_iso(),
            "last_missions_run": missions_run,
            "last_error": error_msg,
        })

        elapsed = time.monotonic() - tick_start
        wait = max(0.0, interval_seconds - elapsed)
        logger.debug(
            "missions_scheduler: tick done in %.1fs, next run in %.0fs", elapsed, wait
        )

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            continue


def start_missions_scheduler(interval_seconds: int = 3600) -> dict[str, Any]:
    """Start the singleton missions background scheduler.

    Safe to call multiple times — returns immediately if already running.

    Args:
        interval_seconds: How often to check for due missions. Defaults to 3600 (1 hour).

    Returns:
        Current scheduler status dict.
    """
    global _task, _stop_event, _status
    if _task and not _task.done():
        logger.debug("missions_scheduler: already running, ignoring start request")
        return get_missions_scheduler_status()

    interval = max(60, int(interval_seconds or 3600))
    _stop_event = asyncio.Event()
    _status.update({
        "running": True,
        "interval_seconds": interval,
        "last_error": "",
    })
    _task = asyncio.create_task(_loop(interval))
    logger.info("missions_scheduler: started (interval=%ds)", interval)
    return get_missions_scheduler_status()


async def stop_missions_scheduler() -> dict[str, Any]:
    """Stop the singleton missions background scheduler gracefully.

    Returns:
        Current scheduler status dict.
    """
    global _task, _stop_event, _status
    logger.info("missions_scheduler: stopping")
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except Exception:
            _task.cancel()
    _status["running"] = False
    return get_missions_scheduler_status()


def get_missions_scheduler_status() -> dict[str, Any]:
    """Return the current scheduler status.

    Returns:
        Dict with ``ok`` and ``scheduler`` keys.
    """
    alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

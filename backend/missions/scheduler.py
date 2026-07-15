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
import os
import time
from datetime import timedelta
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
    "mode": "legacy",
    "schedule_id": "",
}
_TEMPORAL_SCHEDULE_ID = "astra-missions-safety-net"


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


def _temporal_scheduler_enabled() -> bool:
    return os.getenv("ASTRA_TEMPORAL_MISSIONS_SCHEDULE", "1") != "0"


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
            "AstraMissionSchedulerTick",
            id="astra-missions-scheduler-tick",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(seconds=max(60, int(interval_seconds or 3600))))],
        ),
    )
    try:
        await client.create_schedule(_TEMPORAL_SCHEDULE_ID, schedule)
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise
    _status.update({
        "running": True,
        "interval_seconds": max(60, int(interval_seconds or 3600)),
        "last_error": "",
        "mode": "temporal",
        "schedule_id": _TEMPORAL_SCHEDULE_ID,
    })
    return get_missions_scheduler_status()


async def _delete_temporal_schedule() -> None:
    from backend.control_plane.temporal.dispatch import _get_client

    client = await _get_client()
    handle = client.get_schedule_handle(_TEMPORAL_SCHEDULE_ID)
    await handle.delete()


async def _scheduler_tick() -> int:
    """Safety-net only. The goal loop is EVENT-DRIVEN: agent_done events tick tasks.
    When a goal completes, the planner PROPOSES the next goal and waits for the founder
    to approve it (no auto-chain). This tick recovers one failure mode only:
      1. A completed goal with NO proposed successor (after_run missed — crash/restart/
         planner error) → re-PROPOSE the next goal (never dispatched without sign-off).
    It never decides goal-done on a timer, never re-dispatches stalled active goals, and
    never starts a proposed goal.

    Returns the number of missing next-goal proposals recovered.
    """
    from backend.missions.company_goal import (
        list_company_goals, current_goal, chain_allowed, _goal_is_complete,
    )
    from backend.missions.goal_engine import plan_next_goal

    try:
        goals: list[dict] = await asyncio.to_thread(list_company_goals)
    except Exception as exc:
        logger.warning("missions_scheduler: failed to load company goals: %s", exc)
        return 0

    from backend.core.session_store import has_active_run
    from backend.missions.company_goal import reconcile_operating_sessions

    dispatched = 0
    for goal in goals:
        founder_id = goal.get("founder_id", "")
        company_id = goal.get("company_id") or founder_id
        if not founder_id or goal.get("status") in ("paused", "completed"):
            continue
        # Heal op-run records stuck at "running" from a restart-killed dispatch.
        await asyncio.to_thread(reconcile_operating_sessions, founder_id, company_id)
        if await asyncio.to_thread(
            has_active_run,
            founder_id,
            company_id=company_id,
        ):
            continue  # a run is genuinely in progress — don't start a duplicate
        cg = await asyncio.to_thread(current_goal, founder_id, company_id)
        # SAFETY NET — current goal complete but NO successor proposed. This happens when
        # after_run missed (run crashed, backend restarted between goal_done and the
        # proposal, or the planner errored), which is exactly the "goal done but no next
        # goal" stall. Re-propose now. Approval-gated: this only PROPOSES (status
        # "proposed"); it never dispatches without the founder's sign-off. After a
        # proposal exists the current goal is the proposal (not "done"), so this won't
        # fire again or stack duplicates.
        if cg and cg.get("status") == "done" and _goal_is_complete(cg):
            if chain_allowed(goal):
                try:
                    if await asyncio.to_thread(plan_next_goal, founder_id, company_id):
                        dispatched += 1
                        logger.info("missions_scheduler: recovered missing next-goal proposal founder=%s", founder_id)
                except Exception as exc:
                    logger.error("missions_scheduler: next-goal proposal recovery failed founder=%s: %s", founder_id, exc, exc_info=True)
            continue
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


async def start_missions_scheduler(interval_seconds: int = 3600) -> dict[str, Any]:
    """Start the singleton missions background scheduler.

    Safe to call multiple times — returns immediately if already running.

    Args:
        interval_seconds: How often to check for due missions. Defaults to 3600 (1 hour).

    Returns:
        Current scheduler status dict.
    """
    global _task, _stop_event, _status
    interval = max(60, int(interval_seconds or 3600))
    temporal_error = ""
    if _temporal_scheduler_enabled():
        try:
            # Await so a failure INSIDE _ensure_temporal_schedule (e.g. Temporal briefly
            # unreachable) is actually caught here instead of becoming an unhandled task
            # exception, which used to leave the status falsely claiming "running: true /
            # mode: temporal" while nothing was actually scheduled. _ensure_temporal_schedule
            # only flips _status to running/temporal after the schedule is confirmed created.
            await _ensure_temporal_schedule(interval)
            return get_missions_scheduler_status()
        except Exception as exc:
            logger.warning("missions_scheduler: temporal schedule bootstrap failed, falling back to legacy: %s", exc)
            temporal_error = str(exc)
            _status.update({
                "running": False,
                "interval_seconds": interval,
                "last_error": temporal_error,
                "mode": "legacy",
                "schedule_id": "",
            })
    if _task and not _task.done():
        logger.debug("missions_scheduler: already running, ignoring start request")
        return get_missions_scheduler_status()
    _stop_event = asyncio.Event()
    _status.update({
        "running": True,
        "interval_seconds": interval,
        # Preserve the temporal bootstrap failure (if any) so the status endpoint still
        # explains why we're on the legacy loop instead of silently discarding it.
        "last_error": temporal_error,
        "mode": "legacy",
        "schedule_id": "",
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
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        try:
            await _delete_temporal_schedule()
        except Exception as exc:
            logger.warning("missions_scheduler: temporal schedule delete failed: %s", exc)
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except Exception:
            _task.cancel()
    _status.update({"running": False, "schedule_id": ""})
    return get_missions_scheduler_status()


def get_missions_scheduler_status() -> dict[str, Any]:
    """Return the current scheduler status.

    Returns:
        Dict with ``ok`` and ``scheduler`` keys.
    """
    if _status.get("mode") == "temporal" and _status.get("schedule_id"):
        alive = bool(_status.get("running"))
    else:
        alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

"""Background scheduler that keeps every company's shipped work alive.

Each tick (hourly):
  1. For every company, load the artifacts it has shipped (from durable receipts).
  2. Re-verify deploy/live URLs every tick; re-check content freshness weekly.
  3. Record each result to the monitoring ledger.
  4. AUTO-HEAL: when an artifact is down/stale, re-run ONLY the responsible agent via
     orchestrator.continue_run (which itself flows through the verification ladder), then
     notify the founder of the fix. Capped per company per day; skipped if a run is
     already active for that company.

Public API mirrors the other Astra schedulers:
    start_monitoring_scheduler(interval_seconds=3600)
    stop_monitoring_scheduler()
    get_monitoring_scheduler_status() -> dict
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_status: dict[str, Any] = {
    "running": False,
    "interval_seconds": 3600,
    "last_tick_at": None,
    "last_checks": 0,
    "last_heals": 0,
    "last_error": "",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _autoheal_cap() -> int:
    try:
        return int(os.getenv("ASTRA_AUTOHEAL_MAX_PER_DAY", "5"))
    except ValueError:
        return 5


def _autoheal_enabled() -> bool:
    return os.getenv("ASTRA_AUTOHEAL", "1") != "0"


def _claim_autoheal_lease(founder_id: str, company_id: str, artifact_key: str) -> tuple[str, str] | None:
    """Atomically claim one repair across all backend replicas."""
    try:
        from backend.core.events import _redis
        client = _redis()
        if not client:
            return None
        key = f"monitoring:autoheal:{founder_id}:{company_id}:{artifact_key}"
        token = uuid.uuid4().hex
        ttl = max(60, int(os.getenv("ASTRA_AUTOHEAL_LEASE_SECONDS", "3600")))
        return (key, token) if client.set(key, token, nx=True, ex=ttl) else None
    except Exception as exc:
        logger.warning("monitoring: auto-heal lease unavailable: %s", exc)
        return None


def _release_autoheal_lease(lease: tuple[str, str]) -> None:
    try:
        from backend.core.events import _redis
        client = _redis()
        if client and client.get(lease[0]) == lease[1]:
            client.delete(lease[0])
    except Exception:
        logger.warning("monitoring: failed to release auto-heal lease")


async def _auto_heal(founder_id: str, company_id: str, record: dict, check: dict) -> bool:
    """Re-run the single responsible agent to repair a down/stale artifact."""
    from backend.core.session_store import has_active_run
    from backend.monitoring.store import add_monitoring_check, heals_today
    from backend.notifications.push import notify_founder

    agent = record.get("agent") or ""
    prior_session = record.get("session_id") or ""
    artifact_key = record.get("artifact_key") or ""
    if not agent or not prior_session:
        return False

    lease = await asyncio.to_thread(_claim_autoheal_lease, founder_id, company_id, artifact_key)
    if not lease:
        return False

    if await asyncio.to_thread(has_active_run, founder_id, company_id=company_id):
        await asyncio.to_thread(_release_autoheal_lease, lease)
        return False
    if await asyncio.to_thread(heals_today, founder_id, company_id) >= _autoheal_cap():
        await asyncio.to_thread(_release_autoheal_lease, lease)
        logger.info("monitoring: auto-heal cap reached for company=%s", company_id)
        return False

    title = record.get("artifact_title") or artifact_key
    problem = check["metadata"].get("error") or (
        f"HTTP {check['metadata'].get('http_status')}" if check["kind"] == "url"
        else f"{check['metadata'].get('age_days')}d old")
    instruction = (
        f"MONITORING AUTO-HEAL: the deliverable '{title}' is {check['status']} ({problem}). "
        f"Regenerate and re-ship it so it is live and current again. Produce the corrected output."
    )

    # Record the attempt BEFORE launching so the per-day cap counts it.
    await asyncio.to_thread(
        add_monitoring_check, founder_id, company_id,
        session_id=prior_session, artifact_key=artifact_key,
        artifact_type=check["kind"], check_type="auto_heal", status="attempted",
        metadata={"agent": agent, "before": check["status"], "reason": problem},
    )

    async def _run_heal() -> None:
        try:
            from backend.control_plane.start_run import start_continue_run
            from backend.core.session_ids import new_session_id

            await start_continue_run(
                instruction=instruction,
                founder_id=founder_id,
                prior_session_id=prior_session,
                agents=[agent],
                run_id=new_session_id(),
                company_id=company_id,
                kind="scheduled",
                validate_prior=False,
                schedule_task=False,
            )
            await asyncio.to_thread(
                notify_founder, founder_id,
                "Astra fixed your company",
                f"'{title}' was {check['status']} ({problem}) — {agent} agent re-ran and re-shipped it.",
                "/",
            )
        except Exception as exc:
            logger.warning("monitoring: auto-heal run failed for %s: %s", artifact_key, exc)
        finally:
            await asyncio.to_thread(_release_autoheal_lease, lease)

    asyncio.create_task(_run_heal())
    return True


async def _tick() -> tuple[int, int]:
    """Run health checks for all companies. Returns (checks_recorded, heals_launched)."""
    from backend.tools.company_brain import list_company_brain_instances
    from backend.monitoring.checks import artifacts_for_company, check_artifact
    from backend.monitoring.store import add_monitoring_check, last_content_check

    try:
        companies = await asyncio.to_thread(list_company_brain_instances)
    except Exception as exc:
        logger.warning("monitoring: company list failed: %s", exc)
        return 0, 0

    checks = 0
    heals = 0
    for founder_id, company_id in companies:
        try:
            records = await asyncio.to_thread(artifacts_for_company, founder_id, company_id)
        except Exception as exc:
            logger.warning("monitoring: artifacts load failed company=%s: %s", company_id, exc)
            continue
        for record in records:
            artifact_key = record.get("artifact_key") or ""
            # Content freshness only when the last content check is >= a week old.
            last_content = await asyncio.to_thread(last_content_check, founder_id, company_id, artifact_key)
            do_content = True
            if last_content:
                from datetime import datetime
                try:
                    age = (datetime.utcnow() - datetime.strptime(last_content, "%Y-%m-%dT%H:%M:%SZ")).days
                    do_content = age >= 7
                except Exception:
                    do_content = True
            check = await check_artifact(record, do_content=do_content)
            if check is None:
                continue
            await asyncio.to_thread(
                add_monitoring_check, founder_id, company_id,
                session_id=record.get("session_id", ""), artifact_key=artifact_key,
                artifact_type=check["kind"], check_type="health", status=check["status"],
                metadata=check["metadata"],
            )
            checks += 1
            if check["status"] in ("down", "stale") and _autoheal_enabled():
                if await _auto_heal(founder_id, company_id, record, check):
                    heals += 1
    return checks, heals


async def _loop(interval_seconds: int) -> None:
    global _status
    while _stop_event and not _stop_event.is_set():
        tick_start = time.monotonic()
        checks = heals = 0
        error_msg = ""
        try:
            checks, heals = await _tick()
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("monitoring: tick raised: %s", exc)
        _status.update({
            "running": True,
            "interval_seconds": interval_seconds,
            "last_tick_at": _now_iso(),
            "last_checks": checks,
            "last_heals": heals,
            "last_error": error_msg,
        })
        elapsed = time.monotonic() - tick_start
        wait = max(0.0, interval_seconds - elapsed)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            continue


def start_monitoring_scheduler(interval_seconds: int = 3600) -> dict[str, Any]:
    """Start the singleton monitoring scheduler. Safe to call repeatedly."""
    global _task, _stop_event, _status
    if _task and not _task.done():
        return get_monitoring_scheduler_status()
    interval = max(60, int(interval_seconds or 3600))
    _stop_event = asyncio.Event()
    _status.update({"running": True, "interval_seconds": interval, "last_error": ""})
    _task = asyncio.create_task(_loop(interval))
    logger.info("monitoring_scheduler: started (interval=%ds)", interval)
    return get_monitoring_scheduler_status()


async def stop_monitoring_scheduler() -> dict[str, Any]:
    global _task, _stop_event, _status
    if _stop_event:
        _stop_event.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except Exception:
            _task.cancel()
    _status["running"] = False
    return get_monitoring_scheduler_status()


def get_monitoring_scheduler_status() -> dict[str, Any]:
    alive = bool(_task and not _task.done())
    return {"ok": True, "scheduler": {**_status, "running": alive}}

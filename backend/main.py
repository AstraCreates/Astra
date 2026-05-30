import asyncio
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.api.admin import router as admin_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Astra API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Cache-Control", "X-Accel-Buffering"],
)

app.include_router(router)
app.include_router(admin_router)


@app.on_event("startup")
async def startup_background_jobs():
    from backend.tools.company_brain_scheduler import start_company_brain_scheduler
    start_company_brain_scheduler(interval_seconds=60)
    asyncio.create_task(_resume_interrupted_sessions())
    asyncio.create_task(_platform_alert_loop())


async def _resume_interrupted_sessions() -> None:
    """On startup, detect sessions that were live when the backend last restarted and re-run remaining agents."""
    import asyncio as _asyncio
    await _asyncio.sleep(3)  # wait for orchestrator singleton to init
    # Hard cap: only resume the most recent N sessions to avoid overloading the server
    _MAX_RESUME = 2
    try:
        from backend.core.events import _redis_active_sessions, _restore_session, _event_log
        from backend.core.factory import get_orchestrator
        interrupted = await _asyncio.to_thread(_redis_active_sessions)
        if not interrupted:
            return
        # Limit to most recent sessions to prevent startup crash loop
        if len(interrupted) > _MAX_RESUME:
            logger.warning(
                "Skipping session resume: %d interrupted sessions found (limit=%d). "
                "Too many to safely resume on startup — mark all as expired.",
                len(interrupted), _MAX_RESUME,
            )
            from backend.core.events import _completed
            for sid in interrupted:
                _completed.add(sid)
            return
        logger.info("Resuming %d interrupted session(s): %s", len(interrupted), interrupted)
        orch = get_orchestrator()
        for session_id in interrupted:
            try:
                await _asyncio.to_thread(_restore_session, session_id)  # returns (bool, bool) — just restore
                events = _event_log.get(session_id, [])
                event_dicts = [e for _, e in events]

                goal_start = next((e for e in event_dicts if e.get("type") == "goal_start"), None)
                if not goal_start:
                    continue
                goal = goal_start.get("goal", "")
                founder_id = goal_start.get("founder_id", "")
                if not goal or not founder_id:
                    continue

                # Collect planned agents from all plan_done events
                planned: set[str] = set()
                for e in event_dicts:
                    if e.get("type") == "plan_done":
                        for t in e.get("tasks", []):
                            planned.add(t["agent"])

                completed_agents: set[str] = {e["agent"] for e in event_dicts if e.get("type") == "agent_done"}
                _RESEARCH = {
                    "research", "research_2", "research_3", "research_4",
                    "research_competitors", "research_competitors_2", "research_competitors_3", "research_competitors_4",
                    "research_execution", "research_execution_2", "research_execution_3", "research_execution_4",
                }
                remaining = list(planned - completed_agents - _RESEARCH)

                if not remaining:
                    logger.info("Session %s: all agents done, marking complete", session_id)
                    from backend.core.events import _completed
                    _completed.add(session_id)
                    continue

                logger.info("Session %s: re-running agents %s", session_id, remaining)
                _asyncio.create_task(orch.continue_run(
                    instruction=goal,
                    founder_id=founder_id,
                    prior_session_id=session_id,
                    agents=remaining,
                    session_id=session_id,
                ))
            except Exception as _se:
                logger.warning("Could not resume session %s: %s", session_id, _se)
    except Exception as e:
        logger.warning("Session resume startup failed: %s", e)


async def _platform_alert_loop() -> None:
    """Periodically persist and deliver operations alerts."""
    await asyncio.sleep(10)
    while True:
        try:
            from backend.alerts import run_alert_check
            await asyncio.to_thread(run_alert_check)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Platform alert check failed: %s", exc)
        await asyncio.sleep(300)


@app.on_event("shutdown")
async def shutdown_background_jobs():
    from backend.tools.company_brain_scheduler import stop_company_brain_scheduler
    await stop_company_brain_scheduler()


@app.get("/health")
async def health():
    from backend.platform_status import platform_status
    return platform_status()


@app.get("/ready")
async def ready(response: Response):
    from backend.platform_status import readiness_status
    result = readiness_status()
    if not result["ready"]:
        response.status_code = 503
    return result


@app.get("/metrics")
async def metrics():
    from backend.platform_status import prometheus_metrics
    return Response(prometheus_metrics(), media_type="text/plain; version=0.0.4")

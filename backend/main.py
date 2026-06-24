import asyncio
import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.api.admin import router as admin_router
from backend.api.workspace_routes import router as workspace_router
from backend.api.teams_routes import teams_router
from backend.api.model_settings_routes import model_settings_router
from backend.api.library_routes import library_router
from backend.api.missions_routes import router as missions_router
from backend.api.skills_routes import skills_router
from backend.api.deployments_routes import deployments_router
from backend.api.credits_routes import credits_router
from backend.api.genome_routes import router as genome_router
from backend.api.outcomes_routes import router as outcomes_router
from backend.api.roadmap_routes import router as roadmap_router
from backend.api.company_routes import router as company_router
from backend.api.team_map_routes import router as team_map_router
from backend.api.connectors_routes import router as connectors_router
from backend.api.notification_routes import router as notification_router
from backend.api.dashboard_routes import router as dashboard_router
from backend.api.preview_proxy import router as preview_proxy_router
from backend.api.custom_agents_routes import custom_agents_router
from backend.api.insights_routes import router as insights_router
from backend.api.funding_routes import router as funding_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Astra API", version="1.0.0")

from backend.config import settings as _settings
_cors_origins = [o.strip() for o in _settings.frontend_url.split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["http://localhost:3003"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-astra-user-id", "x-user-id", "x-astra-email", "x-astra-session"],
    expose_headers=["Content-Type", "Cache-Control", "X-Accel-Buffering"],
)

app.include_router(router)
app.include_router(workspace_router)
app.include_router(admin_router)
app.include_router(teams_router)
app.include_router(model_settings_router)
app.include_router(library_router)
app.include_router(missions_router)
app.include_router(skills_router)
app.include_router(deployments_router)
app.include_router(credits_router)
app.include_router(genome_router)
app.include_router(outcomes_router)
app.include_router(roadmap_router)
app.include_router(company_router)
app.include_router(team_map_router)
app.include_router(connectors_router)
app.include_router(notification_router)
app.include_router(dashboard_router)
app.include_router(custom_agents_router)
app.include_router(insights_router)
app.include_router(funding_router)
app.include_router(preview_proxy_router)


@app.on_event("startup")
async def startup_background_jobs():
    # Store main event loop so publish_sync works from threads
    from backend.core.events import set_main_loop
    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    # Enlarge the default thread pool used by asyncio.to_thread. Agent LLM calls,
    # tools, and long blocking subprocesses (e.g. the technical agent running
    # Claude Code / deploys for up to 10 min) all run here. The default pool is
    # only min(32, cpu+4) = 8 on this box, so a few long technical jobs starve
    # every other agent/session. These threads are I/O/subprocess-bound (GIL
    # released while waiting), so a large pool is safe and keeps everyone moving.
    import os as _os
    from concurrent.futures import ThreadPoolExecutor
    _pool_size = int(_os.environ.get("ASTRA_THREAD_POOL", "128"))
    loop.set_default_executor(ThreadPoolExecutor(max_workers=_pool_size, thread_name_prefix="astra"))
    logger.info("Thread pool sized to %d workers", _pool_size)
    from backend.tools.company_brain_scheduler import start_company_brain_scheduler
    start_company_brain_scheduler(interval_seconds=60)
    from backend.missions.scheduler import start_missions_scheduler
    # Goal loop is event-driven (agent_done → tasks; complete goal → auto-chain).
    # This scheduler is only a 30-min safety net to recover stalled goals.
    start_missions_scheduler(interval_seconds=1800)
    from backend.custom_agents.scheduler import start_custom_agents_scheduler
    # Recurring custom agents — checks for due agents every 15 min.
    start_custom_agents_scheduler(interval_seconds=900)
    from backend.monitoring.scheduler import start_monitoring_scheduler
    # Live company: re-verify shipped artifacts hourly (content weekly) + auto-heal.
    start_monitoring_scheduler(interval_seconds=3600)
    asyncio.create_task(_resume_interrupted_sessions())
    asyncio.create_task(_platform_alert_loop())
    asyncio.create_task(_pii_purge_loop())


async def _resume_interrupted_sessions() -> None:
    """On startup, detect sessions interrupted by the last restart and re-run remaining agents.
    Uses JSONL session store as primary (no TTL, no cap), Redis as fallback.
    """
    import asyncio as _asyncio
    import calendar as _cal
    import time as _time
    await _asyncio.sleep(3)  # wait for orchestrator singleton to init
    _MAX_RESUME = 8
    _RECENT_SECONDS = 2 * 3600  # only resume runs interrupted within the last 2h
    try:
        from backend.core.session_store import (
            scan_interrupted as _ss_interrupted,
            get_session_meta as _ss_meta,
            update_session_status as _ss_status,
        )
        from backend.core.events import _restore_session, _event_log, _completed
        from backend.core.factory import get_orchestrator

        interrupted = await _asyncio.to_thread(_ss_interrupted)
        if not interrupted:
            return

        def _age(sid: str) -> float:
            meta = _ss_meta(sid) or {}
            ts = meta.get("created_at", "")
            try:
                return _time.time() - _cal.timegm(_time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
            except Exception:
                return 1e12  # unknown timestamp → treat as very old

        # Youngest first; resume only recent ones, expire the stale pile so they
        # never get falsely marked "done with work" or block the thread pool.
        interrupted.sort(key=_age)
        recent = [s for s in interrupted if _age(s) < _RECENT_SECONDS][:_MAX_RESUME]
        stale = [s for s in interrupted if s not in set(recent)]

        for sid in stale:
            try:
                await _asyncio.to_thread(_ss_status, sid, "error")  # expired, NOT done
            except Exception:
                pass
            _completed.add(sid)
        if stale:
            logger.info("Marked %d stale interrupted session(s) as expired", len(stale))
        if not recent:
            return

        logger.info("Resuming %d recent interrupted session(s): %s", len(recent), recent)
        orch = get_orchestrator()
        for session_id in recent:
            try:
                await _asyncio.to_thread(_restore_session, session_id)
                event_dicts = [e for _, e in _event_log.get(session_id, [])]

                goal_start = next((e for e in event_dicts if e.get("type") == "goal_start"), None)
                if not goal_start:
                    continue
                goal = goal_start.get("goal", "")
                founder_id = goal_start.get("founder_id", "")
                if not goal or not founder_id:
                    continue

                planned: set[str] = set()
                for e in event_dicts:
                    if e.get("type") == "plan_done":
                        for t in e.get("tasks", []):
                            planned.add(t["agent"])

                completed_agents = {e["agent"] for e in event_dicts if e.get("type") == "agent_done"}
                # Resume ALL incomplete agents, including research — an interrupted
                # research agent should finish its work, not be silently dropped.
                remaining = list(planned - completed_agents)

                if not remaining:
                    logger.info("Session %s: all planned agents done", session_id)
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


async def _pii_purge_loop() -> None:
    """Run the 30-day SSN deletion pipeline once every 24 hours."""
    await asyncio.sleep(60)  # give startup a moment to settle
    while True:
        try:
            from backend.core.pii_vault import purge_expired
            purge_expired()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("PII purge failed: %s", exc)
        await asyncio.sleep(86_400)  # 24 hours


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


# ── MCP HTTP endpoint ─────────────────────────────────────────────────────────
# Calls Python functions directly — no HTTP loop-back to avoid single-worker deadlock.

@app.post("/mcp")
async def mcp_http(request: Request):
    import json as _json
    import asyncio as _asyncio
    body = await request.body()
    try:
        req = _json.loads(body)
    except Exception:
        return Response(
            content=_json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}),
            media_type="application/json",
        )
    request_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    def _tool_result(payload: dict) -> dict:
        return {
            "content": [{"type": "text", "text": _json.dumps(payload, indent=2, sort_keys=True)}],
            "structuredContent": payload,
            "isError": not payload.get("ok", True),
        }

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "astra", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            from backend.astra_mcp import TOOLS
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            founder_id = args.get("founder_id") or "founder_001"
            if name == "astra_submit_goal":
                from backend.core.session_ids import new_session_id
                from backend.core.factory import get_orchestrator
                orch = get_orchestrator()
                stack_id = args.get("stack_id") or "idea_to_revenue"
                constraints: dict = {}
                if args.get("company_name"):
                    constraints["company_name"] = args["company_name"]
                if stack_id == "custom" and args.get("agents"):
                    constraints["agents"] = args["agents"]
                constraints["stack_id"] = stack_id
                session_id = new_session_id()
                _asyncio.create_task(orch.run(
                    goal=args["goal"], founder_id=founder_id,
                    constraints=constraints, session_id=session_id,
                ))
                payload = {"ok": True, "session_id": session_id, "status": "running",
                           "message": f"Use astra_session_status(session_id='{session_id}') to monitor."}
                result = _tool_result(payload)
            elif name == "astra_steer":
                from backend.core.events import steer_push
                steer_push(args["session_id"], args["message"])
                result = _tool_result({"ok": True, "message": "Steering instruction delivered."})
            elif name == "astra_chat_agent":
                import openai as _openai
                from backend.config import settings
                from backend.core.factory import get_orchestrator
                orch = get_orchestrator()
                agent_name = args.get("agent", "research")
                specialist = orch.specialists.get(agent_name)
                if not specialist:
                    payload = {"ok": False, "error": f"Unknown agent: {agent_name}"}
                else:
                    client = _openai.AsyncOpenAI(
                        base_url=settings.chat_model_base_url or settings.agent_model_base_url,
                        api_key=settings.chat_model_api_key or settings.agent_model_api_key,
                    )
                    resp = await client.chat.completions.create(
                        model=settings.chat_model_name or settings.agent_model_name,
                        messages=[
                            {"role": "system", "content": specialist.role},
                            {"role": "user", "content": args["question"]},
                        ],
                        max_tokens=1024,
                        extra_body={"provider": {"allow_fallbacks": True}},
                    )
                    payload = {"ok": True, "agent": agent_name, "response": (resp.choices[0].message.content if getattr(resp, "choices", None) else "")}
                result = _tool_result(payload)
            else:
                result = _tool_result(await _asyncio.to_thread(_dispatch_mcp, name, args, founder_id))
        else:
            raise ValueError(f"Unsupported method: {method}")
        content = _json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, separators=(",", ":"))
    except Exception as exc:
        content = _json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}, separators=(",", ":"))
    return Response(content=content, media_type="application/json")


def _dispatch_mcp(name: str, args: dict, founder_id: str) -> dict:
    """Dispatch MCP tool calls directly to Python functions — no HTTP."""
    import uuid as _uuid
    import json
    from backend.stacks.compiler import recommend_stack
    from backend.stacks.catalog import get_agent_catalog
    from backend.api.routes import router as _router

    if name == "astra_list_stacks":
        from backend.stacks.templates import STACK_TEMPLATES
        return {"ok": True, "stacks": [
            {"id": s.stack_id, "name": s.name, "target_user": s.target_user,
             "primary_outcome": s.primary_outcome, "agent_count": len(s.tasks)}
            for s in STACK_TEMPLATES.values()
        ]}

    if name == "astra_list_agents":
        return {"ok": True, "agents": get_agent_catalog()}

    if name == "astra_recommend_stack":
        r = recommend_stack(args["goal"])
        return {
            "ok": True,
            "recommended_stack_id": r.stack.stack_id,
            "recommended_stack_name": r.stack.name,
            "confidence": r.confidence,
            "reason": r.reason,
            "matched_signals": r.matched_signals,
        }

    if name in ("astra_submit_goal", "astra_steer", "astra_chat_agent"):
        return {"ok": False, "error": f"{name} must be handled by the async dispatcher"}

    if name == "astra_session_status":
        from backend.core.events import _event_log, _completed
        session_id = args["session_id"]
        events = [e for _, e in _event_log.get(session_id, [])]
        done = session_id in _completed
        agents: dict = {}
        for e in events:
            ag = e.get("agent")
            if not ag:
                continue
            if e["type"] == "agent_start":
                agents[ag] = {"status": "running"}
            elif e["type"] == "agent_done":
                agents[ag] = {"status": "done"}
            elif e["type"] == "agent_error":
                agents[ag] = {"status": "error"}
        done_count = sum(1 for a in agents.values() if a["status"] == "done")
        return {"ok": True, "session_id": session_id, "done": done,
                "agents_done": done_count, "agents_total": len(agents),
                "completion_pct": round(done_count / len(agents) * 100) if agents else 0,
                "agents": agents}

    if name == "astra_session_digest":
        from backend.core.events import _event_log
        session_id = args["session_id"]
        events = [e for _, e in _event_log.get(session_id, [])]
        artifacts = [e for e in events if e.get("type") == "artifact"]
        agent_summaries = {e["agent"]: e.get("summary", "") for e in events if e.get("type") == "agent_done" and e.get("summary")}
        return {"ok": True, "session_id": session_id, "artifact_count": len(artifacts),
                "artifacts": artifacts, "agent_summaries": agent_summaries}

    if name == "astra_session_artifacts":
        from backend.core.events import _event_log
        session_id = args["session_id"]
        events = [e for _, e in _event_log.get(session_id, [])]
        artifacts = [e for e in events if e.get("type") in ("artifact", "run_artifact")]
        return {"ok": True, "session_id": session_id, "artifact_count": len(artifacts), "artifacts": artifacts}

    if name == "astra_chat_agent":
        # Chat is handled separately as async — return a placeholder for sync dispatch
        return {"ok": False, "error": "Use the /chat/{agent} endpoint directly or the stdio MCP for agent chat."}


    if name == "astra_session_workboard":
        from backend.core.events import _event_log
        session_id = args["session_id"]
        events = [e for _, e in _event_log.get(session_id, [])]
        tasks = [e for e in events if e.get("type") in ("task_start", "task_done", "task_error")]
        return {"ok": True, "session_id": session_id, "tasks": tasks}

    if name == "astra_approve":
        try:
            from backend.core.events import steer_push
            steer_push(args["session_id"], json.dumps({"type": "approval_decision", "action_key": args["action_key"], "decision": "approve", "founder_id": founder_id}))
            return {"ok": True, "action_key": args["action_key"], "decision": "approve"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"Unknown tool: {name}"}

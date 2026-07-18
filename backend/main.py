import asyncio
import logging
import os

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
from backend.api.company_os_routes import router as company_os_router
from backend.api.company_os_phase1_routes import router as company_os_phase1_router

logger = logging.getLogger(__name__)
_background_tasks: list[asyncio.Task] = []

app = FastAPI(title="Astra API", version="1.0.0")

from backend.config import settings as _settings
# Explicit allow-list only — never "*". Header-based auth (x-astra-user-id) means a
# wildcard origin would let any website drive the API using a visitor's own session.
# Set via ASTRA_CORS_ORIGINS (comma-separated) in .env; see backend/config.py.
_cors_origins = [o.strip() for o in _settings.astra_cors_origins.split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Last-Event-ID", "x-astra-user-id", "x-user-id", "x-astra-email", "x-astra-session"],
    expose_headers=["Content-Type", "Cache-Control", "X-Accel-Buffering"],
)
# minimum_size=1024: session/goal SSE streams send frequent small text/event-stream
# chunks — compressing those would buffer them and add latency for no bandwidth win.
# The actual targets (session lists, brain records, flow/integration catalogs) are
# multi-KB JSON payloads well above this floor.
app.add_middleware(GZipMiddleware, minimum_size=1024)

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
app.include_router(company_os_router)
app.include_router(company_os_phase1_router)
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
    from backend.production_env import audit_runtime_settings
    runtime_env = audit_runtime_settings(_settings)
    if not runtime_env.get("ok") and runtime_env.get("mode") == "production":
        raise RuntimeError(runtime_env.get("summary") or "Production env validation failed.")

    # Wave 5.2: OTel is mandatory (unlike the still-disabled Langfuse flag). Must run
    # before any run/workflow/agent code so get_tracer() is populated by the time the
    # first request lands; init_tracing() itself never raises.
    from backend.observability.tracing import init_tracing
    init_tracing()

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
    from concurrent.futures import ThreadPoolExecutor
    _pool_size = max(4, min(64, int(os.environ.get("ASTRA_THREAD_POOL", "32"))))
    loop.set_default_executor(ThreadPoolExecutor(max_workers=_pool_size, thread_name_prefix="astra"))
    logger.info("Thread pool sized to %d workers", _pool_size)
    logger.info(
        "Model routing: mvp_build=%s technical=%s technical_build=%s technical_subagent=%s web=%s planner=%s highoutput=%s light=%s tool_heavy=%s tooluse=%s chat=%s",
        _settings.mvp_build_model,
        _settings.technical_agent_model,
        _settings.technical_build_model,
        _settings.technical_subagent_model,
        _settings.web_agent_model,
        _settings.or_planner_model,
        _settings.or_highoutput_model,
        _settings.or_light_model,
        _settings.tool_heavy_agent_model,
        _settings.tooluse_model_name,
        _settings.chat_model_name,
    )
    # Reconcile sessions left "running"/"queued" by a prior process crash/restart.
    # This is a durable-store sweep and must not block readiness on a large store.
    async def _reconcile_sessions_in_background() -> None:
        try:
            from backend.core.session_store import reconcile_orphaned_sessions
            reconciled = await asyncio.to_thread(reconcile_orphaned_sessions)
            if reconciled:
                logger.info("startup session reconciliation: marked %d orphaned session(s) as error: %s", len(reconciled), reconciled)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("startup session reconciliation failed: %s", exc)

    _background_tasks.append(asyncio.create_task(_reconcile_sessions_in_background()))

    # Copilot turns may intentionally outlive their original HTTP request. Their
    # queued state lives in session metadata, so reconnect them after a restart.
    # Recovery scans durable session metadata and must not block readiness: on a
    # large store that scan can outlive the container health-check window.
    async def _recover_copilot_turns_in_background() -> None:
        try:
            from backend.copilot import recover_pending_copilot_turns
            recovered = await recover_pending_copilot_turns()
            if recovered:
                logger.info("startup copilot recovery: resumed %d pending turn(s)", recovered)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("startup copilot recovery failed: %s", exc)

    _background_tasks.append(asyncio.create_task(_recover_copilot_turns_in_background()))

    async def _recover_company_os_work_in_background() -> None:
        try:
            from backend.company_os_runner import recover_pending_missions
            recovered = await recover_pending_missions()
            if recovered:
                logger.info("startup Company OS recovery: resumed %d pending mission(s)", recovered)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("startup Company OS recovery failed: %s", exc)

    _background_tasks.append(asyncio.create_task(_recover_company_os_work_in_background()))

    from backend.tools.company_brain_scheduler import start_company_brain_scheduler
    start_company_brain_scheduler(interval_seconds=60)
    from backend.company_os_phase1_scheduler import start_company_os_phase_1_scheduler
    start_company_os_phase_1_scheduler(interval_seconds=3600)
    from backend.missions.scheduler import start_missions_scheduler
    # Goal loop is event-driven (agent_done → tasks; complete goal → auto-chain).
    # This scheduler is only a 30-min safety net to recover stalled goals.
    await start_missions_scheduler(interval_seconds=1800)
    from backend.custom_agents.scheduler import start_custom_agents_scheduler
    # Recurring custom agents — checks for due agents every 15 min.
    await start_custom_agents_scheduler(interval_seconds=900)
    from backend.monitoring.scheduler import start_monitoring_scheduler
    # Live company: re-verify shipped artifacts hourly (content weekly) + auto-heal.
    await start_monitoring_scheduler(interval_seconds=3600)
    _background_tasks[:] = [
        asyncio.create_task(_platform_alert_loop()),
        asyncio.create_task(_pii_purge_loop()),
        asyncio.create_task(_budget_reservation_reaper_loop()),
        asyncio.create_task(_control_plane_outbox_loop()),
        asyncio.create_task(_control_plane_rollout_loop()),
    ]


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


async def _budget_reservation_reaper_loop() -> None:
    """Wave 1 orphan reaper: release expired budget reservations that never
    got committed (e.g. process crash between reserve() and commit()) so they
    don't sit "reserved" forever, silently eating into a founder's available
    balance for the next reservation. Reservations default to a 300s TTL
    (backend/control_plane/budget.py::DEFAULT_TTL_SECONDS) -- checking every
    120s catches them well inside that window without excessive churn."""
    await asyncio.sleep(30)
    while True:
        try:
            from backend.control_plane.budget import get_default_budget_service
            expired = get_default_budget_service().expire_orphans()
            if expired:
                logger.info("budget reservation reaper: released %d expired reservation(s)", len(expired))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Budget reservation reaper failed: %s", exc)
        await asyncio.sleep(120)


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


async def _control_plane_outbox_loop() -> None:
    await asyncio.sleep(5)
    from backend.control_plane.event_stream import outbox_publisher_loop

    await outbox_publisher_loop()


async def _control_plane_rollout_loop() -> None:
    """Periodically evaluate active rollout campaigns from durable run state."""
    await asyncio.sleep(20)
    while True:
        try:
            from backend.control_plane.wave7_automation import run_all_rollout_automation_ticks

            run_all_rollout_automation_ticks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Control-plane rollout automation failed: %s", exc)
        await asyncio.sleep(300)


@app.on_event("shutdown")
async def shutdown_background_jobs():
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    from backend.tools.company_brain_scheduler import stop_company_brain_scheduler
    await stop_company_brain_scheduler()
    from backend.missions.scheduler import stop_missions_scheduler
    from backend.custom_agents.scheduler import stop_custom_agents_scheduler
    from backend.monitoring.scheduler import stop_monitoring_scheduler
    await stop_missions_scheduler()
    await stop_custom_agents_scheduler()
    await stop_monitoring_scheduler()


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
async def metrics(request: Request):
    from backend.tenant_auth import require_platform_admin
    require_platform_admin(request)
    from backend.platform_status import prometheus_metrics
    return Response(prometheus_metrics(), media_type="text/plain; version=0.0.4")


# ── MCP HTTP endpoint ─────────────────────────────────────────────────────────
# Calls Python functions directly — no HTTP loop-back to avoid single-worker deadlock.

@app.post("/mcp")
async def mcp_http(request: Request):
    import json as _json
    import asyncio as _asyncio
    from backend.tenant_auth import request_user_id as _request_user_id
    from backend.config import settings as _cfg

    # Authenticate — derive caller identity from verified token/trusted header.
    # initialize + tools/list are allowed unauthenticated (metadata only).
    # Any tools/call that mutates state requires an authenticated identity.
    _caller_id: str | None = _request_user_id(request)

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
            mutating_tools = {
                "astra_submit_goal",
                "astra_steer",
                "astra_message_agent",
                "astra_stop_agent",
                "astra_approve",
                "astra_approve_next_goal",
                "astra_run_cycle",
            }
            # Require authenticated identity for configured auth, and always for mutations.
            if (_cfg.astra_require_auth or name in mutating_tools) and not _caller_id:
                return Response(
                    content=_json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Unauthorized"}}),
                    media_type="application/json", status_code=401,
                )
            # founder_id ALWAYS comes from auth context — never from caller-supplied args
            founder_id = _caller_id or ""
            # Reject if caller tries to impersonate another founder
            if args.get("founder_id") and args["founder_id"] != founder_id:
                return Response(
                    content=_json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": "Forbidden: founder_id mismatch"}}),
                    media_type="application/json", status_code=403,
                )
            args.pop("founder_id", None)  # strip — will be injected from auth context
            if name == "astra_submit_goal":
                from backend.api.schemas import RunCreateRequest
                from backend.control_plane.start_run import start_run as control_plane_start_run
                stack_id = args.get("stack_id") or "idea_to_revenue"
                constraints: dict = {}
                if args.get("company_name"):
                    constraints["company_name"] = args["company_name"]
                if stack_id == "custom" and args.get("agents"):
                    constraints["agents"] = args["agents"]
                payload_result = await control_plane_start_run(
                    RunCreateRequest(
                        founder_id=founder_id,
                        instruction=args["goal"],
                        stack_id=stack_id,
                        constraints=constraints,
                    ),
                    request=None,
                )
                payload = {"ok": True, "session_id": payload_result.session_id, "status": payload_result.status,
                           "message": f"Use astra_session_status(session_id='{payload_result.session_id}') to monitor."}
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
                    from backend.core.llm_client import get_async_or_client
                    from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
                    client = get_async_or_client(
                        settings.chat_model_base_url or settings.agent_model_base_url,
                        settings.chat_model_api_key or settings.agent_model_api_key,
                    )
                    resp = await client.chat.completions.create(
                        model=settings.chat_model_name or settings.agent_model_name,
                        messages=[
                            {"role": "system", "content": specialist.role},
                            {"role": "user", "content": args["question"]},
                        ],
                        max_tokens=1024,
                        extra_body=openrouter_extra_body(settings.chat_model_name or settings.agent_model_name),
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

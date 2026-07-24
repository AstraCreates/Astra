import asyncio
import contextvars
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

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
from backend.api.company_routes import router as company_router
from backend.api.connectors_routes import router as connectors_router
from backend.api.notification_routes import router as notification_router
from backend.api.dashboard_routes import router as dashboard_router
from backend.api.preview_proxy import router as preview_proxy_router
from backend.api.custom_agents_routes import custom_agents_router
from backend.api.insights_routes import router as insights_router
from backend.api.funding_routes import router as funding_router
from backend.api.company_os_routes import router as company_os_router
from backend.api.voice_routes import router as voice_router

logger = logging.getLogger(__name__)
_background_tasks: list[asyncio.Task] = []

app = FastAPI(title="Astra API", version="1.0.0")


# ── Process role: web or worker ─────────────────────────────────────────────
# Replaces the old "skip everything if WEB_CONCURRENCY>1" gate. The dedicated
# Temporal worker container sets ``ASTRA_WORKER_ROLE=worker`` and now owns
# recovery + schedulers exclusively; the FastAPI web containers set
# ``ASTRA_WORKER_ROLE=web`` and skip every background job that races on
# shared JSON stores (Company OS event log, run ledger, approval ledger,
# session metadata, control-plane outbox).
#
# Values:
#   worker — run in-process recovery + schedulers + control-plane loops
#   web    — skip every in-process background job (the worker does them)
#   auto   — default for tests/local dev. Mirrors the historical behavior:
#            single-process runs everything like ``worker``; multi-process
#            ``WEB_CONCURRENCY>1`` runs none like ``web``. Set it explicitly
#            in production to make the role unambiguous.
def _process_role() -> str:
    explicit = (os.environ.get("ASTRA_WORKER_ROLE") or "").strip().lower()
    if explicit in {"worker", "web"}:
        return explicit
    if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
        return "web"
    return "worker"


# ── Correlation ID + request timing context ────────────────────────────────
# Read by structured logging handlers so every log line emitted while a
# request is in flight is correlatable with the browser's network panel via
# the X-Correlation-ID response header. Setting it as a contextvar (not just
# request.state) is critical: background tasks spawned via asyncio.create_task
# later in the request lose the FastAPI Request object but inherit the
# contextvar, so their log lines still carry the correlation — which is the
# whole point of having the id in the first place.
_correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "astra_correlation_id", default=None
)


def current_correlation_id() -> str | None:
    """Return the correlation id active in the current async task, if any."""
    return _correlation_id_var.get()


_SLOW_LOG_MS = float(os.environ.get("ASTRA_SLOW_REQUEST_MS", "750"))


@app.middleware("http")
async def correlation_id_and_timing_middleware(request: Request, call_next):
    incoming = (
        request.headers.get("x-correlation-id")
        or request.headers.get("x-request-id")
        or ""
    ).strip()
    corr_id = incoming or uuid.uuid4().hex
    token = _correlation_id_var.set(corr_id)
    request.state.correlation_id = corr_id
    start = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Correlation-ID"] = corr_id
        response.headers["X-Response-Time-Ms"] = f"{(time.monotonic() - start) * 1000:.2f}"
        return response
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        # Suppress noisy health-check traffic from the timing log; the
        # container-level health probe does not need a per-request line.
        path = request.url.path
        if path in {"/health", "/ready", "/release"}:
            return
        should_log = (
            status_code >= 500
            or status_code == 429
            or (status_code >= 400 and path.startswith("/api"))
            or elapsed_ms >= _SLOW_LOG_MS
        )
        if should_log:
            level = logging.WARNING if status_code >= 500 or elapsed_ms >= _SLOW_LOG_MS * 2 else logging.INFO
            logger.log(
                level,
                "request method=%s path=%s status=%d duration_ms=%.2f corr_id=%s",
                request.method,
                path,
                status_code,
                elapsed_ms,
                corr_id,
            )
        _correlation_id_var.reset(token)


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
    expose_headers=["Content-Type", "Cache-Control", "X-Accel-Buffering", "X-Correlation-ID", "X-Response-Time-Ms"],
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
app.include_router(company_router)
app.include_router(company_os_router)
app.include_router(connectors_router)
app.include_router(notification_router)
app.include_router(dashboard_router)
app.include_router(custom_agents_router)
app.include_router(insights_router)
app.include_router(funding_router)
app.include_router(voice_router)
app.include_router(preview_proxy_router)


@app.on_event("startup")
async def startup_background_jobs():
    from backend.production_env import audit_runtime_settings
    runtime_env = audit_runtime_settings(_settings)
    if not runtime_env.get("ok") and runtime_env.get("mode") == "production":
        # Log loud, never crash boot over it: the same audit is already surfaced
        # non-blocking via /admin/production-verification (platform_status.py),
        # and inferring "production" from URL/require_auth alone false-positives
        # on any local run against a copied prod .env (this exact gate already
        # flip-flopped once between hard-fail and soft-fail, see git history).
        logging.getLogger(__name__).error(
            "Production env validation failed: %s",
            runtime_env.get("summary") or "unknown",
        )

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
    # Uvicorn starts this hook once per worker. Durable recovery scans and
    # schedulers are owned by the dedicated Temporal worker in production;
    # running them in every web worker races on shared JSON stores. The
    # explicit ASTRA_WORKER_ROLE flag replaces the "WEB_CONCURRENCY==1 ?
    # worker : skip" inference so this can no longer silently flip.
    role = _process_role()
    if role != "worker":
        explicit = os.environ.get("ASTRA_WORKER_ROLE")
        logger.info(
            "Skipping in-process recovery, schedulers, and control-plane loops (ASTRA_WORKER_ROLE=%s)",
            explicit if explicit else f"auto→{role}",
        )
        return
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

    # Same sweep, for the separate run_ledger store: a run left "running" after
    # a crash/restart is never revisited otherwise, so it gets permanently
    # relabeled "stalled" by normalize_run_row() on every future read.
    async def _reap_stale_runs_in_background() -> None:
        try:
            from backend.run_ledger import reap_stale_runs
            reaped = await asyncio.to_thread(reap_stale_runs)
            if reaped:
                logger.info("startup run-ledger reap: marked %d orphaned run(s) as error: %s", len(reaped), reaped)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("startup run-ledger reap failed: %s", exc)

    _background_tasks.append(asyncio.create_task(_reap_stale_runs_in_background()))

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

    # Sweep any approval requests that were ACK'd by the async /os/approvals
    # endpoint but whose side-effects (update_task → update_mission →
    # launch_mission → reconcile_initiatives) were never applied -- either
    # because the web worker accepted the click and the process restarted
    # before asyncio.create_task ran, or because the analyze-side-effect step
    # crashed after the durable ledger write. Idempotent: a second run after
    # side-effects did complete is a no-op (replay_event leaves events that
    # already match the desired state untouched).
    async def _resync_company_os_async_approvals() -> None:
        try:
            from backend.api.company_os_routes import resync_pending_async_approvals
            count = await asyncio.to_thread(resync_pending_async_approvals)
            if count:
                logger.info("startup async approval resync: applied %d side-effect(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("async approval resync failed: %s", exc)

    _background_tasks.append(asyncio.create_task(_resync_company_os_async_approvals()))

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
        asyncio.create_task(_company_os_recovery_loop()),
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


async def _company_os_recovery_loop() -> None:
    """Recover Company OS missions that became orphaned while the process stayed up.

    Startup recovery handles crash/restart orphans, but a task can also be left
    stale if an in-process worker is cancelled or loses its final state update.
    Use the existing locked recovery path so periodic healing and startup
    recovery share the same safety checks.
    """
    await asyncio.sleep(120)
    while True:
        try:
            from backend.company_os_runner import recover_pending_missions

            recovered = await recover_pending_missions()
            if recovered:
                logger.info("Company OS recovery loop: resumed %d pending mission(s)", recovered)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Company OS recovery loop failed: %s", exc)
        await asyncio.sleep(300)


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


# Cache the release sha for 30 s. The sidebar polls every 30 s on multiple
# tabs and never needs sub-second freshness; pinning a TTL collapses a 30-tab
# fanout into one disk read every 30 s.
from backend.core.lt_cache import ttl_cache as _release_ttl


@_release_ttl(ttl_seconds=30)
def _release_identity() -> dict[str, str]:
    return {"sha": os.environ.get("ASTRA_RELEASE_SHA", "development")}


@app.get("/release")
async def release_identity():
    """Expose the runtime release identity for deploy verification only."""
    return await asyncio.to_thread(_release_identity)


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

    # Retired run/session tools return a deterministic removal response even
    # without authentication. This avoids making clients interpret an auth
    # challenge as a missing compatibility migration.
    if method == "tools/call" and params.get("name") in {"astra_submit_goal", "astra_session_status", "astra_session_digest", "astra_session_artifacts", "astra_chat_agent", "astra_steer", "astra_message_agent", "astra_stop_agent", "astra_approve", "astra_session_workboard", "astra_company_goal", "astra_approve_next_goal", "astra_run_cycle"}:
        payload = {"ok": False, "error": "legacy_run_session_removed", "message": "Use Company OS tools instead."}
        result = {"content": [{"type": "text", "text": _json.dumps(payload)}], "structuredContent": payload, "isError": True}
        return Response(content=_json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": result}), media_type="application/json")

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
                "astra_library_create",
                "astra_library_update",
                "astra_library_append",
                "astra_library_delete",
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
            # The HTTP adapter must use the same Company OS MCP boundary as
            # stdio and in-process callers. Do not maintain a second legacy
            # dispatcher here: it could resurrect run/session actions or drift
            # from the tools/list contract.
            from backend import astra_mcp as _astra_mcp
            if name in _astra_mcp._LEGACY_MCP_TOOLS:
                result = _tool_result({"ok": False, "error": "This MCP run/session tool was removed. Use Company OS tools instead."})
            else:
                result = _tool_result(await _asyncio.to_thread(_astra_mcp.call_tool, name, args, founder_id))
            content = _json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, separators=(",", ":"))
            return Response(content=content, media_type="application/json")
        else:
            raise ValueError(f"Unsupported method: {method}")
        content = _json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, separators=(",", ":"))
    except Exception as exc:
        content = _json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}, separators=(",", ":"))
    return Response(content=content, media_type="application/json")

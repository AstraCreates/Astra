"""Production health, readiness, and platform metrics.

This module gives Astra one authoritative operational snapshot for deploys,
admin surfaces, and monitors. It checks the stateful systems that matter for
the Agent Stack Platform: Redis/event replay, Company Brain sync, approval
ledgers, workflow snapshots, core credentials, and local resource pressure.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


_STARTED_AT = time.time()


def _now_epoch() -> int:
    return int(time.time())


def _dir_count(path: str, pattern: str = "*") -> int:
    root = Path(path)
    if not root.exists():
        return 0
    return len(list(root.glob(pattern)))


def _check_redis() -> dict[str, Any]:
    try:
        from backend.core.events import _redis
        client = _redis()
        if not client:
            return {"ok": False, "status": "unavailable", "detail": "Redis client not connected."}
        client.ping()
        return {"ok": True, "status": "ok"}
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_supabase() -> dict[str, Any]:
    try:
        from backend.config import settings
        configured = bool(settings.supabase_url and settings.supabase_key)
        return {
            "ok": configured,
            "status": "configured" if configured else "missing_config",
            "detail": "" if configured else "SUPABASE_URL or SUPABASE_KEY is missing.",
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_models() -> dict[str, Any]:
    try:
        from backend.config import settings
        required = {
            "agent_model": bool(settings.agent_model_base_url and settings.agent_model_name and settings.agent_model_api_key),
            "planner_model": bool(settings.planner_model_base_url and settings.planner_model_name and settings.planner_model_api_key),
            "chat_model": bool(settings.chat_model_base_url and settings.chat_model_name and settings.chat_model_api_key),
        }
        missing = [key for key, ok in required.items() if not ok]
        return {
            "ok": not missing,
            "status": "configured" if not missing else "missing_config",
            "missing": missing,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_company_brain_scheduler() -> dict[str, Any]:
    try:
        from backend.tools.company_brain_scheduler import get_company_brain_scheduler_status
        status = get_company_brain_scheduler_status().get("scheduler", {})
        return {
            "ok": bool(status.get("running")),
            "status": "running" if status.get("running") else "stopped",
            **status,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_storage() -> dict[str, Any]:
    try:
        from backend.storage_adapter import storage_status
        return storage_status()
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_stack_templates() -> dict[str, Any]:
    try:
        from backend.stack_catalog_proof import build_stack_catalog_proof
        proof = build_stack_catalog_proof()
        failures = proof.get("failed", [])
        min_score = min((int(item.get("quality_score") or 0) for item in proof.get("stacks", [])), default=0)
        return {
            "ok": bool(proof.get("ok")),
            "status": "ready" if proof.get("ok") else "failed",
            "templates": int(proof.get("stack_count") or 0),
            "ready_templates": int(proof.get("ready_count") or 0),
            "min_score": min_score,
            "failures": [
                {"stack_id": item.get("stack_id"), "gaps": item.get("gaps", [])}
                for item in failures
            ],
            "catalog_proof": proof,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_accounts_billing() -> dict[str, Any]:
    try:
        from backend.accounts import PLANS
        from backend.billing import (
            apply_platform_billing_event,
            billing_config_status,
            create_checkout_session,
            create_customer_portal_session,
            verify_stripe_signature,
        )
        required_plans = {"beta", "starter", "team", "scale"}
        missing_plans = sorted(required_plans - set(PLANS))
        plan_gaps = [
            plan_id
            for plan_id, plan in PLANS.items()
            if not {"monthly_runs", "team_seats", "connector_syncs_per_day", "approval_workflows", "company_brain"} <= set(plan)
        ]
        billing_config = billing_config_status()
        callable_ok = all(callable(fn) for fn in (
            apply_platform_billing_event,
            verify_stripe_signature,
            create_checkout_session,
            create_customer_portal_session,
        ))
        return {
            "ok": not missing_plans and not plan_gaps and callable_ok,
            "status": "ready" if not missing_plans and not plan_gaps and callable_ok else "misconfigured",
            "plans": sorted(PLANS),
            "missing_plans": missing_plans,
            "plan_gaps": plan_gaps,
            "stripe_webhook_handler": callable_ok,
            "billing_config": billing_config,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_objective_readiness() -> dict[str, Any]:
    try:
        from backend.objective_readiness import build_objective_readiness
        return build_objective_readiness()
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc), "checks": []}


def _check_auth_policy() -> dict[str, Any]:
    try:
        from backend.config import settings
        require_auth = bool(settings.astra_require_auth)
        trusted_headers = bool(settings.astra_trust_auth_headers)
        jwt_configured = bool(settings.astra_jwt_secret or settings.astra_jwt_jwks_url or settings.astra_jwt_issuer)
        platform_admins = [item.strip() for item in str(settings.astra_platform_admins or "").split(",") if item.strip()]
        gaps: list[str] = []
        if require_auth and not jwt_configured and not trusted_headers:
            gaps.append("No trusted auth source configured while ASTRA_REQUIRE_AUTH is enabled.")
        if require_auth and not platform_admins:
            gaps.append("ASTRA_PLATFORM_ADMINS is empty while auth is enabled.")
        return {
            "ok": not gaps,
            "status": "ready" if not gaps else "misconfigured",
            "require_auth": require_auth,
            "trusted_headers": trusted_headers,
            "jwt_configured": jwt_configured,
            "platform_admin_count": len(platform_admins),
            "gaps": gaps,
        }
    except Exception as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


def _check_durable_ledgers() -> dict[str, Any]:
    checks = {
        "workflows": _writable_dir(".astra/workflows"),
        "approvals": _writable_dir(".astra/approvals"),
        "connector_sync": _writable_dir(".astra/connector_sync"),
        "run_ledger": _writable_dir(".astra/run_ledger"),
        "accounts": _writable_dir(".astra/accounts"),
    }
    failures = {key: value for key, value in checks.items() if not value.get("ok")}
    return {
        "ok": not failures,
        "status": "writable" if not failures else "not_writable",
        "checks": checks,
        "failures": failures,
    }


def _writable_dir(path: str) -> dict[str, Any]:
    try:
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".healthcheck"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return {"ok": True, "path": str(root)}
    except Exception as exc:
        return {"ok": False, "path": path, "detail": str(exc)}


def _runtime_metrics() -> dict[str, Any]:
    try:
        import psutil
        proc = psutil.Process()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "ok": True,
            "cpu_percent": psutil.cpu_percent(interval=0.0),
            "memory_percent": memory.percent,
            "disk_percent": disk.percent,
            "process_rss_mb": round(proc.memory_info().rss / 1e6, 2),
            "open_fds": proc.num_fds() if hasattr(proc, "num_fds") else None,
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _state_metrics() -> dict[str, Any]:
    try:
        from backend.core.events import _completed, _event_log, _sessions
        active = len([session_id for session_id in _sessions if session_id not in _completed])
        events = sum(len(items) for items in _event_log.values())
    except Exception:
        active = 0
        events = 0
    try:
        from backend.run_ledger import ledger_metrics
        ledger = ledger_metrics()
    except Exception:
        ledger = {}
    try:
        from backend.connector_sync_ledger import connector_sync_metrics
        connector_sync = connector_sync_metrics()
    except Exception:
        connector_sync = {}
    try:
        from backend.alerts import alert_metrics
        alerts = alert_metrics()
    except Exception:
        alerts = {}
    try:
        from backend.runtime.metrics import snapshot as runtime_agent_metrics
        agent_runtime = runtime_agent_metrics()
    except Exception:
        agent_runtime = {}
    try:
        from backend.runtime.circuit_breaker import status as circuit_breaker_status
        runtime_rollbacks = circuit_breaker_status()
    except Exception:
        runtime_rollbacks = {}
    return {
        "sessions_active": active,
        "sessions_completed": len(_safe_completed()),
        "events_buffered": events,
        "agent_runtime": agent_runtime,
        "runtime_rollbacks": runtime_rollbacks,
        "workflow_snapshots": _dir_count(".astra/workflows", "*.json"),
        "approval_ledgers": _dir_count(".astra/approvals", "*.json"),
        "company_brains": _dir_count(".astra/company_brain", "*.json"),
        "storage_mirror_documents": _dir_count(".astra/storage_mirror/*", "*.json"),
        **ledger,
        **connector_sync,
        **alerts,
    }


def _safe_completed() -> set[str]:
    try:
        from backend.core.events import _completed
        return set(_completed)
    except Exception:
        return set()


def platform_status() -> dict[str, Any]:
    storage_check = _check_storage()
    stack_template_check = _check_stack_templates()
    checks = {
        "redis": _check_redis(),
        "supabase": _check_supabase(),
        "models": _check_models(),
        "company_brain_scheduler": _check_company_brain_scheduler(),
        "storage": storage_check,
        "stack_templates": stack_template_check,
        "objective_readiness": _check_objective_readiness(),
        "accounts_billing": _check_accounts_billing(),
        "auth_policy": _check_auth_policy(),
        "durable_ledgers": _check_durable_ledgers(),
        "runtime": _runtime_metrics(),
    }
    required = ["redis", "models", "company_brain_scheduler", "stack_templates", "objective_readiness", "accounts_billing", "auth_policy", "durable_ledgers"]
    if storage_check.get("backend") in {"supabase", "dual"}:
        required.append("storage")
    ready = all(checks[key].get("ok") for key in required)
    healthy = ready and not (checks["runtime"].get("memory_percent", 0) > 92 or checks["runtime"].get("disk_percent", 0) > 92)
    return {
        "status": "healthy" if healthy else "degraded",
        "ready": ready,
        "started_at": int(_STARTED_AT),
        "now": _now_epoch(),
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "checks": checks,
        "state": _state_metrics(),
        "release": {
            "pid": os.getpid(),
            "cwd": os.getcwd(),
        },
    }


def readiness_status() -> dict[str, Any]:
    status = platform_status()
    readiness_keys = {"redis", "models", "company_brain_scheduler", "stack_templates", "objective_readiness", "accounts_billing", "auth_policy", "durable_ledgers"}
    if status["checks"].get("storage", {}).get("backend") in {"supabase", "dual"}:
        readiness_keys.add("storage")
    return {
        "ready": status["ready"],
        "status": "ready" if status["ready"] else "not_ready",
        "checks": {
            key: value
            for key, value in status["checks"].items()
            if key in readiness_keys
        },
    }


def prometheus_metrics() -> str:
    status = platform_status()
    runtime = status["checks"].get("runtime", {})
    state = status["state"]
    stack_templates = status["checks"].get("stack_templates", {})
    auth_policy = status["checks"].get("auth_policy", {})
    objective_readiness = status["checks"].get("objective_readiness", {})
    alerts = {key: state.get(key, 0) for key in ("alerts_total", "alerts_open", "alerts_critical", "alerts_warning")}
    lines = [
        "# HELP astra_ready Whether Astra is ready to serve stack runs.",
        "# TYPE astra_ready gauge",
        f"astra_ready {1 if status['ready'] else 0}",
        "# HELP astra_uptime_seconds Backend process uptime.",
        "# TYPE astra_uptime_seconds gauge",
        f"astra_uptime_seconds {status['uptime_seconds']}",
        "# HELP astra_sessions_active Active in-memory sessions.",
        "# TYPE astra_sessions_active gauge",
        f"astra_sessions_active {state['sessions_active']}",
        "# HELP astra_events_buffered Buffered event count.",
        "# TYPE astra_events_buffered gauge",
        f"astra_events_buffered {state['events_buffered']}",
        "# HELP astra_workflow_snapshots Persisted workflow snapshots.",
        "# TYPE astra_workflow_snapshots gauge",
        f"astra_workflow_snapshots {state['workflow_snapshots']}",
        "# HELP astra_approval_ledgers Persisted approval ledgers.",
        "# TYPE astra_approval_ledgers gauge",
        f"astra_approval_ledgers {state['approval_ledgers']}",
        "# HELP astra_company_brains Persisted company brain stores.",
        "# TYPE astra_company_brains gauge",
        f"astra_company_brains {state['company_brains']}",
        "# HELP astra_stack_templates_ready Production-depth stack templates passing quality audit.",
        "# TYPE astra_stack_templates_ready gauge",
        f"astra_stack_templates_ready {stack_templates.get('ready_templates', 0)}",
        "# HELP astra_stack_template_quality_min Minimum stack template quality audit score.",
        "# TYPE astra_stack_template_quality_min gauge",
        f"astra_stack_template_quality_min {stack_templates.get('min_score', 0)}",
        "# HELP astra_auth_policy_ready Authentication and platform admin policy is production-ready.",
        "# TYPE astra_auth_policy_ready gauge",
        f"astra_auth_policy_ready {1 if auth_policy.get('ok') else 0}",
        "# HELP astra_objective_readiness_ready Agent Stack Platform objective contract is implemented.",
        "# TYPE astra_objective_readiness_ready gauge",
        f"astra_objective_readiness_ready {1 if objective_readiness.get('ok') else 0}",
        "# HELP astra_runs_total Durable run ledger entries.",
        "# TYPE astra_runs_total gauge",
        f"astra_runs_total {state.get('runs_total', 0)}",
        "# HELP astra_runs_error Durable run ledger error entries.",
        "# TYPE astra_runs_error gauge",
        f"astra_runs_error {state.get('runs_error', 0)}",
        "# HELP astra_connector_sources_error Connector sources with latest error status.",
        "# TYPE astra_connector_sources_error gauge",
        f"astra_connector_sources_error {state.get('connector_sources_error', 0)}",
        "# HELP astra_connector_webhook_events Durable connector webhook events recorded.",
        "# TYPE astra_connector_webhook_events gauge",
        f"astra_connector_webhook_events {state.get('connector_webhook_events', 0)}",
        "# HELP astra_alerts_open Open production alerts.",
        "# TYPE astra_alerts_open gauge",
        f"astra_alerts_open {alerts.get('alerts_open', 0)}",
        "# HELP astra_alerts_critical Open critical production alerts.",
        "# TYPE astra_alerts_critical gauge",
        f"astra_alerts_critical {alerts.get('alerts_critical', 0)}",
        "# HELP astra_process_rss_mb Backend RSS memory in MB.",
        "# TYPE astra_process_rss_mb gauge",
        f"astra_process_rss_mb {runtime.get('process_rss_mb', 0)}",
        "# HELP astra_disk_percent Root disk usage percent.",
        "# TYPE astra_disk_percent gauge",
        f"astra_disk_percent {runtime.get('disk_percent', 0)}",
    ]
    for name, check in status["checks"].items():
        lines.extend([
            f"# HELP astra_check_ok Check status for {name}.",
            f"# TYPE astra_check_ok gauge",
            f"astra_check_ok{{check=\"{name}\"}} {1 if check.get('ok') else 0}",
        ])
    try:
        from backend.runtime.metrics import prometheus_lines
        lines.extend(prometheus_lines())
    except Exception:
        pass
    return "\n".join(lines) + "\n"

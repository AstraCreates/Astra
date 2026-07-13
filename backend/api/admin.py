"""Admin monitoring endpoints — /admin/*"""
import asyncio
import collections
import os
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from backend.core.events import _sessions, _completed, _event_log, _event_counters, _steer
from backend.tenant_auth import require_platform_admin


def require_admin_actor(request: Request) -> str:
    return require_platform_admin(request)


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_actor)])

_START_TIME = time.time()

# In-process request counter: {endpoint: count}
_request_counts: dict[str, int] = collections.defaultdict(int)
# Rolling event-rate samples: list of (unix_ts, total_event_count)
_event_rate_samples: list[tuple[float, int]] = []


def _uptime_str(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _uptime() -> str:
    return _uptime_str(int(time.time() - _START_TIME))


def _total_events() -> int:
    return sum(len(v) for v in _event_log.values())


# ──────────────────────────────────────────────
# Index
# ──────────────────────────────────────────────

@router.get("/")
async def index():
    _request_counts["/admin/"] += 1
    return {
        "endpoints": [
            "/admin/health",
            "/admin/overview",
            "/admin/system",
            "/admin/system/processes",
            "/admin/system/network",
            "/admin/system/disk",
            "/admin/sessions",
            "/admin/sessions/{id}/events",
            "/admin/sessions/{id}/timeline",
            "/admin/agents",
            "/admin/errors",
            "/admin/founders",
            "/admin/redis",
            "/admin/asyncio",
            "/admin/requests",
            "/admin/env",
            "/admin/git",
            "/admin/logs",
            "/admin/platform",
            "/admin/objective",
            "/admin/objective/evidence",
            "/admin/stack-catalog-proof",
            "/admin/deploy-evidence",
            "/admin/production-bootstrap",
            "/admin/production-preflight",
            "/admin/production-requirements",
            "/admin/launch-readiness",
            "/admin/production-verification",
            "/admin/production-launch",
            "/admin/production-launch/reports/{proof_id}",
            "/admin/production-verification/reports",
            "/admin/alerts",
            "/admin/smoke",
            "/admin/control-plane/rollout",
        ]
    }


class RolloutCampaignStartRequest(BaseModel):
    feature: str
    stage: str = "internal_fixture"
    required_sample_size: int | None = None
    observation_hours: int = 24
    metadata: dict[str, Any] = Field(default_factory=dict)


class RolloutEvidenceRequest(BaseModel):
    campaign_id: str
    kind: str
    stage: str
    passed: bool = False
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class RolloutEvaluationRequest(BaseModel):
    feature: str
    baseline_completion_rate: float = 0.95
    baseline_p95_latency_ms: float = 1000.0


class RolloutAutomationRequest(BaseModel):
    feature: str
    baseline_completion_rate: float = 0.95
    baseline_p95_latency_ms: float = 1000.0


class RolloutRollbackRequest(BaseModel):
    feature: str
    reason: str = ""


class LegacyRetirementRequest(BaseModel):
    feature: str
    temporal_run_count: int
    clean_days: int
    restart_chaos_passed: bool
    parity_discrepancies_open: int
    rollback_drill_passed: bool
    archival_snapshots_exported: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Health / Overview
# ──────────────────────────────────────────────

@router.get("/health")
async def health():
    _request_counts["/admin/health"] += 1
    from backend.platform_status import platform_status
    return {**platform_status(), "admin_uptime": _uptime(), "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/platform")
async def platform():
    """Production readiness snapshot for the Agent Stack Platform."""
    _request_counts["/admin/platform"] += 1
    from backend.platform_status import platform_status
    return platform_status()


@router.get("/control-plane/rollout")
async def control_plane_rollout():
    _request_counts["/admin/control-plane/rollout"] += 1
    from backend.control_plane.wave7_rollout import rollout_status_snapshot

    return rollout_status_snapshot()


@router.post("/control-plane/rollout/campaigns")
async def start_control_plane_rollout_campaign(body: RolloutCampaignStartRequest):
    _request_counts["/admin/control-plane/rollout/campaigns"] += 1
    from backend.control_plane.wave7_rollout import start_rollout_campaign

    return start_rollout_campaign(
        feature=body.feature,
        stage=body.stage,  # type: ignore[arg-type]
        required_sample_size=body.required_sample_size,
        observation_hours=body.observation_hours,
        metadata=body.metadata,
    )


@router.post("/control-plane/rollout/evidence")
async def record_control_plane_rollout_evidence(body: RolloutEvidenceRequest):
    _request_counts["/admin/control-plane/rollout/evidence"] += 1
    from backend.control_plane.wave7_rollout import record_rollout_evidence

    return record_rollout_evidence(
        campaign_id=body.campaign_id,
        kind=body.kind,
        stage=body.stage,  # type: ignore[arg-type]
        passed=body.passed,
        summary=body.summary,
        metrics=body.metrics,
        run_id=body.run_id,
    )


@router.post("/control-plane/rollout/evaluate")
async def evaluate_control_plane_rollout(body: RolloutEvaluationRequest):
    _request_counts["/admin/control-plane/rollout/evaluate"] += 1
    from backend.control_plane.wave7_rollout import evaluate_rollout_campaign

    return evaluate_rollout_campaign(
        feature=body.feature,
        baseline_completion_rate=body.baseline_completion_rate,
        baseline_p95_latency_ms=body.baseline_p95_latency_ms,
    )


@router.post("/control-plane/rollout/tick")
async def run_control_plane_rollout_tick(body: RolloutAutomationRequest):
    _request_counts["/admin/control-plane/rollout/tick"] += 1
    from backend.control_plane.wave7_automation import run_rollout_automation_tick

    return run_rollout_automation_tick(
        feature=body.feature,
        baseline_completion_rate=body.baseline_completion_rate,
        baseline_p95_latency_ms=body.baseline_p95_latency_ms,
    )


@router.post("/control-plane/rollout/drills")
async def run_control_plane_rollout_drills(body: RolloutAutomationRequest):
    _request_counts["/admin/control-plane/rollout/drills"] += 1
    from backend.control_plane.wave7_automation import run_canary_halt_drills

    return run_canary_halt_drills(
        feature=body.feature,
        baseline_completion_rate=body.baseline_completion_rate,
        baseline_p95_latency_ms=body.baseline_p95_latency_ms,
    )


@router.post("/control-plane/rollout/rollback")
async def rollback_control_plane_rollout(body: RolloutRollbackRequest):
    _request_counts["/admin/control-plane/rollout/rollback"] += 1
    from backend.control_plane.wave7_rollout import mark_rollout_rolled_back

    return mark_rollout_rolled_back(feature=body.feature, reason=body.reason)


@router.post("/control-plane/legacy-retirement")
async def evaluate_control_plane_legacy_retirement(body: LegacyRetirementRequest):
    _request_counts["/admin/control-plane/legacy-retirement"] += 1
    from backend.control_plane.wave7_rollout import evaluate_legacy_retirement

    return evaluate_legacy_retirement(
        feature=body.feature,
        temporal_run_count=body.temporal_run_count,
        clean_days=body.clean_days,
        restart_chaos_passed=body.restart_chaos_passed,
        parity_discrepancies_open=body.parity_discrepancies_open,
        rollback_drill_passed=body.rollback_drill_passed,
        archival_snapshots_exported=body.archival_snapshots_exported,
        metadata=body.metadata,
    )


@router.get("/control-plane/legacy-retirement/manifest")
async def control_plane_legacy_retirement_manifest():
    _request_counts["/admin/control-plane/legacy-retirement/manifest"] += 1
    from backend.control_plane.wave7_archival import build_legacy_retirement_manifest

    return build_legacy_retirement_manifest()


@router.post("/control-plane/archive-snapshot")
async def control_plane_archive_snapshot(output_path: str = ""):
    _request_counts["/admin/control-plane/archive-snapshot"] += 1
    from backend.control_plane.wave7_archival import export_wave7_archival_snapshot

    return export_wave7_archival_snapshot(output_path=output_path or None)


@router.get("/control-plane/readiness")
async def control_plane_wave7_readiness():
    _request_counts["/admin/control-plane/readiness"] += 1
    from backend.control_plane.wave7_readiness import build_wave7_readiness_report

    return build_wave7_readiness_report()


@router.get("/objective")
async def objective():
    """Objective-level readiness audit for the Agent Stack Platform promise."""
    _request_counts["/admin/objective"] += 1
    from backend.objective_readiness import build_objective_readiness
    return build_objective_readiness()


@router.get("/objective/evidence")
async def objective_evidence(
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
):
    """Requirement-by-requirement evidence matrix for the Agent Stack Platform promise."""
    _request_counts["/admin/objective/evidence"] += 1
    from backend.objective_readiness import build_objective_evidence_matrix
    return build_objective_evidence_matrix(founder_id=founder_id, stack_id=stack_id, base_url=base_url)


@router.get("/stack-catalog-proof")
async def stack_catalog_proof():
    """Catalog-level proof that every promised Agent Stack compiles for execution."""
    _request_counts["/admin/stack-catalog-proof"] += 1
    from backend.stack_catalog_proof import build_stack_catalog_proof
    return build_stack_catalog_proof()


@router.get("/deploy-evidence")
async def deploy_evidence(
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    live_connectors: bool = False,
    base_url: str = "",
    strict: bool = True,
):
    """Show exact missing production deploy proof for the selected stack."""
    _request_counts["/admin/deploy-evidence"] += 1
    from backend.deploy_evidence import build_deploy_evidence
    return build_deploy_evidence(
        founder_id=founder_id,
        stack_id=stack_id,
        live_connectors=live_connectors,
        base_url=base_url,
        strict=strict,
    )


@router.get("/production-requirements")
async def production_requirements(
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
):
    """Show production env, connector, and final-gate requirements."""
    _request_counts["/admin/production-requirements"] += 1
    from backend.production_requirements import build_production_requirements
    return build_production_requirements(founder_id=founder_id, stack_id=stack_id, base_url=base_url)


@router.get("/production-bootstrap")
async def production_bootstrap(
    founder_id: str,
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
    expected_backend_ip: str = "",
):
    """Show exact production bootstrap steps before final launch proof."""
    _request_counts["/admin/production-bootstrap"] += 1
    from backend.production_bootstrap import build_production_bootstrap
    return build_production_bootstrap(
        founder_id=founder_id,
        stack_id=stack_id,
        base_url=base_url,
        expected_backend_ip=expected_backend_ip,
    )


@router.get("/production-preflight")
async def production_preflight(
    base_url: str,
    expected_backend_ip: str = "",
):
    """Verify DNS and public HTTP surfaces before final launch proof."""
    _request_counts["/admin/production-preflight"] += 1
    from backend.production_preflight import build_production_preflight
    return build_production_preflight(base_url=base_url, expected_backend_ip=expected_backend_ip)


@router.get("/launch-readiness")
async def launch_readiness(
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
    report_id: str = "latest",
):
    """Single pass/fail launch audit across requirements, objective proof, report, manifest, and bundle."""
    _request_counts["/admin/launch-readiness"] += 1
    from backend.launch_readiness import build_launch_readiness
    return build_launch_readiness(founder_id=founder_id, stack_id=stack_id, base_url=base_url, report_id=report_id)


@router.get("/alerts")
async def alerts(limit: int = 50, status: str = ""):
    """Durable production alert ledger."""
    _request_counts["/admin/alerts"] += 1
    from backend.alerts import list_alerts
    return list_alerts(limit=limit, status=status)


@router.post("/alerts/check")
async def alert_check(deliver: bool = True):
    """Evaluate platform state and deliver configured operations alerts."""
    _request_counts["/admin/alerts/check"] += 1
    from backend.alerts import run_alert_check
    return run_alert_check(deliver=deliver)


@router.get("/smoke")
async def smoke(
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    live_connectors: bool = False,
    base_url: str = "",
    strict: bool = False,
    save: bool = True,
):
    """Run the production smoke verifier from the admin surface."""
    _request_counts["/admin/smoke"] += 1
    from backend.production_smoke import run_production_smoke
    return run_production_smoke(
        founder_id=founder_id,
        stack_id=stack_id,
        live_connectors=live_connectors,
        base_url=base_url,
        strict=strict,
        save=save,
    )


@router.get("/smoke/reports")
async def smoke_reports(limit: int = 20):
    """List persisted production smoke reports."""
    _request_counts["/admin/smoke/reports"] += 1
    from backend.production_smoke import list_smoke_reports
    return list_smoke_reports(limit=limit)


@router.post("/production-verification")
async def production_verification(
    founder_id: str,
    base_url: str,
    stack_id: str = "idea_to_revenue",
    live_connectors: bool = True,
    save: bool = True,
):
    """Run the final production launch gate and persist operator reports."""
    _request_counts["/admin/production-verification"] += 1
    from backend.production_verify import run_production_verification
    return run_production_verification(
        founder_id=founder_id,
        stack_id=stack_id,
        base_url=base_url,
        live_connectors=live_connectors,
        save=save,
    )


@router.post("/production-launch")
async def production_launch(
    founder_id: str,
    base_url: str,
    stack_id: str = "idea_to_revenue",
    live_connectors: bool = True,
    seed_env_connectors: bool = False,
):
    """Run the complete final production launch proof sequence."""
    _request_counts["/admin/production-launch"] += 1
    from backend.production_launch import run_final_launch_proof
    return run_final_launch_proof(
        founder_id=founder_id,
        stack_id=stack_id,
        base_url=base_url,
        live_connectors=live_connectors,
        seed_env_connectors=seed_env_connectors,
    )


@router.get("/production-launch/reports/{proof_id}")
async def production_launch_report(proof_id: str):
    """Fetch one persisted aggregate final production launch proof."""
    _request_counts["/admin/production-launch/reports/detail"] += 1
    from backend.production_launch import get_final_launch_proof
    proof = get_final_launch_proof(proof_id)
    if not proof.get("found"):
        raise HTTPException(status_code=404, detail=proof.get("error") or "Final launch proof not found.")
    return proof


@router.get("/production-launch/reports/{proof_id}/manifest")
async def production_launch_report_manifest(proof_id: str):
    """Fetch one persisted aggregate final production launch proof checksum manifest."""
    _request_counts["/admin/production-launch/reports/manifest"] += 1
    from backend.production_launch import get_final_launch_proof_manifest
    manifest = get_final_launch_proof_manifest(proof_id)
    if not manifest.get("found"):
        raise HTTPException(status_code=404, detail=manifest.get("error") or "Final launch proof checksum manifest not found.")
    return manifest


@router.get("/production-launch/reports/{proof_id}/manifest/verify")
async def production_launch_report_manifest_verify(proof_id: str):
    """Verify one aggregate final production launch proof checksum manifest."""
    _request_counts["/admin/production-launch/reports/manifest/verify"] += 1
    from backend.production_launch import verify_final_launch_proof_manifest
    result = verify_final_launch_proof_manifest(proof_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Final launch proof checksum manifest not found.")
    return result


@router.get("/production-verification/reports")
async def production_verification_reports(limit: int = 20):
    """List persisted final production verification reports."""
    _request_counts["/admin/production-verification/reports"] += 1
    from backend.production_verify import list_production_verification_reports
    return list_production_verification_reports(limit=limit)


@router.get("/production-verification/reports/{report_id}")
async def production_verification_report(report_id: str):
    """Fetch one persisted final production verification report."""
    _request_counts["/admin/production-verification/reports/detail"] += 1
    from backend.production_verify import get_production_verification_report
    report = get_production_verification_report(report_id)
    if not report.get("found"):
        raise HTTPException(status_code=404, detail=report.get("error") or "Production verification report not found.")
    return report


@router.get("/production-verification/reports/{report_id}/markdown", response_class=PlainTextResponse)
async def production_verification_report_markdown(report_id: str):
    """Fetch one persisted final production verification report as Markdown."""
    _request_counts["/admin/production-verification/reports/markdown"] += 1
    from backend.production_verify import get_production_verification_markdown
    report = get_production_verification_markdown(report_id)
    if not report.get("found"):
        raise HTTPException(status_code=404, detail=report.get("error") or "Production verification Markdown report not found.")
    return PlainTextResponse(str(report.get("markdown") or ""), media_type="text/markdown")


@router.get("/production-verification/reports/{report_id}/manifest")
async def production_verification_report_manifest(report_id: str):
    """Fetch one persisted production verification checksum manifest."""
    _request_counts["/admin/production-verification/reports/manifest"] += 1
    from backend.production_verify import get_production_verification_manifest
    report = get_production_verification_manifest(report_id)
    if not report.get("found"):
        raise HTTPException(status_code=404, detail=report.get("error") or "Production verification checksum manifest not found.")
    return report


@router.get("/production-verification/reports/{report_id}/manifest/verify")
async def production_verification_report_manifest_verify(report_id: str):
    """Verify persisted production evidence files against their checksum manifest."""
    _request_counts["/admin/production-verification/reports/manifest/verify"] += 1
    from backend.production_verify import verify_production_verification_manifest
    report = verify_production_verification_manifest(report_id)
    if not report.get("found"):
        raise HTTPException(status_code=404, detail=report.get("error") or "Production verification checksum manifest not found.")
    return report


@router.get("/production-verification/reports/{report_id}/bundle")
async def production_verification_report_bundle(report_id: str):
    """Export the production verification report, Markdown proof, and checksums as one ZIP."""
    _request_counts["/admin/production-verification/reports/bundle"] += 1
    from backend.production_verify import export_production_verification_bundle
    bundle = export_production_verification_bundle(report_id)
    if not bundle.get("found"):
        raise HTTPException(status_code=404, detail=bundle.get("error") or "Production verification bundle not found.")
    return FileResponse(
        str(bundle["path"]),
        media_type="application/zip",
        filename=str(bundle["filename"]),
    )


@router.get("/overview")
async def overview():
    """Single-page dashboard summary — everything at a glance."""
    _request_counts["/admin/overview"] += 1

    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    disk = psutil.disk_usage("/")
    proc = psutil.Process()

    active_sessions = [s for s in _sessions if s not in _completed]
    total_events = _total_events()

    # Aggregate agent stats
    agent_runs: dict[str, int] = collections.defaultdict(int)
    agent_errors: dict[str, int] = collections.defaultdict(int)
    total_errors = 0
    total_agent_starts = 0
    founders: set[str] = set()

    for sid, log in _event_log.items():
        for _, ev in log:
            t = ev.get("type", "")
            a = ev.get("agent", "")
            if t == "goal_start":
                fid = ev.get("founder_id")
                if fid:
                    founders.add(fid)
            if t == "agent_start":
                agent_runs[a] += 1
                total_agent_starts += 1
            if t == "agent_error":
                agent_errors[a] += 1
                total_errors += 1

    top_agents = sorted(agent_runs.items(), key=lambda x: -x[1])[:5]
    error_agents = sorted(agent_errors.items(), key=lambda x: -x[1])[:5]

    return {
        "uptime": _uptime(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "system": {
            "cpu_percent": cpu,
            "mem_percent": mem.percent,
            "mem_used_gb": round(mem.used / 1e9, 2),
            "mem_total_gb": round(mem.total / 1e9, 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1e9, 2),
            "load_avg": [round(x, 2) for x in os.getloadavg()],
            "process_rss_mb": round(proc.memory_info().rss / 1e6, 2),
        },
        "sessions": {
            "total": len(_sessions),
            "active": len(active_sessions),
            "completed": len(_completed),
            "active_ids": active_sessions,
        },
        "agents": {
            "total_runs": total_agent_starts,
            "total_errors": total_errors,
            "error_rate_pct": round(total_errors / total_agent_starts * 100, 1) if total_agent_starts else 0,
            "top_5": [{"agent": a, "runs": n} for a, n in top_agents],
            "error_leaders": [{"agent": a, "errors": n} for a, n in error_agents],
        },
        "founders": {
            "unique": len(founders),
        },
        "events": {
            "total": total_events,
        },
    }


# ──────────────────────────────────────────────
# System
# ──────────────────────────────────────────────

@router.get("/system")
async def system_info():
    _request_counts["/admin/system"] += 1
    cpu_per_core = psutil.cpu_percent(interval=0.5, percpu=True)
    cpu_times = psutil.cpu_times()
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    disk_io = psutil.disk_io_counters()
    net = psutil.net_io_counters()
    boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc).isoformat()
    freq = psutil.cpu_freq()

    proc = psutil.Process()
    with proc.oneshot():
        proc_mem = proc.memory_info()
        proc_cpu = proc.cpu_percent(interval=0.1)
        proc_threads = proc.num_threads()
        proc_fds = proc.num_fds() if hasattr(proc, "num_fds") else None
        try:
            proc_conns = len(proc.net_connections())
        except Exception:
            proc_conns = None
        proc_children = len(proc.children(recursive=True))

    # temp sensors (may not be available in containers)
    temps: dict[str, Any] = {}
    try:
        raw = psutil.sensors_temperatures()
        for name, entries in raw.items():
            temps[name] = [{"label": e.label, "current": e.current, "high": e.high, "critical": e.critical} for e in entries]
    except Exception:
        pass

    return {
        "host": "redacted",
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "uptime": _uptime(),
        "boot_time": boot,
        "cpu": {
            "percent_total": sum(cpu_per_core) / len(cpu_per_core),
            "percent_per_core": cpu_per_core,
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "freq_current_mhz": round(freq.current, 1) if freq else None,
            "freq_max_mhz": round(freq.max, 1) if freq else None,
            "times": {
                "user": round(cpu_times.user, 2),
                "system": round(cpu_times.system, 2),
                "idle": round(cpu_times.idle, 2),
                "iowait": round(getattr(cpu_times, "iowait", 0), 2),
                "steal": round(getattr(cpu_times, "steal", 0), 2),
            },
            "load_avg_1m": round(os.getloadavg()[0], 2),
            "load_avg_5m": round(os.getloadavg()[1], 2),
            "load_avg_15m": round(os.getloadavg()[2], 2),
        },
        "memory": {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb": round(mem.used / 1e9, 2),
            "available_gb": round(mem.available / 1e9, 2),
            "cached_gb": round(getattr(mem, "cached", 0) / 1e9, 2),
            "buffers_gb": round(getattr(mem, "buffers", 0) / 1e9, 2),
            "percent": mem.percent,
            "swap_total_gb": round(swap.total / 1e9, 2),
            "swap_used_gb": round(swap.used / 1e9, 2),
            "swap_percent": swap.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb": round(disk.used / 1e9, 2),
            "free_gb": round(disk.free / 1e9, 2),
            "percent": disk.percent,
            "io_read_mb": round(disk_io.read_bytes / 1e6, 2) if disk_io else None,
            "io_write_mb": round(disk_io.write_bytes / 1e6, 2) if disk_io else None,
            "io_read_count": disk_io.read_count if disk_io else None,
            "io_write_count": disk_io.write_count if disk_io else None,
        },
        "network": {
            "bytes_sent_mb": round(net.bytes_sent / 1e6, 2),
            "bytes_recv_mb": round(net.bytes_recv / 1e6, 2),
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
            "errin": net.errin,
            "errout": net.errout,
            "dropin": net.dropin,
            "dropout": net.dropout,
        },
        "process": {
            "pid": os.getpid(),
            "rss_mb": round(proc_mem.rss / 1e6, 2),
            "vms_mb": round(proc_mem.vms / 1e6, 2),
            "shared_mb": round(getattr(proc_mem, "shared", 0) / 1e6, 2),
            "cpu_percent": proc_cpu,
            "threads": proc_threads,
            "open_fds": proc_fds,
            "open_connections": proc_conns,
            "child_processes": proc_children,
        },
        "temperatures": temps,
    }


@router.get("/system/processes")
async def top_processes(limit: int = 20, sort_by: str = "cpu"):
    """Top processes by CPU or memory."""
    _request_counts["/admin/system/processes"] += 1
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status", "username", "cmdline", "create_time"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"],
                "status": info["status"],
                "username": info["username"],
                "cpu_percent": info["cpu_percent"] or 0,
                "rss_mb": round((info["memory_info"].rss if info["memory_info"] else 0) / 1e6, 2),
                "cmd": " ".join(info["cmdline"] or [])[:120],
                "age_s": int(time.time() - info["create_time"]) if info["create_time"] else None,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    key = "rss_mb" if sort_by == "mem" else "cpu_percent"
    procs.sort(key=lambda x: -x[key])
    return {"count": len(procs), "sort_by": sort_by, "processes": procs[:limit]}


@router.get("/system/network")
async def network_interfaces():
    """Per-interface network stats and active connections."""
    _request_counts["/admin/system/network"] += 1
    ifaces = {}
    per_iface = psutil.net_io_counters(pernic=True)
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for name, counters in per_iface.items():
        ifaces[name] = {
            "bytes_sent_mb": round(counters.bytes_sent / 1e6, 2),
            "bytes_recv_mb": round(counters.bytes_recv / 1e6, 2),
            "packets_sent": counters.packets_sent,
            "packets_recv": counters.packets_recv,
            "errin": counters.errin,
            "errout": counters.errout,
            "speed_mbps": stats[name].speed if name in stats else None,
            "is_up": stats[name].isup if name in stats else None,
            "addresses": [{"family": str(a.family)} for a in addrs.get(name, [])],
        }

    # Active connections summary
    try:
        conns = psutil.net_connections(kind="inet")
        conn_states: dict[str, int] = collections.defaultdict(int)
        for c in conns:
            conn_states[c.status] += 1
        connections = {"total": len(conns), "by_state": dict(conn_states)}
    except Exception:
        connections = {"total": None, "by_state": {}}

    return {"interfaces": ifaces, "connections": connections}


@router.get("/system/disk")
async def disk_detail():
    """All mounted partitions."""
    _request_counts["/admin/system/disk"] += 1
    parts = []
    for p in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(p.mountpoint)
            parts.append({
                "device": p.device,
                "mountpoint": p.mountpoint,
                "fstype": p.fstype,
                "total_gb": round(usage.total / 1e9, 2),
                "used_gb": round(usage.used / 1e9, 2),
                "free_gb": round(usage.free / 1e9, 2),
                "percent": usage.percent,
            })
        except Exception:
            pass
    return {"partitions": parts}


# ──────────────────────────────────────────────
# Sessions
# ──────────────────────────────────────────────

def _parse_session(sid: str) -> dict:
    log = _event_log.get(sid, [])
    goal = None
    founder_id = None
    agents_seen: dict[str, str] = {}  # agent -> last status
    errors: list[str] = []
    started_at_ts: float | None = None
    ended_at_ts: float | None = None
    plan_nodes: list = []
    tool_calls = 0

    for _, ev in log:
        t = ev.get("type", "")
        if t == "goal_start":
            goal = ev.get("goal", "")[:160]
            founder_id = ev.get("founder_id")
            started_at_ts = ev.get("ts_unix") or time.time()
        if t == "goal_done":
            ended_at_ts = ev.get("ts_unix") or time.time()
        a = ev.get("agent")
        if a:
            if t == "agent_start":
                agents_seen[a] = "running"
            elif t == "agent_done":
                agents_seen[a] = "done"
            elif t == "agent_error":
                agents_seen[a] = "error"
                errors.append(f"{a}: {ev.get('error', '')[:200]}")
        if t == "tool_call":
            tool_calls += 1
        if t == "detailed_plan" and "nodes" in ev:
            plan_nodes = ev["nodes"]

    duration = None
    if started_at_ts and ended_at_ts:
        duration = round(ended_at_ts - started_at_ts, 1)

    return {
        "session_id": sid,
        "status": "completed" if sid in _completed else "running",
        "goal": goal,
        "founder_id": founder_id,
        "agents": agents_seen,
        "agent_count": len(agents_seen),
        "event_count": len(log),
        "tool_calls": tool_calls,
        "errors": errors,
        "error_count": len(errors),
        "queue_depth": _sessions[sid].qsize() if sid in _sessions else 0,
        "steer_messages": len(_steer.get(sid, [])),
        "plan_nodes": len(plan_nodes),
        "duration_s": duration,
    }


@router.get("/sessions")
async def sessions_overview():
    _request_counts["/admin/sessions"] += 1
    rows = [_parse_session(sid) for sid in list(_sessions.keys())]
    rows.sort(key=lambda r: (r["status"] == "completed", r["session_id"]))
    active = sum(1 for r in rows if r["status"] == "running")
    return {
        "total": len(rows),
        "active": active,
        "completed": len(rows) - active,
        "sessions": rows,
    }


@router.get("/runs")
async def runs_ledger(limit: int = 50, founder_id: str = "", status: str = ""):
    """Restart-safe run ledger summary."""
    _request_counts["/admin/runs"] += 1
    from backend.run_ledger import ledger_metrics, list_runs
    return {
        "metrics": ledger_metrics(),
        "runs": list_runs(limit=limit, founder_id=founder_id, status=status),
    }


@router.get("/runs/{session_id}")
async def run_ledger_detail(session_id: str):
    """One restart-safe run ledger record."""
    _request_counts["/admin/runs/detail"] += 1
    from backend.run_ledger import get_run
    run = get_run(session_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, limit: int = 500, event_type: str = ""):
    _request_counts["/admin/sessions/events"] += 1
    log = _event_log.get(session_id)
    if log is None:
        raise HTTPException(status_code=404, detail="session not found")
    filtered = [(eid, ev) for eid, ev in log if not event_type or ev.get("type") == event_type]
    tail = filtered[-limit:]
    events = [{"id": eid, **ev} for eid, ev in tail]
    types = collections.Counter(ev.get("type") for _, ev in log)
    return {
        "session_id": session_id,
        "status": "completed" if session_id in _completed else "running",
        "total_events": len(log),
        "returned": len(events),
        "event_types": dict(types.most_common()),
        "events": events,
    }


@router.get("/sessions/{session_id}/timeline")
async def session_timeline(session_id: str):
    """Agent-level timeline: when each agent started/ended and how long it took."""
    _request_counts["/admin/sessions/timeline"] += 1
    log = _event_log.get(session_id)
    if log is None:
        raise HTTPException(status_code=404, detail="session not found")

    agent_times: dict[str, dict] = {}
    goal_start = None
    goal_end = None

    for _, ev in log:
        t = ev.get("type", "")
        ts = ev.get("ts_unix", time.time())
        a = ev.get("agent")

        if t == "goal_start":
            goal_start = ts
        if t == "goal_done":
            goal_end = ts
        if not a:
            continue
        if a not in agent_times:
            agent_times[a] = {"agent": a, "started": None, "ended": None, "status": "waiting", "error": None}
        at = agent_times[a]
        if t == "agent_start":
            at["started"] = ts
            at["status"] = "running"
        elif t == "agent_done":
            at["ended"] = ts
            at["status"] = "done"
        elif t == "agent_error":
            at["ended"] = ts
            at["status"] = "error"
            at["error"] = ev.get("error", "")[:200]

    timeline = []
    for at in agent_times.values():
        duration = None
        if at["started"] and at["ended"]:
            duration = round(at["ended"] - at["started"], 1)
        timeline.append({**at, "duration_s": duration})
    timeline.sort(key=lambda x: x["started"] or 0)

    total_duration = None
    if goal_start and goal_end:
        total_duration = round(goal_end - goal_start, 1)

    return {
        "session_id": session_id,
        "total_duration_s": total_duration,
        "agents": timeline,
    }


# ──────────────────────────────────────────────
# Agents
# ──────────────────────────────────────────────

@router.get("/agents")
async def agents_activity():
    _request_counts["/admin/agents"] += 1
    agent_stats: dict[str, dict] = {}

    for sid, log in _event_log.items():
        for _, ev in log:
            agent = ev.get("agent")
            if not agent:
                continue
            if agent not in agent_stats:
                agent_stats[agent] = {
                    "agent": agent,
                    "runs": 0,
                    "completions": 0,
                    "errors": 0,
                    "sessions": set(),
                    "total_duration_s": 0.0,
                    "last_status": None,
                    "last_error": None,
                    "_start_ts": {},
                }
            s = agent_stats[agent]
            t = ev.get("type", "")
            ts = ev.get("ts_unix", 0)
            s["sessions"].add(sid)

            if t == "agent_start":
                s["runs"] += 1
                s["_start_ts"][sid] = ts
                s["last_status"] = "running"
            elif t == "agent_done":
                s["completions"] += 1
                s["last_status"] = "done"
                if sid in s["_start_ts"] and ts:
                    s["total_duration_s"] += ts - s["_start_ts"].pop(sid, ts)
            elif t == "agent_error":
                s["errors"] += 1
                s["last_status"] = "error"
                s["last_error"] = ev.get("error", "")[:200]

    result = []
    for s in agent_stats.values():
        runs = s["runs"]
        comps = s["completions"]
        avg_dur = round(s["total_duration_s"] / comps, 1) if comps else None
        result.append({
            "agent": s["agent"],
            "runs": runs,
            "completions": comps,
            "errors": s["errors"],
            "success_rate_pct": round(comps / runs * 100, 1) if runs else None,
            "avg_duration_s": avg_dur,
            "session_count": len(s["sessions"]),
            "sessions": sorted(s["sessions"]),
            "last_status": s["last_status"],
            "last_error": s["last_error"],
        })
    result.sort(key=lambda x: -x["runs"])
    return {"total_agents": len(result), "agents": result}


# ──────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────

@router.get("/errors")
async def all_errors(limit: int = 100):
    """All agent errors across all sessions, newest first."""
    _request_counts["/admin/errors"] += 1
    errors = []
    for sid, log in _event_log.items():
        for eid, ev in log:
            if ev.get("type") == "agent_error":
                errors.append({
                    "session_id": sid,
                    "event_id": eid,
                    "agent": ev.get("agent"),
                    "task_id": ev.get("task_id"),
                    "error": ev.get("error", "")[:500],
                    "ts": ev.get("ts"),
                })
    errors.sort(key=lambda e: e["event_id"], reverse=True)
    return {
        "total_errors": len(errors),
        "returned": min(len(errors), limit),
        "errors": errors[:limit],
    }


# ──────────────────────────────────────────────
# Founders
# ──────────────────────────────────────────────

@router.get("/founders")
async def founders_stats():
    _request_counts["/admin/founders"] += 1
    founder_data: dict[str, dict] = {}

    for sid, log in _event_log.items():
        fid = None
        goal = None
        status = "completed" if sid in _completed else "running"
        agent_runs = 0
        errors = 0

        for _, ev in log:
            t = ev.get("type", "")
            if t == "goal_start":
                fid = ev.get("founder_id")
                goal = ev.get("goal", "")[:120]
            if t == "agent_start":
                agent_runs += 1
            if t == "agent_error":
                errors += 1

        if not fid:
            continue

        if fid not in founder_data:
            founder_data[fid] = {
                "founder_id": fid,
                "sessions": [],
                "total_agent_runs": 0,
                "total_errors": 0,
                "completed_sessions": 0,
                "active_sessions": 0,
            }
        fd = founder_data[fid]
        fd["sessions"].append({"session_id": sid, "goal": goal, "status": status})
        fd["total_agent_runs"] += agent_runs
        fd["total_errors"] += errors
        if status == "completed":
            fd["completed_sessions"] += 1
        else:
            fd["active_sessions"] += 1

    result = sorted(founder_data.values(), key=lambda x: -len(x["sessions"]))
    return {"unique_founders": len(result), "founders": result}


# ──────────────────────────────────────────────
# Redis
# ──────────────────────────────────────────────

@router.get("/redis")
async def redis_info():
    _request_counts["/admin/redis"] += 1
    try:
        import redis.asyncio as aioredis
        from backend.config import settings
        r = aioredis.from_url(settings.redis_url)
        info = await r.info("all")
        keyspace = await r.info("keyspace")
        dbsize = await r.dbsize()
        await r.aclose()
        return {
            "connected": True,
            "version": info.get("redis_version"),
            "mode": info.get("redis_mode"),
            "role": info.get("role"),
            "uptime_seconds": info.get("uptime_in_seconds"),
            "uptime_human": _uptime_str(info.get("uptime_in_seconds", 0)),
            "clients": {
                "connected": info.get("connected_clients"),
                "blocked": info.get("blocked_clients"),
                "tracking": info.get("tracking_clients"),
                "max": info.get("maxclients"),
            },
            "memory": {
                "used_mb": round(info.get("used_memory", 0) / 1e6, 2),
                "used_peak_mb": round(info.get("used_memory_peak", 0) / 1e6, 2),
                "used_rss_mb": round(info.get("used_memory_rss", 0) / 1e6, 2),
                "maxmemory_mb": round(info.get("maxmemory", 0) / 1e6, 2),
                "fragmentation_ratio": info.get("mem_fragmentation_ratio"),
            },
            "stats": {
                "total_commands_processed": info.get("total_commands_processed"),
                "total_connections_received": info.get("total_connections_received"),
                "rejected_connections": info.get("rejected_connections"),
                "keyspace_hits": info.get("keyspace_hits"),
                "keyspace_misses": info.get("keyspace_misses"),
                "hit_rate_pct": round(
                    info.get("keyspace_hits", 0) /
                    max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1), 1) * 100, 1
                ),
                "expired_keys": info.get("expired_keys"),
                "evicted_keys": info.get("evicted_keys"),
                "ops_per_sec": info.get("instantaneous_ops_per_sec"),
                "input_kbps": info.get("instantaneous_input_kbps"),
                "output_kbps": info.get("instantaneous_output_kbps"),
            },
            "persistence": {
                "rdb_last_save": info.get("rdb_last_bgsave_status"),
                "aof_enabled": info.get("aof_enabled"),
            },
            "keyspace": keyspace,
            "total_keys": dbsize,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ──────────────────────────────────────────────
# Asyncio tasks
# ──────────────────────────────────────────────

@router.get("/asyncio")
async def asyncio_stats():
    _request_counts["/admin/asyncio"] += 1
    loop = asyncio.get_event_loop()
    all_tasks = asyncio.all_tasks(loop)
    task_list = []
    for t in all_tasks:
        coro = t.get_coro()
        task_list.append({
            "name": t.get_name(),
            "done": t.done(),
            "cancelled": t.cancelled(),
            "coro": getattr(coro, "__qualname__", str(coro)),
        })
    task_list.sort(key=lambda x: x["name"])
    by_coro: dict[str, int] = collections.Counter(t["coro"] for t in task_list)
    return {
        "total_tasks": len(task_list),
        "running": sum(1 for t in task_list if not t["done"]),
        "top_coros": dict(by_coro.most_common(10)),
        "tasks": task_list,
    }


# ──────────────────────────────────────────────
# Request stats
# ──────────────────────────────────────────────

@router.get("/requests")
async def request_stats():
    """Hit counts for admin endpoints since last restart."""
    _request_counts["/admin/requests"] += 1
    total = sum(_request_counts.values())
    sorted_counts = dict(sorted(_request_counts.items(), key=lambda x: -x[1]))
    return {
        "total_admin_requests": total,
        "uptime": _uptime(),
        "per_endpoint": sorted_counts,
        "total_events_in_memory": _total_events(),
        "sessions_in_memory": len(_sessions),
    }


# ──────────────────────────────────────────────
# Env
# ──────────────────────────────────────────────

@router.get("/env")
async def env_check():
    _request_counts["/admin/env"] += 1
    keys = [
        "SUPABASE_URL", "SUPABASE_KEY", "REDIS_URL",
        "AGENT_MODEL_BASE_URL", "AGENT_MODEL_NAME", "AGENT_MODEL_API_KEY",
        "PLANNER_MODEL_BASE_URL", "PLANNER_MODEL_NAME", "PLANNER_MODEL_API_KEY",
        "VERCEL_TOKEN", "GITHUB_TOKEN",
        "CLOUDFLARE_API_TOKEN", "COMPOSIO_API_KEY",
        "CLERK_SECRET_KEY", "SENDGRID_API_KEY", "OBSIDIAN_VAULT",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    ]
    result = {}
    for k in keys:
        v = os.environ.get(k, "")
        if v:
            result[k] = f"{v[:6]}...{v[-4:]}" if len(v) > 10 else "***set***"
        else:
            result[k] = "NOT SET"
    return result


# ──────────────────────────────────────────────
# Git
# ──────────────────────────────────────────────

@router.get("/git")
async def git_status():
    _request_counts["/admin/git"] += 1

    def _run(cmd, cwd="/opt/astra"):
        for d in [cwd, ".", None]:
            try:
                kw = {"cwd": d} if d else {}
                return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, **kw).strip()
            except Exception:
                continue
        return None

    origin = _run(["git", "rev-parse", "origin/main"])
    head = _run(["git", "rev-parse", "HEAD"])
    behind = None
    if origin and head:
        try:
            behind = int(subprocess.check_output(
                ["git", "rev-list", "--count", f"HEAD..origin/main"],
                text=True, stderr=subprocess.DEVNULL, cwd="/opt/astra"
            ).strip())
        except Exception:
            pass

    return {
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": head,
        "commit_short": _run(["git", "rev-parse", "--short", "HEAD"]),
        "commit_message": _run(["git", "log", "-1", "--pretty=%s"]),
        "commit_date": _run(["git", "log", "-1", "--pretty=%ci"]),
        "origin_commit": origin,
        "commits_behind_origin": behind,
        "in_sync": head == origin if head and origin else None,
        "dirty": bool(_run(["git", "status", "--porcelain"])),
        "recent_commits": (_run(["git", "log", "--oneline", "-15"]) or "").splitlines(),
    }


# ──────────────────────────────────────────────
# Logs
# ──────────────────────────────────────────────

# Raw docker/journald/server.log output can contain secret values that were
# logged at startup or during request handling (OpenRouter/Composio/Stripe/
# Resend/etc. API keys — see backend/config.py Settings fields ending in
# _key/_token/_secret/_password). Redact known key shapes plus a generic
# "name=value" / "Authorization: Bearer ..." catch-all before this ever
# leaves the process, since /admin/logs returns it verbatim to the caller.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # OpenAI/OpenRouter-style keys, e.g. sk-or-v1-xxxxxxxx
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "sk-[REDACTED]"),
    # Resend keys, e.g. re_xxxxxxxx
    (re.compile(r"re_[A-Za-z0-9_-]{16,}"), "re_[REDACTED]"),
    # Stripe keys, e.g. sk_live_xxx / sk_test_xxx / rk_live_xxx / whsec_xxx
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"), "[REDACTED_STRIPE_KEY]"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{8,}"), "whsec_[REDACTED]"),
    # "Authorization: Bearer <token>" headers
    (
        re.compile(r"(?i)(authorization\s*:\s*bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
        r"\1 [REDACTED]",
    ),
    # Generic "<name containing key/token/secret/password>=<value>" or "...: <value>",
    # covers env-var dumps like OPENROUTER_API_KEY=... or AUTOMATION_TOKEN=...
    (
        re.compile(
            r"(?i)\b([a-z0-9_.\-]*(?:api[_-]?key|token|secret|password)[a-z0-9_.\-]*"
            r"\s*[:=]\s*)([\"']?)[^\s\"']{6,}\2"
        ),
        r"\1\2[REDACTED]\2",
    ),
]


def _redact_secrets(text: str) -> str:
    """Redact common secret-shaped substrings from log text before it is returned."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@router.get("/logs")
async def recent_logs(lines: int = 300, filter: str = ""):
    _request_counts["/admin/logs"] += 1
    raw_lines: list[str] = []
    source = "none"

    # Try Docker container logs first
    for container in ["astra-backend-1", "astra_backend_1"]:
        try:
            out = subprocess.check_output(
                ["docker", "logs", "--tail", str(lines), container],
                stderr=subprocess.STDOUT, text=True
            )
            raw_lines = out.strip().splitlines()
            source = f"docker:{container}"
            break
        except Exception:
            pass

    # Fall back to journald
    if not raw_lines:
        try:
            out = subprocess.check_output(
                ["journalctl", "-u", "astra*", "--no-pager", f"-n{lines}"],
                stderr=subprocess.DEVNULL, text=True
            )
            raw_lines = out.strip().splitlines()
            source = "journald"
        except Exception:
            pass

    # Fall back to server.log
    if not raw_lines:
        try:
            with open("server.log") as f:
                raw_lines = [l.rstrip() for l in f.readlines()[-lines:]]
            source = "server.log"
        except Exception:
            pass

    raw_lines = [_redact_secrets(l) for l in raw_lines]

    if filter:
        raw_lines = [l for l in raw_lines if filter.lower() in l.lower()]

    return {
        "source": source,
        "total_lines": len(raw_lines),
        "filter": filter or None,
        "lines": raw_lines[-lines:],
    }

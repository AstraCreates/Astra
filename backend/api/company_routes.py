"""Company API — company-scoped operations and dashboard."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.tenant_auth import require_founder_access, require_company_access, request_user_id
from backend.missions.company_goal import get_company_goal
from backend.genome.store import get_genome, get_conflicts
from backend.outcomes.store import weekly_rollup
from backend.missions.goal_engine import plan_next_goal
from backend.core.session_store import list_sessions, load_events
from backend.workboard import build_session_workboard
from backend.verification.receipt_store import list_receipts
from backend.verification.share_store import create_share, resolve_share
from backend.stacks import probe_live_url
from backend.monitoring.store import latest_status, uptime_percent, list_monitoring_checks

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/company/{company_id}/overview")
async def company_overview_route(
    company_id: str,
    request: Request = None,
) -> dict[str, Any]:
    """Get company command center overview: goals, outcomes, active run, next action."""
    try:
        founder_id = request_user_id(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")

    resolved_company_id = company_id or founder_id
    require_company_access(request, founder_id, resolved_company_id, min_role="viewer")

    overview = {}

    # Goals: current + bucketed
    try:
        company_goal = get_company_goal(founder_id, company_id) or {}
        goals = company_goal.get("goals", [])
        current_goal_id = company_goal.get("current_goal_id")

        current_goal = None
        if current_goal_id:
            current_goal = next((g for g in goals if g["id"] == current_goal_id), None)

        goal_buckets = {}
        for bucket in ["now", "next", "later"]:
            goal_buckets[bucket] = [g for g in goals if g.get("bucket") == bucket]

        overview["goals"] = {
            "current": current_goal,
            "buckets": goal_buckets,
            "north_star": company_goal.get("north_star", ""),
        }
    except Exception as e:
        logger.warning("Failed to load goals: %s", e)
        overview["goals"] = None

    # Outcomes: this week's rollup
    try:
        rollup = weekly_rollup(founder_id, company_id)
        overview["outcomes_rollup"] = rollup
    except Exception as e:
        logger.warning("Failed to load outcomes rollup: %s", e)
        overview["outcomes_rollup"] = None

    # Active run: blockers + status
    try:
        sessions = list_sessions(founder_id, company_id=company_id, limit=1)
        latest_meta = sessions[0] if sessions else None
        if latest_meta and latest_meta.get("status") == "running":
            session_id = latest_meta.get("session_id") or latest_meta.get("id")
            raw_events = load_events(session_id) or []
            events = [e for _, e in raw_events]
            workboard = build_session_workboard(session_id, events)
            overview["active_run"] = {
                "session_id": session_id,
                "started_at": latest_meta.get("created_at"),
                "blockers": workboard.get("blockers", []),
                "progress": workboard.get("progress", {}),
            }
        else:
            overview["active_run"] = None
    except Exception as e:
        logger.warning("Failed to load active run: %s", e)
        overview["active_run"] = None

    # Recommended next goal
    try:
        next_goal = plan_next_goal(founder_id, company_id)
        overview["recommended_goal"] = next_goal
    except Exception as e:
        logger.warning("Failed to load recommended goal: %s", e)
        overview["recommended_goal"] = None

    # Genome facts + conflicts
    try:
        genome = get_genome(founder_id, company_id)
        conflicts = get_conflicts(founder_id, company_id)
        overview["genome"] = {
            "sections": genome.get("sections", {}) if genome else {},
            "conflicts": conflicts,
        }
    except Exception as e:
        logger.warning("Failed to load genome: %s", e)
        overview["genome"] = None

    return {"overview": overview, "ok": True}


async def _build_proof_payload(founder_id: str, company_id: str, *, relive: bool) -> dict[str, Any]:
    """Assemble the verification proof for a company: every artifact's latest receipt.
    When relive is True, re-fetch any deploy URL right now so the proof reflects
    current reality, not just what was true at build time."""
    receipts = list_receipts(founder_id, company_id, latest_only=True)
    artifacts: list[dict[str, Any]] = []
    verified = 0
    for rec in receipts:
        receipt = rec.get("receipt") or {}
        live = None
        if relive:
            url = ((receipt.get("evidence") or {}).get("executable") or {}).get("url")
            if url:
                live = await probe_live_url(url)
        status = (live.get("ok") and "passed") if live is not None else receipt.get("status")
        if status == "passed" or receipt.get("status") == "passed":
            verified += 1
        artifacts.append({
            "artifact_key": rec.get("artifact_key"),
            "artifact_title": rec.get("artifact_title"),
            "agent": rec.get("agent"),
            "status": receipt.get("status"),
            "checks": receipt.get("checks", []),
            "evidence": receipt.get("evidence", {}),
            "attempts": receipt.get("attempts", 1),
            "checked_at": receipt.get("checked_at"),
            "live": live,  # null unless relived
        })
    return {
        "company_id": company_id,
        "artifact_count": len(artifacts),
        "verified_count": verified,
        "artifacts": artifacts,
    }


@router.get("/company/{company_id}/receipts")
async def company_receipts_route(company_id: str, request: Request = None) -> dict[str, Any]:
    """In-app: verification receipts for every artifact this company has produced."""
    try:
        founder_id = request_user_id(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")
    resolved = company_id or founder_id
    require_company_access(request, founder_id, resolved, min_role="viewer")
    payload = await _build_proof_payload(founder_id, resolved, relive=False)
    return {"ok": True, **payload}


@router.post("/company/{company_id}/share")
async def company_share_route(company_id: str, request: Request = None) -> dict[str, Any]:
    """Issue (or rotate) a public share token for this company's proof page."""
    try:
        founder_id = request_user_id(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")
    resolved = company_id or founder_id
    require_company_access(request, founder_id, resolved, min_role="admin")
    token = create_share(founder_id, resolved)
    return {"ok": True, "share_token": token, "path": f"/proof/{token}"}


@router.get("/company/{company_id}/monitoring")
async def company_monitoring_route(company_id: str, request: Request = None) -> dict[str, Any]:
    """Live status: latest health per artifact, uptime, and recent auto-heals."""
    try:
        founder_id = request_user_id(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")
    resolved = company_id or founder_id
    require_company_access(request, founder_id, resolved, min_role="viewer")

    latest = latest_status(founder_id, resolved)
    artifacts = []
    for key, rec in latest.items():
        artifacts.append({
            "artifact_key": key,
            "status": rec.get("status"),
            "checked_at": rec.get("checked_at"),
            "metadata": rec.get("metadata", {}),
            "uptime_7d": uptime_percent(founder_id, resolved, key, days=7),
        })
    heals = [
        {"artifact_key": r.get("artifact_key"), "at": r.get("checked_at"),
         "agent": (r.get("metadata") or {}).get("agent"), "reason": (r.get("metadata") or {}).get("reason")}
        for r in list_monitoring_checks(founder_id, resolved, check_type="auto_heal")
    ][-20:]
    return {"ok": True, "artifacts": artifacts, "recent_heals": heals}


@router.get("/monitoring/scheduler/status")
async def monitoring_scheduler_status_route() -> dict[str, Any]:
    """Singleton monitoring scheduler health."""
    from backend.monitoring.scheduler import get_monitoring_scheduler_status
    return get_monitoring_scheduler_status()


@router.get("/share/{token}")
async def public_proof_route(token: str) -> dict[str, Any]:
    """PUBLIC (no auth): render a company's verification proof, re-verified live."""
    resolved = resolve_share(token)
    if not resolved:
        raise HTTPException(status_code=404, detail="Unknown or revoked share link")
    payload = await _build_proof_payload(
        resolved["founder_id"], resolved["company_id"], relive=True
    )
    # Never leak internal ids on the public surface.
    payload.pop("company_id", None)
    return {"ok": True, **payload}

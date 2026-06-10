"""Company API — company-scoped operations and dashboard."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.tenant_auth import require_founder_access, request_user_id
from backend.missions.company_goal import get_company_goal
from backend.genome.store import get_genome, get_conflicts
from backend.outcomes.store import weekly_rollup
from backend.missions.goal_engine import plan_next_goal
from backend.core.session_store import get_latest_session_meta, get_session_events
from backend.workboard import build_session_workboard

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/company/{company_id}/overview")
async def company_overview_route(
    company_id: str,
    request: Request = None,
) -> dict[str, Any]:
    """Get company command center overview: goals, outcomes, active run, next action.

    Aggregates:
    - Current goal + bucket goals (now/next/later)
    - This week's outcomes + rollup
    - Active run blockers/status
    - Recommended next goal
    - Genome facts + conflicts
    """
    try:
        founder_id = request_user_id(request)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")

    require_founder_access(request, founder_id, min_role="viewer")

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
        latest_meta = get_latest_session_meta(founder_id, company_id)
        if latest_meta and latest_meta.get("status") == "running":
            session_id = latest_meta.get("id")
            events = get_session_events(session_id) or []
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

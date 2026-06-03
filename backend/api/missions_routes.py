"""Missions API — standing autonomous department operators.

Endpoints:
  POST   /missions                        — create mission
  GET    /missions?founder_id=xxx         — list missions for founder
  GET    /missions/{mission_id}           — get mission
  PATCH  /missions/{mission_id}           — update mission fields
  DELETE /missions/{mission_id}           — delete mission
  POST   /missions/{mission_id}/run       — trigger immediate manual run
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from backend.core.session_ids import new_session_id

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BudgetModel(BaseModel):
    max_runs_per_day: int = 3
    max_cost_usd_per_run: float = 1.0


class CreateMissionRequest(BaseModel):
    founder_id: str
    department: str
    name: str
    goal: str
    primary_metric: str
    objectives: List[str] = []
    budget: BudgetModel = BudgetModel()
    approval_policy: str = "auto"


class PatchMissionRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    goal: Optional[str] = None
    objectives: Optional[List[str]] = None
    budget: Optional[BudgetModel] = None
    approval_policy: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/missions")
async def create_mission(body: CreateMissionRequest):
    """Create a new Mission and persist it."""
    from backend.missions.store import create_mission as store_create
    if not body.founder_id or not body.name or not body.goal:
        raise HTTPException(status_code=400, detail="founder_id, name, and goal are required")

    valid_departments = {"research", "marketing", "sales", "technical", "legal", "ops", "finance"}
    if body.department not in valid_departments:
        raise HTTPException(
            status_code=400,
            detail=f"department must be one of: {', '.join(sorted(valid_departments))}",
        )

    valid_policies = {"auto", "require_approval"}
    if body.approval_policy not in valid_policies:
        raise HTTPException(
            status_code=400,
            detail=f"approval_policy must be one of: {', '.join(sorted(valid_policies))}",
        )

    mission = store_create(
        founder_id=body.founder_id,
        department=body.department,
        name=body.name,
        goal=body.goal,
        primary_metric=body.primary_metric,
        objectives=body.objectives,
        budget=body.budget.model_dump(),
        approval_policy=body.approval_policy,
    )
    logger.info("Mission created: %s (founder=%s)", mission["id"], body.founder_id)
    return mission


@router.get("/missions")
async def list_missions(founder_id: str = ""):
    """List all missions for a founder."""
    from backend.missions.store import list_missions as store_list
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    missions = store_list(founder_id=founder_id)
    return {"missions": missions}


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """Return a single mission by ID."""
    from backend.missions.store import get_mission as store_get
    mission = store_get(mission_id=mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.patch("/missions/{mission_id}")
async def update_mission(mission_id: str, body: PatchMissionRequest):
    """Partially update a mission's mutable fields."""
    from backend.missions.store import get_mission as store_get, update_mission as store_update

    mission = store_get(mission_id=mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.status is not None:
        valid_statuses = {"active", "paused", "completed"}
        if body.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of: {', '.join(sorted(valid_statuses))}",
            )
        updates["status"] = body.status
    if body.goal is not None:
        updates["goal"] = body.goal
    if body.objectives is not None:
        updates["objectives"] = body.objectives
    if body.budget is not None:
        updates["budget"] = body.budget.model_dump()
    if body.approval_policy is not None:
        valid_policies = {"auto", "require_approval"}
        if body.approval_policy not in valid_policies:
            raise HTTPException(
                status_code=400,
                detail=f"approval_policy must be one of: {', '.join(sorted(valid_policies))}",
            )
        updates["approval_policy"] = body.approval_policy

    if not updates:
        return mission

    updated = store_update(mission_id=mission_id, updates=updates)
    logger.info("Mission updated: %s fields=%s", mission_id, list(updates.keys()))
    return updated


@router.delete("/missions/{mission_id}")
async def delete_mission(mission_id: str):
    """Delete a mission permanently."""
    from backend.missions.store import get_mission as store_get, delete_mission as store_delete

    mission = store_get(mission_id=mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    store_delete(mission_id=mission_id, founder_id=mission["founder_id"])
    logger.info("Mission deleted: %s", mission_id)
    return {"ok": True}


@router.post("/missions/{mission_id}/run")
async def run_mission(mission_id: str, background_tasks: BackgroundTasks):
    """Trigger an immediate manual run of a mission in the background."""
    from backend.missions.store import get_mission as store_get
    from backend.missions.runner import run_mission as mission_runner

    mission = store_get(mission_id=mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")

    if mission.get("status") == "paused":
        raise HTTPException(status_code=409, detail="Mission is paused — resume it before running")

    session_id = new_session_id()
    background_tasks.add_task(mission_runner, mission_id=mission_id, session_id=session_id)
    logger.info("Mission manual run triggered: %s session=%s", mission_id, session_id)
    return {"ok": True, "session_id": session_id}

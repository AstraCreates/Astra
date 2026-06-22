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

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from backend.core.session_ids import new_session_id
from backend.tenant_auth import require_founder_access

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
    company_id: str = ""
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


class PatchTaskRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SyncNotionRequest(BaseModel):
    founder_id: str
    company_id: str = ""


class ApproveTaskRequest(BaseModel):
    founder_id: str = ""
    company_id: str = ""
    approved: bool = True
    note: str = ""


def _require_company_access(
    request: Request,
    founder_id: str,
    company_id: str = "",
    min_role: str = "viewer",
) -> str:
    require_founder_access(request, founder_id, min_role=min_role)
    resolved_company_id = company_id or founder_id
    if resolved_company_id != founder_id:
        from backend.core.workspace_store import get_workspace
        company = get_workspace(resolved_company_id)
        if not company or str(company.get("founder_id") or "") != founder_id:
            raise HTTPException(status_code=404, detail="Company not found")
    return resolved_company_id


def _mission_for_request(
    request: Request,
    mission_id: str,
    min_role: str = "viewer",
) -> dict[str, Any]:
    from backend.missions.store import get_mission as store_get

    mission = store_get(mission_id=mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    founder_id = str(mission.get("founder_id") or "")
    company_id = str(mission.get("company_id") or founder_id)
    _require_company_access(request, founder_id, company_id, min_role=min_role)
    return mission


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/missions")
async def create_mission(body: CreateMissionRequest, request: Request):
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

    company_id = _require_company_access(
        request,
        body.founder_id,
        body.company_id,
        min_role="operator",
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
        company_id=company_id,
    )
    logger.info("Mission created: %s (founder=%s)", mission["id"], body.founder_id)
    return mission


@router.get("/missions")
async def list_missions(
    request: Request,
    founder_id: str = "",
    company_id: str = "",
):
    """List all missions for a founder."""
    from backend.missions.store import list_missions as store_list
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = _require_company_access(request, founder_id, company_id)
    missions = store_list(founder_id=founder_id, company_id=resolved_company_id)
    return {"missions": missions}


@router.get("/missions/pending-approvals")
async def list_pending_approvals(
    request: Request,
    founder_id: str = "",
    company_id: str = "",
):
    """Every company milestone awaiting the founder's sign-off.
    Declared before /missions/{mission_id} so it isn't swallowed by the dynamic route."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    resolved_company_id = _require_company_access(request, founder_id, company_id)
    from backend.missions.company_goal import pending_approvals
    pend = [{"task": task} for task in pending_approvals(founder_id, resolved_company_id)]
    # Legacy missions are founder-wide, so only expose them in the default company.
    if resolved_company_id == founder_id:
        try:
            from backend.missions.store import pending_approvals as legacy_pending
            pend.extend(legacy_pending(founder_id, resolved_company_id))
        except Exception:
            pass
    return {"pending": pend}


@router.get("/missions/company-goal")
async def get_company_goal(
    request: Request,
    founder_id: str = "",
    company_id: str = "",
):
    from backend.missions.company_goal import get_company_goal as load_company_goal

    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    resolved_company_id = _require_company_access(request, founder_id, company_id)
    goal = load_company_goal(founder_id, resolved_company_id)
    cur = None
    if goal:
        from backend.missions.company_goal import current_goal as _cur, goal_credits, sweep_stale_tasks
        from backend.core.session_store import get_session_credits
        # Auto-heal: if no operating session is actively running, tasks stuck "in_progress"
        # with no done_agents are stale (agent ran but session terminated). Reset to "pending"
        # so the checklist + GoalPanel don't show permanently stuck state.
        sweep_stale_tasks(founder_id, resolved_company_id)
        # Per-goal credit spend (sum of each goal's sessions).
        credits_by_goal = goal_credits(founder_id, resolved_company_id)
        for go in goal.get("goals") or []:
            go["credits_used"] = credits_by_goal.get(go.get("id"), 0)
        # Per-sub-run credit spend.
        for r in goal.get("operating_sessions") or []:
            r["credits_used"] = get_session_credits(r.get("session_id"))
        goal["credits_used_total"] = sum(credits_by_goal.values())
        cur = _cur(founder_id, resolved_company_id)
        if cur:
            cur["credits_used"] = credits_by_goal.get(cur.get("id"), 0)
    return {"company_goal": goal, "current_goal": cur}


class CompanyTaskPatch(BaseModel):
    founder_id: str
    company_id: str = ""
    title: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class PostponeBody(BaseModel):
    founder_id: str
    company_id: str = ""
    postponed: bool = True


@router.patch("/missions/company-goal/tasks/{task_id}")
async def patch_company_task(task_id: str, body: CompanyTaskPatch, request: Request):
    """Founder edits a current-goal task's status (e.g. manually mark done)."""
    from backend.missions.company_goal import set_goal_task_status
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    company_id = _require_company_access(
        request,
        body.founder_id,
        body.company_id,
        min_role="operator",
    )
    if body.status is not None:
        valid = {"pending", "in_progress", "done", "blocked"}
        if body.status not in valid:
            raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(sorted(valid))}")
        try:
            task = set_goal_task_status(
                body.founder_id,
                task_id,
                body.status,
                company_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"ok": True, "task": task}
    raise HTTPException(status_code=400, detail="status is required")


@router.post("/missions/company-goal/tasks/{task_id}/postpone")
async def postpone_company_task(task_id: str, body: PostponeBody, request: Request):
    """Postpone (or un-postpone) a task so it no longer blocks goal completion."""
    from backend.missions.company_goal import postpone_task
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    company_id = _require_company_access(
        request,
        body.founder_id,
        body.company_id,
        min_role="operator",
    )
    try:
        task = postpone_task(
            body.founder_id,
            task_id,
            postponed=body.postponed,
            company_id=company_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True, "task": task}


@router.post("/missions/company-goal/run")
async def run_company_cycle(
    request: Request,
    background_tasks: BackgroundTasks,
    founder_id: str,
    company_id: str = "",
):
    """Run the current goal now — dispatch the whole agent system on its open tasks
    in a child session linked to the launch session."""
    from backend.missions.company_goal import get_company_goal as load_company_goal, current_goal, reconcile_operating_sessions
    from backend.missions.goal_engine import dispatch_current_goal
    from backend.core.session_store import has_active_run
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    resolved_company_id = _require_company_access(
        request,
        founder_id,
        company_id,
        min_role="operator",
    )
    goal = load_company_goal(founder_id, resolved_company_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="No company goal yet — start a run first")
    if goal.get("status") == "paused":
        raise HTTPException(status_code=409, detail="Operating is paused — resume it first")
    cg = current_goal(founder_id, resolved_company_id)
    if not cg:
        raise HTTPException(status_code=409, detail="No active goal to run")
    if cg.get("status") == "proposed":
        raise HTTPException(status_code=409, detail="This goal is proposed — approve it first to start the team")
    reconcile_operating_sessions(founder_id, resolved_company_id)
    if has_active_run(founder_id, company_id=resolved_company_id):
        raise HTTPException(status_code=409, detail="A run is already in progress — wait for it to finish")
    # Pre-register the operating session so we can return its ID immediately.
    # The orchestrator is then kicked off as an asyncio task (non-blocking).
    from backend.core.session_ids import new_session_id
    from backend.core.session_store import register_session, get_session_meta
    import asyncio as _asyncio
    root = goal.get("root_session_id") or goal.get("source_session_id") or ""
    root_meta = get_session_meta(root) if root else {}
    pre_sid = new_session_id()
    try:
        register_session(
            session_id=pre_sid,
            founder_id=founder_id,
            goal=f"GOAL: {cg.get('title', 'Goal run')}",
            workspace_id=str((root_meta or {}).get("workspace_id") or ""),
            company_id=str((root_meta or {}).get("company_id") or resolved_company_id),
            parent_session_id=root,
            kind="operating",
        )
    except Exception:
        pass
    _asyncio.create_task(dispatch_current_goal(founder_id, resolved_company_id, _pre_session_id=pre_sid))
    return {"ok": True, "session_id": pre_sid, "parent_session_id": goal.get("root_session_id", "")}


class ApproveNextGoalBody(BaseModel):
    founder_id: str
    company_id: str = ""
    approved: bool = True


@router.post("/missions/company-goal/approve-next")
async def approve_next_goal(
    body: ApproveNextGoalBody,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Founder sign-off on the planner's PROPOSED next goal. approved → goal goes active
    and the team starts working it; rejected → it's dropped (planner proposes another
    after the next run)."""
    from backend.missions.company_goal import (
        approve_current_goal, reject_current_goal, reconcile_operating_sessions,
    )
    from backend.missions.goal_engine import dispatch_current_goal, plan_next_goal
    from backend.core.session_store import has_active_run
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    company_id = _require_company_access(
        request,
        body.founder_id,
        body.company_id,
        min_role="operator",
    )
    if not body.approved:
        if not reject_current_goal(body.founder_id, company_id):
            raise HTTPException(status_code=404, detail="No proposed goal to reject")
        # Re-plan immediately so the founder gets a different proposal to consider,
        # rather than being stuck with a done goal and no way to move forward.
        nxt = plan_next_goal(body.founder_id, company_id)
        return {"ok": True, "rejected": True, "proposed": nxt}
    goal = approve_current_goal(body.founder_id, company_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="No proposed goal awaiting approval")
    reconcile_operating_sessions(body.founder_id, company_id)
    pre_sid = ""
    if not has_active_run(body.founder_id, company_id=company_id):
        from backend.core.session_ids import new_session_id
        from backend.core.session_store import register_session, get_session_meta
        from backend.missions.company_goal import current_goal as _cg
        import asyncio as _asyncio
        _cg_entry = _cg(body.founder_id, company_id) or {}
        root = goal.get("root_session_id") or goal.get("source_session_id") or ""
        root_meta = get_session_meta(root) if root else {}
        pre_sid = new_session_id()
        try:
            register_session(
                session_id=pre_sid,
                founder_id=body.founder_id,
                goal=f"GOAL: {_cg_entry.get('title', 'Goal run')}",
                workspace_id=str((root_meta or {}).get("workspace_id") or ""),
                company_id=str((root_meta or {}).get("company_id") or company_id),
                parent_session_id=root,
                kind="operating",
            )
        except Exception:
            pass
        _asyncio.create_task(dispatch_current_goal(body.founder_id, company_id, _pre_session_id=pre_sid))
    return {"ok": True, "goal": goal, "session_id": pre_sid}


@router.patch("/missions/company-goal/status")
async def set_company_goal_status(
    request: Request,
    founder_id: str,
    status: str,
    company_id: str = "",
):
    """Pause/resume/complete the whole company operating loop."""
    from backend.missions.company_goal import get_company_goal as load_company_goal, upsert_company_goal
    valid = {"operating", "paused", "completed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(sorted(valid))}")
    resolved_company_id = _require_company_access(
        request,
        founder_id,
        company_id,
        min_role="operator",
    )
    goal = load_company_goal(founder_id, resolved_company_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="No company goal")
    updated = upsert_company_goal(
        founder_id, north_star=goal.get("north_star", ""), company_goal=goal.get("company_goal", ""),
        source_session_id=goal.get("source_session_id", ""), status=status, kpis=goal.get("kpis", []),
        company_id=resolved_company_id,
    )
    return {"ok": True, "status": updated.get("status")}


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str, request: Request):
    """Return a single mission by ID."""
    return _mission_for_request(request, mission_id)


@router.patch("/missions/{mission_id}")
async def update_mission(mission_id: str, body: PatchMissionRequest, request: Request):
    """Partially update a mission's mutable fields."""
    from backend.missions.store import update_mission as store_update

    mission = _mission_for_request(request, mission_id, min_role="operator")

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

    updated = store_update(mission_id=mission_id, **updates)
    logger.info("Mission updated: %s fields=%s", mission_id, list(updates.keys()))
    return updated


@router.delete("/missions/{mission_id}")
async def delete_mission(mission_id: str, request: Request):
    """Delete a mission permanently."""
    from backend.missions.store import delete_mission as store_delete

    _mission_for_request(request, mission_id, min_role="admin")
    store_delete(mission_id=mission_id)
    logger.info("Mission deleted: %s", mission_id)
    return {"ok": True}


@router.patch("/missions/{mission_id}/tasks/{task_id}")
async def patch_task(
    mission_id: str,
    task_id: str,
    body: PatchTaskRequest,
    request: Request,
):
    from backend.missions.store import update_task as store_update_task

    mission = _mission_for_request(request, mission_id, min_role="operator")

    updates: dict[str, Any] = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.notes is not None:
        updates["notes"] = body.notes
    if body.status is not None:
        valid_statuses = {"pending", "in_progress", "awaiting_approval", "done", "blocked"}
        if body.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(sorted(valid_statuses))}")
        updates["status"] = body.status
    if not updates:
        tasks = mission.get("tasks") or []
        for task in tasks:
            if str(task.get("id")) == str(task_id):
                return {"task": task}
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        task = store_update_task(mission_id, task_id, **updates)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task}


@router.post("/missions/{mission_id}/tasks/{task_id}/approve")
async def approve_task(
    mission_id: str,
    task_id: str,
    body: ApproveTaskRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Founder decision on a milestone the agent marked awaiting_approval.

    approved → milestone is 'done'. If that clears all open work on the mission, the
    planner assigns the next milestones (continuous operation). rejected → reopened
    with the founder's note as feedback for the next run.
    """
    from backend.missions.store import get_mission as store_get, decide_task

    mission = _mission_for_request(request, mission_id, min_role="operator")
    founder_id = str(mission.get("founder_id") or "")
    company_id = str(mission.get("company_id") or founder_id)
    if body.founder_id and body.founder_id != founder_id:
        raise HTTPException(status_code=404, detail="Mission not found")
    if body.company_id and body.company_id != company_id:
        raise HTTPException(status_code=404, detail="Mission not found")
    try:
        task = decide_task(mission_id, task_id, approved=body.approved, note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")

    assigned = 0
    if body.approved and founder_id:
        # If approving cleared all open work, assign the next milestones now.
        from backend.missions.planner import assign_next_milestones, has_open_work
        refreshed = store_get(mission_id=mission_id) or {}
        if not has_open_work(refreshed):
            try:
                background_tasks.add_task(
                    assign_next_milestones,
                    founder_id,
                    mission_id,
                    3,
                    company_id,
                )
                assigned = -1  # scheduled in background
            except Exception:
                pass
    # Mirror to Notion (best-effort, non-blocking).
    if founder_id:
        try:
            from backend.tools.notion_sync import sync_founder_operating_system
            if company_id == founder_id:
                background_tasks.add_task(sync_founder_operating_system, founder_id)
            else:
                background_tasks.add_task(
                    sync_founder_operating_system,
                    founder_id,
                    company_id,
                )
        except Exception:
            pass
    return {"ok": True, "task": task, "next_milestones_scheduled": assigned == -1}


@router.post("/missions/sync-notion")
async def sync_missions_notion(body: SyncNotionRequest, request: Request):
    from backend.tools.notion_sync import sync_founder_operating_system

    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    company_id = _require_company_access(
        request,
        body.founder_id,
        body.company_id,
        min_role="operator",
    )
    if company_id == body.founder_id:
        result = sync_founder_operating_system(body.founder_id)
    else:
        result = sync_founder_operating_system(body.founder_id, company_id)
    return result


@router.post("/missions/{mission_id}/run")
async def run_mission(
    mission_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Trigger an immediate manual run of a mission in the background."""
    from backend.missions.runner import run_mission as mission_runner

    mission = _mission_for_request(request, mission_id, min_role="operator")

    if mission.get("status") == "paused":
        raise HTTPException(status_code=409, detail="Mission is paused — resume it before running")

    session_id = new_session_id()
    background_tasks.add_task(mission_runner, mission_id=mission_id, session_id=session_id)
    logger.info("Mission manual run triggered: %s session=%s", mission_id, session_id)
    return {"ok": True, "session_id": session_id}

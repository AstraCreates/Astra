"""Missions API — the company operating loop's founder-facing surface.

Legacy standing-mission CRUD (create/list/get/patch/delete a mission, manual
mission run, ad-hoc Notion sync) has been removed: company_os fully
superseded it and its only frontend callers were themselves orphaned (not
imported by any app route). What remains is the live company-goal lifecycle:

Endpoints:
  GET   /missions/company-goal                          — current operating goal + state
  GET   /missions/pending-approvals                      — milestones awaiting founder sign-off
  PATCH /missions/company-goal/tasks/{task_id}           — edit a goal task
  POST  /missions/company-goal/tasks/{task_id}/postpone  — postpone/un-postpone a task
  POST  /missions/company-goal/run                       — run the current goal now
  POST  /missions/company-goal/approve-next               — approve/reject the proposed next goal
  PATCH /missions/company-goal/status                     — pause/resume/complete operating
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)

router = APIRouter()


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
        from backend.missions.company_goal import (
            current_goal as _cur, goal_credits, sweep_stale_tasks,
            reconcile_operating_sessions,
        )
        from backend.core.session_store import get_session_credits
        # Reconcile first: flip sessions stuck "running" in the JSON to their real
        # terminal state so sweep_stale_tasks can actually fire.
        reconcile_operating_sessions(founder_id, resolved_company_id)
        # Auto-heal: if no operating session is actively running, tasks stuck "in_progress"
        # are stale — reset to "pending" so GoalPanel doesn't show permanently stuck state.
        sweep_stale_tasks(founder_id, resolved_company_id)
        # Re-read after mutations so we return the healed data.
        from backend.missions.company_goal import get_company_goal as _reload
        goal = _reload(founder_id, resolved_company_id) or goal
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
        # Expose whether any session is actively running right now so the
        # frontend can show idle state instead of a stale in-progress goal.
        cur_id = goal.get("current_goal_id", "")
        has_active_session = any(
            r.get("status") == "running" and r.get("goal_id") == cur_id
            for r in goal.get("operating_sessions") or []
        )
    else:
        has_active_session = False
    return {"company_goal": goal, "current_goal": cur, "has_active_session": has_active_session}


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
    from backend.missions.goal_engine import launch_current_goal_dispatch
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
    launch = launch_current_goal_dispatch(founder_id, resolved_company_id)
    return {"ok": True, "session_id": launch["session_id"], "parent_session_id": goal.get("root_session_id", "")}


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
    from backend.missions.goal_engine import launch_current_goal_dispatch, plan_next_goal
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
        pre_sid = launch_current_goal_dispatch(body.founder_id, company_id)["session_id"]
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



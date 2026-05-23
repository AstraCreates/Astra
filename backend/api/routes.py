import uuid

from fastapi import APIRouter, HTTPException

from backend.api.schemas import AskRequest, ApproveRequest, GoalRequest, RejectRequest
from backend.db.client import get_supabase, update_task_status
from backend.orchestrator.loop import orchestrator

router = APIRouter()


@router.post("/goal")
async def submit_goal(body: GoalRequest):
    goal_id = f"g_{uuid.uuid4().hex[:8]}"
    result = await orchestrator.run_goal(
        goal_id=goal_id,
        founder_id=body.founder_id,
        raw_instruction=body.instruction,
        constraints=body.constraints,
    )
    return result


@router.post("/approve")
async def approve_task(body: ApproveRequest):
    await update_task_status(body.task_id, "approved")
    return {"task_id": body.task_id, "status": "approved"}


@router.post("/reject")
async def reject_task(body: RejectRequest):
    await update_task_status(body.task_id, "rejected")
    return {"task_id": body.task_id, "status": "rejected", "reason": body.reason}


@router.post("/ask")
async def ask_agent(body: AskRequest):
    from backend.orchestrator.loop import AGENTS
    from backend.agents.base import AgentTask

    agent = AGENTS.get(body.target_agent)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{body.target_agent}' not found")

    task = AgentTask(
        task_id=f"ask_{uuid.uuid4().hex[:8]}",
        goal_id="direct_ask",
        founder_id=body.founder_id,
        agent=body.target_agent,
        instruction=body.question,
        context_bundle={"context": body.context or ""},
        constraints={},
        tools_available=[],
    )
    result = await agent.run(task)
    return {"agent": body.target_agent, "response": result.output, "reasoning": result.reasoning}


@router.get("/status/{goal_id}")
async def get_status(goal_id: str):
    db = get_supabase()
    goals = db.table("goals").select("*").eq("id", goal_id).execute().data
    if not goals:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal = goals[0]
    tasks = db.table("tasks").select("*").eq("goal_id", goal_id).execute().data
    return {"goal": goal, "tasks": tasks}

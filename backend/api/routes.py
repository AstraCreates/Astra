import uuid

from fastapi import APIRouter, HTTPException

from backend.api.schemas import AskRequest, ApproveRequest, GoalRequest, RejectRequest, SetupRequest, SaveCredentialRequest
from backend.provisioning.credentials_store import store_credentials


def _write_env_key(key: str, value: str) -> None:
    env_path = ".env"
    try:
        try:
            lines = open(env_path).readlines()
        except FileNotFoundError:
            lines = []
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}\n")
        open(env_path, "w").writelines(lines)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not write %s to .env: %s", key, e)
import asyncio
from fastapi.responses import StreamingResponse

from backend.db.client import get_supabase, update_task_status
from backend.core.factory import get_orchestrator
from backend.core.events import stream_events, publish

router = APIRouter()


@router.post("/goal")
async def submit_goal(body: GoalRequest):
    import uuid as _uuid
    session_id = _uuid.uuid4().hex[:12]
    orch = get_orchestrator()

    async def _run():
        try:
            await orch.run(
                goal=body.instruction,
                founder_id=body.founder_id,
                constraints=body.constraints,
                session_id=session_id,
            )
        except Exception as e:
            await publish(session_id, {"type": "goal_error", "error": str(e)})

    asyncio.create_task(_run())
    return {"session_id": session_id, "status": "running"}


@router.get("/stream/{session_id}")
async def stream_goal(session_id: str):
    async def _gen():
        async for chunk in stream_events(session_id):
            yield chunk
    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
    })


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
    from backend.core.agent import AgentContext

    orch = get_orchestrator()
    agent = orch.specialists.get(body.target_agent)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{body.target_agent}' not found. Available: {list(orch.specialists.keys())}")

    ctx = AgentContext(
        goal=body.question,
        founder_id=body.founder_id,
        session_id=f"ask_{uuid.uuid4().hex[:8]}",
        shared={"context": body.context or ""},
    )
    result = await agent.run(ctx)
    return {"agent": body.target_agent, "response": result}


@router.post("/setup")
async def setup_accounts(body: SetupRequest):
    """
    Provision GitHub, Vercel, SendGrid accounts from email+password.
    Returns status per service + OAuth URLs for Instagram/TikTok/Meta.
    """
    from backend.provisioning.account_provisioner import provision_all
    result = await provision_all(
        founder_id=body.founder_id,
        email=body.email,
        password=body.password,
        base_url=body.base_url,
    )
    return result


@router.post("/setup/service")
async def save_service_credential(body: SaveCredentialRequest):
    """Save a manually entered credential (GitHub PAT, SendGrid key, Vercel token)."""
    from backend.tools.composio_tools import _reset_toolset
    store_credentials(body.founder_id, body.service, body.credentials)
    if body.service == "composio" and body.credentials.get("api_key"):
        store_credentials("__platform__", "composio", body.credentials)
        api_key = body.credentials["api_key"]
        # Persist to .env so it survives server restarts
        _write_env_key("COMPOSIO_API_KEY", api_key)
        from backend.config import settings
        from backend.tools.composio_tools import _reset_toolset
        settings.composio_api_key = api_key
        _reset_toolset()
    return {"saved": True, "service": body.service, "founder_id": body.founder_id}


@router.get("/setup/{founder_id}")
async def get_setup_status(founder_id: str):
    """Returns which services are connected for this founder."""
    from backend.provisioning.account_provisioner import get_founder_setup_status
    return await get_founder_setup_status(founder_id)


@router.get("/setup/composio/connect/{founder_id}")
async def composio_connect(founder_id: str, apps: str = "github,gmail,linkedin,googlecalendar,notion,linear"):
    """
    Returns Composio OAuth URLs for the requested apps.
    Founder clicks each URL to authenticate — Composio stores tokens mapped to founder_id.
    apps: comma-separated list, defaults to all supported apps.
    """
    import asyncio
    from backend.tools.composio_tools import connect_founder_tools
    app_list = [a.strip() for a in apps.split(",") if a.strip()]
    result = await asyncio.to_thread(connect_founder_tools, founder_id, app_list)
    return {"founder_id": founder_id, "oauth_urls": result}


@router.get("/status/{goal_id}")
async def get_status(goal_id: str):
    db = get_supabase()
    goals = db.table("goals").select("*").eq("id", goal_id).execute().data
    if not goals:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal = goals[0]
    tasks = db.table("tasks").select("*").eq("goal_id", goal_id).execute().data
    return {"goal": goal, "tasks": tasks}

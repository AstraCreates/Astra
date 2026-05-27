import hashlib
import hmac
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

from backend.api.schemas import AskRequest, ApproveRequest, ContinueRequest, GoalRequest, RejectRequest, SetupRequest, SaveCredentialRequest, SteerRequest
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
async def stream_goal(session_id: str, request: Request):
    raw_last = request.headers.get("Last-Event-ID") or request.query_params.get("lastEventId")
    last_event_id: int | None = None
    if raw_last:
        try:
            last_event_id = int(raw_last)
        except ValueError:
            pass

    async def _gen():
        async for chunk in stream_events(session_id, last_event_id=last_event_id):
            yield chunk
    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Last-Event-ID, *",
    })


@router.post("/approve")
async def approve_task(body: ApproveRequest):
    await update_task_status(body.task_id, "approved")
    return {"task_id": body.task_id, "status": "approved"}


@router.post("/reject")
async def reject_task(body: RejectRequest):
    await update_task_status(body.task_id, "rejected")
    return {"task_id": body.task_id, "status": "rejected", "reason": body.reason}


@router.post("/goal/continue")
async def continue_goal(body: ContinueRequest):
    """Run follow-up tasks on an existing company session with full vault context."""
    import uuid as _uuid
    session_id = _uuid.uuid4().hex[:12]
    orch = get_orchestrator()

    async def _run():
        try:
            await orch.continue_run(
                instruction=body.instruction,
                founder_id=body.founder_id,
                prior_session_id=body.prior_session_id,
                agents=body.agents,
                session_id=session_id,
            )
        except Exception as e:
            await publish(session_id, {"type": "goal_error", "error": str(e)})

    asyncio.create_task(_run())
    return {"session_id": session_id, "status": "running", "prior_session_id": body.prior_session_id}


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


@router.post("/steer")
async def steer_session(body: SteerRequest):
    """Inject a founder directive into a running session."""
    from backend.core.events import publish, steer_push
    steer_push(body.session_id, body.message)
    await publish(body.session_id, {
        "type": "founder_steer",
        "message": body.message,
    })
    return {"ok": True, "session_id": body.session_id}


@router.post("/steer/{session_id}")
async def steer_session_path(session_id: str, body: dict):
    """Path-param variant — frontend sends POST /steer/{session_id} with {message} body."""
    from backend.core.events import publish, steer_push
    message = body.get("message", "")
    steer_push(session_id, message)
    await publish(session_id, {
        "type": "founder_steer",
        "message": message,
    })
    return {"ok": True, "session_id": session_id}


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


@router.get("/vault/{founder_id}")
async def get_vault_sessions(founder_id: str):
    """List all sessions for a founder with per-agent note summaries."""
    import asyncio
    from backend.tools.obsidian_logger import _sessions_root
    from pathlib import Path
    import re

    root = _sessions_root(founder_id)
    if not root.exists():
        return {"sessions": []}

    sessions = []
    for session_dir in sorted(root.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        notes = []
        for note_file in sorted(session_dir.glob("*.md")):
            agent = note_file.stem
            if agent == "index":
                continue
            text = note_file.read_text(errors="replace")
            # Extract summary section
            summary_match = re.search(r"## Summary\n(.+?)(?=\n##|\Z)", text, re.DOTALL)
            summary = summary_match.group(1).strip()[:300] if summary_match else ""
            # Extract output keys
            output_match = re.search(r"## Output\n```json\n(.+?)```", text, re.DOTALL)
            output_keys = []
            if output_match:
                try:
                    import json
                    d = json.loads(output_match.group(1))
                    output_keys = [k for k in d.keys() if d[k]]
                except Exception:
                    pass
            notes.append({"agent": agent, "summary": summary, "output_keys": output_keys, "file": str(note_file)})

        # Read index.md for goal
        goal = ""
        idx = session_dir / "index.md"
        if idx.exists():
            idx_text = idx.read_text(errors="replace")
            goal_match = re.search(r"goal:\s*(.+)", idx_text)
            if goal_match:
                goal = goal_match.group(1).strip()

        sessions.append({
            "session_id": session_dir.name,
            "goal": goal,
            "agents": notes,
            "note_count": len(notes),
        })

    return {"founder_id": founder_id, "sessions": sessions}


@router.get("/vault/{founder_id}/note")
async def get_vault_note(founder_id: str, session_id: str, agent: str):
    """Return full markdown content of one agent note."""
    from backend.tools.obsidian_logger import _note_path
    path = _note_path(agent, session_id, founder_id)
    if not path.exists():
        path = _note_path(agent, session_id, None)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    return {"content": path.read_text(errors="replace"), "agent": agent, "session_id": session_id}


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request):
    """
    Clerk webhook — auto-provisions a user record on user.created.
    Verify svix signature, then initialize credentials store + DB row.
    """
    from backend.config import settings
    from backend.db.client import get_supabase

    body = await request.body()
    secret = settings.clerk_webhook_secret

    # Verify Clerk/svix signature when secret is configured
    if secret:
        svix_id = request.headers.get("svix-id", "")
        svix_ts = request.headers.get("svix-timestamp", "")
        svix_sig = request.headers.get("svix-signature", "")

        # Reject replays older than 5 minutes
        try:
            if abs(time.time() - int(svix_ts)) > 300:
                raise HTTPException(status_code=400, detail="Timestamp too old")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid timestamp")

        signed = f"{svix_id}.{svix_ts}.{body.decode()}"
        raw_secret = secret.removeprefix("whsec_")
        import base64
        key = base64.b64decode(raw_secret)
        expected = base64.b64encode(
            hmac.new(key, signed.encode(), hashlib.sha256).digest()
        ).decode()
        sigs = [s.removeprefix("v1,") for s in svix_sig.split(" ")]
        if not any(hmac.compare_digest(expected, s) for s in sigs):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    event_type = payload.get("type")

    if event_type != "user.created":
        return {"ok": True, "skipped": event_type}

    data = payload.get("data", {})
    user_id = data.get("id")
    email = (data.get("email_addresses") or [{}])[0].get("email_address", "")
    name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()

    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user id")

    logger.info("clerk webhook: user.created user_id=%s email=%s", user_id, email)

    # Upsert user row in Supabase (non-fatal)
    try:
        db = get_supabase()
        db.table("users").upsert({"id": user_id, "email": email, "name": name}).execute()
    except Exception as e:
        logger.warning("supabase user upsert failed: %s", e)

    # Full auto-provision in background — don't block webhook response
    async def _provision():
        try:
            from backend.provisioning.user_provisioner import provision_new_user
            await provision_new_user(founder_id=user_id, email=email, name=name)
        except Exception as e:
            logger.error("Auto-provisioning failed for %s: %s", user_id, e)

    asyncio.create_task(_provision())

    return {"ok": True, "user_id": user_id, "provisioning": "started"}


@router.get("/files/{filename}")
async def serve_file(filename: str):
    """Serve generated files (PDFs, TXTs) from /tmp/astra_docs."""
    import mimetypes
    from pathlib import Path
    from fastapi.responses import FileResponse

    safe_name = Path(filename).name
    docs_dir = Path("/tmp/astra_docs")
    path = docs_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(safe_name)
    return FileResponse(path, media_type=media_type or "application/octet-stream", filename=safe_name)


@router.get("/status/{goal_id}")
async def get_status(goal_id: str):
    db = get_supabase()
    goals = db.table("goals").select("*").eq("id", goal_id).execute().data
    if not goals:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal = goals[0]
    tasks = db.table("tasks").select("*").eq("goal_id", goal_id).execute().data
    return {"goal": goal, "tasks": tasks}

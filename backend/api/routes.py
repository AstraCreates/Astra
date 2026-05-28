import hashlib
import hmac
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

from backend.api.schemas import (
    AskRequest,
    ApproveRequest,
    BrainRecordRequest,
    BrainIngestRequest,
    BrainAskRequest,
    BrainProposalRequest,
    BrainSyncConfigRequest,
    BrainSyncRequest,
    ContinueRequest,
    GoalRequest,
    RejectRequest,
    SetupRequest,
    SaveCredentialRequest,
    SteerRequest,
    StripeEINUpgradeRequest,
    StripeProductRequest,
    StripeWebhookRegisterRequest,
)
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


@router.get("/brain/{founder_id}")
async def get_brain(founder_id: str):
    """Return the founder's normalized company brain graph."""
    from backend.tools.company_brain import get_company_brain
    return get_company_brain(founder_id)


@router.post("/brain/{founder_id}/sync")
async def sync_brain(founder_id: str, body: BrainSyncRequest):
    """Sync connected sources and local agent vault notes into the company brain."""
    import asyncio
    from backend.tools.company_brain import sync_company_brain
    return await asyncio.to_thread(sync_company_brain, founder_id, body.sources)


@router.get("/brain/{founder_id}/search")
async def search_brain(founder_id: str, q: str, limit: int = 8):
    """Search company brain records for human UI and agent context."""
    from backend.tools.company_brain import search_company_brain
    return search_company_brain(founder_id, q, limit)


@router.get("/brain/{founder_id}/agent-context")
async def brain_agent_context(founder_id: str, q: str, limit: int = 8):
    """Compact graph context for IDE/MCP/external agents."""
    from backend.tools.company_brain import company_brain_agent_context
    return company_brain_agent_context(founder_id, q, limit)


@router.post("/brain/{founder_id}/ask")
async def ask_brain(founder_id: str, body: BrainAskRequest):
    """Return a cited answer synthesized from matched company-brain records."""
    from backend.tools.company_brain import ask_company_brain
    return ask_company_brain(founder_id, body.question, body.limit)


@router.post("/brain/{founder_id}/records")
async def add_brain_record(founder_id: str, body: BrainRecordRequest):
    """Add a manual or app-sourced record to the company brain."""
    from backend.tools.company_brain import add_company_brain_record
    return add_company_brain_record(
        founder_id=founder_id,
        source=body.source,
        title=body.title,
        content=body.content,
        kind=body.kind,
        url=body.url or "",
        canonical=body.canonical,
        stale_risk=body.stale_risk,
    )


@router.post("/brain/{founder_id}/ingest")
async def ingest_brain_records(founder_id: str, body: BrainIngestRequest):
    """Bulk-ingest normalized records from connector/webhook payloads."""
    import asyncio
    from backend.tools.company_brain import ingest_company_brain_records
    return await asyncio.to_thread(
        ingest_company_brain_records,
        founder_id,
        body.source,
        body.records,
    )


@router.post("/brain/{founder_id}/import")
async def import_brain_sources(founder_id: str, body: BrainSyncRequest):
    """Import actual records from connected providers into the company brain."""
    import asyncio
    from backend.tools.company_brain_connectors import import_company_brain_sources
    return await asyncio.to_thread(
        import_company_brain_sources,
        founder_id,
        body.sources,
        body.limit,
    )


@router.get("/brain/{founder_id}/sync/status")
async def brain_sync_status(founder_id: str):
    """Return continuous sync settings and recent run history."""
    from backend.tools.company_brain import get_company_brain_sync_status
    return get_company_brain_sync_status(founder_id)


@router.post("/brain/{founder_id}/sync/config")
async def configure_brain_sync(founder_id: str, body: BrainSyncConfigRequest):
    """Configure continuous sync for connected providers."""
    from backend.tools.company_brain import configure_company_brain_sync
    return configure_company_brain_sync(
        founder_id=founder_id,
        enabled=body.enabled,
        sources=body.sources,
        interval_minutes=body.interval_minutes,
    )


@router.post("/brain/{founder_id}/sync/run")
async def run_brain_sync(founder_id: str, body: BrainSyncRequest):
    """Run continuous-sync import now, regardless of schedule."""
    import asyncio
    from backend.tools.company_brain import configure_company_brain_sync, run_company_brain_sync
    if body.sources:
        configure_company_brain_sync(founder_id, enabled=True, sources=body.sources, interval_minutes=60)
    return await asyncio.to_thread(run_company_brain_sync, founder_id, True)


@router.get("/brain/scheduler/status")
async def brain_scheduler_status():
    """Return process-local company-brain scheduler status."""
    from backend.tools.company_brain_scheduler import get_company_brain_scheduler_status
    return get_company_brain_scheduler_status()


@router.post("/brain/scheduler/run-due")
async def run_due_brain_syncs():
    """Run all currently due company-brain sync jobs."""
    import asyncio
    from backend.tools.company_brain import run_due_company_brain_syncs
    return await asyncio.to_thread(run_due_company_brain_syncs)


@router.post("/brain/{founder_id}/maintain")
async def maintain_brain(founder_id: str):
    """Run drift, canonical-gap, and contradiction detection."""
    import asyncio
    from backend.tools.company_brain import maintain_company_brain
    return await asyncio.to_thread(maintain_company_brain, founder_id)


@router.post("/brain/{founder_id}/proposals/{proposal_id}")
async def update_brain_proposal(founder_id: str, proposal_id: str, body: BrainProposalRequest):
    """Update a maintenance proposal status."""
    from backend.tools.company_brain import resolve_company_brain_proposal
    return resolve_company_brain_proposal(founder_id, proposal_id, body.status)


# ── Stripe Standard Connect ───────────────────────────────────────────────────

@router.get("/stripe/oauth-url/{founder_id}")
async def stripe_oauth_url(founder_id: str, email: str = "", frontend_base: str = "http://localhost:3003"):
    """
    Return the Stripe OAuth URL to send the founder to connect/create their Stripe account.
    The redirect_uri points back to this backend's /stripe/callback endpoint.
    """
    from backend.tools.stripe_tools import get_oauth_url_with_email
    from backend.config import settings
    redirect_uri = f"{settings.backend_url}/stripe/callback"
    try:
        url = get_oauth_url_with_email(founder_id, redirect_uri, email)
        return {"url": url}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stripe/debug-callback")
async def stripe_debug_callback(code: str = "", state: str = "", error: str = ""):
    """Debug version — returns raw result instead of redirecting."""
    from backend.tools.stripe_tools import exchange_oauth_code
    if error:
        return {"stripe_error": error}
    result = exchange_oauth_code(code)
    return {"code": code[:12], "state": state, "result": result}


@router.get("/stripe/callback")
async def stripe_callback(code: str = "", state: str = "", error: str = "", frontend_base: str = "http://localhost:3003"):
    """
    Stripe OAuth callback. Exchanges the code for an access_token, stores it,
    then redirects the browser to the frontend payments page.
    """
    from fastapi.responses import RedirectResponse
    from backend.tools.stripe_tools import exchange_oauth_code
    from backend.provisioning.credentials_store import store_credentials
    from backend.config import settings

    fe_base = settings.frontend_url

    if error:
        return RedirectResponse(url=f"{fe_base}/payments?stripe_error={error}")

    if not code or not state:
        return RedirectResponse(url=f"{fe_base}/payments?stripe_error=missing_params")

    founder_id = state
    print(f"[STRIPE] callback code={code[:12]} founder={founder_id}", flush=True)
    result = exchange_oauth_code(code)
    print(f"[STRIPE] exchange result={result}", flush=True)

    if "error" in result:
        print(f"[STRIPE] exchange FAILED: {result}", flush=True)
        return RedirectResponse(url=f"{fe_base}/payments?stripe_error=exchange_failed")

    store_credentials(founder_id, "stripe", {
        "access_token": result["access_token"],
        "stripe_user_id": result["stripe_user_id"],
        "livemode": result.get("livemode", False),
    })

    return RedirectResponse(url=f"{fe_base}/payments?stripe_connected=1")


@router.get("/stripe/status/{founder_id}")
async def stripe_status(founder_id: str):
    """Check if the founder has connected Stripe and whether their account is active."""
    from backend.tools.stripe_tools import get_account_status
    from backend.provisioning.credentials_store import load_credentials

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        return {"connected": False, "charges_enabled": False, "payouts_enabled": False}

    status = get_account_status(creds["access_token"])
    return {
        **status,
        "livemode": creds.get("livemode", False),
        "upgraded_to_business": creds.get("upgraded_to_business", False),
    }


@router.get("/stripe/data/{founder_id}")
async def stripe_data(founder_id: str):
    """Return live balance, charges, payouts, and revenue metrics from the founder's Stripe account."""
    from backend.tools.stripe_tools import get_stripe_data
    from backend.provisioning.credentials_store import load_credentials

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=404, detail="Stripe not connected. Connect via the Payments page.")

    data = get_stripe_data(creds["access_token"])
    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])
    return data


@router.post("/stripe/upgrade-ein/{founder_id}")
async def stripe_upgrade_ein(founder_id: str, body: StripeEINUpgradeRequest):
    """
    Record that the founder has upgraded their Stripe account to their LLC/EIN.
    With Standard Connect the founder updates Stripe directly — this marks it complete in Astra.
    TODO: Auto-trigger this after NWRA LLC filing + IRS EIN confirmation.
    """
    from backend.tools.stripe_tools import record_ein_upgrade
    from backend.provisioning.credentials_store import load_credentials, store_credentials

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=404, detail="Stripe not connected for this founder.")

    result = record_ein_upgrade(founder_id, body.ein, body.business_name)
    store_credentials(founder_id, "stripe", {
        **creds,
        "ein_last4": body.ein[-4:],
        "business_name": body.business_name,
        "upgraded_to_business": True,
    })
    return result


@router.get("/setup/{founder_id}")
async def get_setup_status(founder_id: str):
    """Returns which services are connected for this founder."""
    from backend.provisioning.account_provisioner import get_founder_setup_status
    return await get_founder_setup_status(founder_id)


@router.post("/setup/auto-connect/{founder_id}")
async def auto_connect_integrations(founder_id: str):
    """
    Apply all available platform credentials for this founder and return
    deterministic per-service auto-connect status.
    """
    from backend.provisioning.integration_automation import auto_connect_status
    return auto_connect_status(founder_id, apply=True)


@router.get("/setup/auto-connect/{founder_id}")
async def get_auto_connect_status(founder_id: str):
    """Preview per-service automation status without applying changes."""
    from backend.provisioning.integration_automation import auto_connect_status
    return auto_connect_status(founder_id, apply=False)


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


# ── Stripe Products ───────────────────────────────────────────────────────────

@router.post("/stripe/products/{founder_id}")
async def create_product(founder_id: str, body: StripeProductRequest):
    """Create a Stripe product + price + payment link for the founder."""
    from backend.tools.stripe_tools import create_product_with_payment_link
    from backend.provisioning.credentials_store import load_credentials

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=404, detail="Stripe not connected.")

    result = create_product_with_payment_link(
        access_token=creds["access_token"],
        name=body.name,
        description=body.description or "",
        amount=body.amount,
        currency=body.currency or "usd",
        interval=body.interval or "",
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/stripe/products/{founder_id}")
async def list_products(founder_id: str):
    """List all Stripe products with prices and payment links."""
    from backend.tools.stripe_tools import list_stripe_products
    from backend.provisioning.credentials_store import load_credentials

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=404, detail="Stripe not connected.")

    result = list_stripe_products(creds["access_token"])
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Stripe Webhooks ───────────────────────────────────────────────────────────

@router.post("/stripe/register-webhook/{founder_id}")
async def register_webhook(founder_id: str, body: StripeWebhookRegisterRequest):
    """Register a Stripe webhook endpoint for the founder's account."""
    from backend.tools.stripe_tools import register_stripe_webhook
    from backend.provisioning.credentials_store import load_credentials, store_credentials
    from backend.config import settings

    creds = load_credentials(founder_id, "stripe")
    if not creds or not creds.get("access_token"):
        raise HTTPException(status_code=404, detail="Stripe not connected.")

    backend_base = (body.backend_url or settings.backend_url).rstrip("/")
    endpoint_url = f"{backend_base}/stripe/webhook/{founder_id}"

    result = register_stripe_webhook(creds["access_token"], endpoint_url)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    # Store webhook secret for signature verification
    store_credentials(founder_id, "stripe", {
        **creds,
        "webhook_id": result["webhook_id"],
        "webhook_secret": result["secret"],
    })
    return result


@router.post("/stripe/webhook/{founder_id}")
async def stripe_webhook(founder_id: str, request: Request):
    """
    Receive Stripe webhook events for a founder.
    Stores event and publishes alert to SSE stream if a session is active.
    """
    from backend.tools.stripe_tools import store_webhook_event
    from backend.provisioning.credentials_store import load_credentials

    body = await request.body()
    payload = json.loads(body)

    event_type = payload.get("type", "")
    event_data = payload.get("data", {}).get("object", {})

    # Build a human-readable alert
    alert = _build_alert(event_type, event_data)
    event = {
        "id": payload.get("id", ""),
        "type": event_type,
        "alert": alert,
        "created": payload.get("created", int(time.time())),
        "data": {k: event_data.get(k) for k in ("amount", "currency", "status", "description", "receipt_email") if event_data.get(k) is not None},
    }

    store_webhook_event(founder_id, event)
    logger.info("Stripe webhook %s for founder %s: %s", event_type, founder_id, alert)
    return {"received": True}


def _build_alert(event_type: str, data: dict) -> str:
    amount = data.get("amount")
    currency = (data.get("currency") or "usd").upper()
    amt_str = f"${amount / 100:.2f} {currency}" if amount else ""
    email = data.get("receipt_email") or data.get("customer_email") or ""
    customer = f" from {email}" if email else ""

    if event_type == "payment_intent.succeeded":
        return f"Payment received: {amt_str}{customer}"
    if event_type == "charge.succeeded":
        return f"Charge succeeded: {amt_str}{customer}"
    if event_type == "payment_intent.payment_failed":
        return f"Payment failed: {amt_str}{customer}"
    if event_type == "charge.failed":
        return f"Charge failed: {amt_str}{customer}"
    if event_type == "charge.refunded":
        return f"Refund issued: {amt_str}{customer}"
    if event_type == "customer.subscription.created":
        return f"New subscription started{customer}"
    if event_type == "customer.subscription.deleted":
        return f"Subscription cancelled{customer}"
    if event_type == "customer.subscription.updated":
        return f"Subscription updated{customer}"
    if event_type == "payout.paid":
        return f"Payout sent to bank: {amt_str}"
    if event_type == "payout.failed":
        return f"Payout failed: {amt_str}"
    return event_type.replace(".", " ").title()


@router.get("/stripe/events/{founder_id}")
async def stripe_events(founder_id: str, limit: int = 20):
    """Return recent Stripe webhook events/alerts for the founder."""
    from backend.tools.stripe_tools import get_webhook_events
    return {"events": get_webhook_events(founder_id, limit)}

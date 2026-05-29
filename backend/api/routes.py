import hashlib
import hmac
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

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
    InputResponse,
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


_AGENT_CHAT_ROLES: dict[str, str] = {
    "research": "You are Astra's Research agent. You are an expert in market analysis, competitive intelligence, TAM/SAM/SOM sizing, industry trends, and academic research.",
    "research_competitors": "You are Astra's Competitor Research agent. You are an expert in competitive landscapes, company profiles, funding data, and market positioning.",
    "research_execution": "You are Astra's Execution Research agent. You are an expert in go-to-market strategy, unit economics, tech stack decisions, and startup execution.",
    "legal": "You are Astra's Legal agent. You are an expert in startup legal structures, privacy policies, terms of service, NDAs, founder agreements, IP assignment, and LLC/incorporation.",
    "web": "You are Astra's Web agent. You are an expert in landing page design, Vercel deployments, GitHub repos, and conversion-focused web copy.",
    "marketing": "You are Astra's Marketing agent. You are an expert in social media content, Instagram Reels, TikTok scripts, Meta ad copy, email campaigns, and growth marketing.",
    "technical": "You are Astra's Technical agent. You are an expert in software architecture, MVP development, full-stack engineering, auth systems, and database design.",
    "ops": "You are Astra's Operations agent. You are an expert in fundraising docs, investor outreach, executive summaries, SOPs, and company operations.",
    "sales": "You are Astra's Sales agent. You are an expert in lead generation, outreach sequences, CRM management, and B2B/B2C sales strategy.",
    "design": "You are Astra's Design agent. You are an expert in brand identity, color palettes, wireframes, design systems, and UI/UX mockups.",
}


@router.post("/chat/{agent_key}")
async def chat_agent(agent_key: str, body: AskRequest):
    """
    Lightweight single-turn chat with a specific agent.
    Injects company brain snippets, Obsidian vault notes, and session
    context so the agent answers with full knowledge of the company.
    """
    import re as _re
    import openai as _openai
    from backend.config import settings

    orch = get_orchestrator()
    base_key = _re.sub(r"_\d+$", "", agent_key)
    agent = orch.specialists.get(agent_key) or orch.specialists.get(base_key)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found. Available: {list(orch.specialists.keys())}")

    # ── 1. Company brain — semantic search + canonical fallback ──────────────
    brain_context = ""
    try:
        from backend.tools.company_brain import search_company_brain, _load as _brain_load
        results = search_company_brain(body.founder_id, body.question, limit=6)
        snippets = results.get("results", [])
        if snippets:
            lines = [f"- [{r.get('source','?')}] {r.get('content','')[:400]}" for r in snippets]
            brain_context = "COMPANY KNOWLEDGE (semantic search):\n" + "\n".join(lines)
        else:
            # Fallback: load ALL canonical records directly
            data = _brain_load(body.founder_id)
            records = [r for r in data.get("records", []) if r.get("status", "active") == "active"]
            if records:
                lines = [f"- [{r.get('source','?')}] {r.get('title','')}: {r.get('content','')[:300]}" for r in records[:10]]
                brain_context = "COMPANY KNOWLEDGE (all records):\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("Brain context fetch failed: %s", e)

    # ── 2. Obsidian vault — all prior sessions for this agent + founder ───────
    obsidian_context = ""
    try:
        from backend.tools.obsidian_logger import format_vault_context, _note_path
        # Load notes across all prior sessions for this agent
        vault_text = format_vault_context(base_key, max_notes=5, founder_id=body.founder_id)
        # If a specific session is active, also include that note in full (may overlap, that's fine)
        if body.session_id:
            note_file = _note_path(base_key, body.session_id, body.founder_id)
            if note_file.exists():
                current_text = note_file.read_text(encoding="utf-8")[:3000]
                if current_text not in vault_text:
                    vault_text = f"CURRENT SESSION NOTES:\n{current_text}\n\n{vault_text}"
        if vault_text.strip():
            obsidian_context = vault_text
    except Exception as e:
        logger.warning("Obsidian context fetch failed: %s", e)

    # ── 3. Assemble system prompt with a clean conversational role ────────────
    role_description = _AGENT_CHAT_ROLES.get(base_key, f"You are Astra's {base_key.capitalize()} agent.")

    # Company identity block — always at top so model never forgets it
    identity_lines = []
    if body.company_name:
        identity_lines.append(f"Company name: {body.company_name}")
    if body.goal:
        identity_lines.append(f"Founder's goal: {body.goal}")
    identity_block = "\n".join(identity_lines)

    context_blocks = [b for b in [identity_block, brain_context, obsidian_context, body.context or ""] if b.strip()]
    context_section = ("\n\n---\n\n".join(context_blocks)) if context_blocks else ""

    system_prompt = (
        f"{role_description}\n\n"
        "You are answering a direct question from the founder. "
        "Use the context below — company identity, company knowledge, prior research, and session notes — "
        "to give a specific, grounded answer. "
        "Be concise and helpful. Respond in plain conversational text. "
        "Do NOT output JSON. Do NOT use markdown headers. Bullet points are fine."
    )
    if context_section:
        system_prompt += f"\n\n--- CONTEXT ---\n{context_section}"

    # Use chat model if configured, otherwise fall back to agent model
    base_url = settings.chat_model_base_url or settings.agent_model_base_url
    api_key = settings.chat_model_api_key or settings.agent_model_api_key
    model_name = settings.chat_model_name or settings.agent_model_name

    try:
        client = _openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        resp = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": body.question},
            ],
            temperature=0.7,
            timeout=60.0,
        )
        reply = resp.choices[0].message.content or ""
        reply = _re.sub(r"<think>.*?</think>", "", reply, flags=_re.DOTALL).strip()
        return {"agent": agent_key, "response": reply}
    except Exception as e:
        logger.error("Chat agent %s error: %s", agent_key, e)
        raise HTTPException(status_code=503, detail=str(e))


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


# ── GitHub OAuth ──────────────────────────────────────────────────────────────

@router.get("/github/oauth-url/{founder_id}")
async def github_oauth_url(founder_id: str):
    """Return the GitHub OAuth authorization URL."""
    from backend.config import settings
    from urllib.parse import urlencode
    if not settings.github_client_id:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured")
    redirect_uri = f"{settings.backend_url}/api/github/callback"
    params = urlencode({
        "client_id": settings.github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo workflow read:org",
        "state": founder_id,
    })
    return {"url": f"https://github.com/login/oauth/authorize?{params}"}


@router.get("/github/callback")
async def github_callback(code: str = "", state: str = "", error: str = ""):
    """
    GitHub OAuth callback. Exchanges the code for an access token,
    stores it under the founder's credentials, then redirects to the
    integrations page.
    """
    import httpx
    from fastapi.responses import RedirectResponse
    from backend.config import settings
    from backend.provisioning.credentials_store import store_credentials

    fe_base = settings.frontend_url

    if error:
        return RedirectResponse(url=f"{fe_base}/integrations?github_error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{fe_base}/integrations?github_error=missing_params")

    founder_id = state
    redirect_uri = f"{settings.backend_url}/api/github/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )

    data = resp.json()
    token = data.get("access_token")

    if not token:
        logger.error("GitHub OAuth exchange failed: %s", data)
        return RedirectResponse(url=f"{fe_base}/integrations?github_error=exchange_failed")

    store_credentials(founder_id, "github", {"token": token})
    settings.github_token = token
    logger.info("GitHub OAuth connected for founder %s", founder_id)

    return RedirectResponse(url=f"{fe_base}/integrations?github_connected=1")


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

    import os as _os
    safe_name = Path(filename).name
    vault = _os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    search_dirs = [Path(vault) / "files", Path(vault), Path("/tmp/astra_docs")]
    path = None
    for d in search_dirs:
        candidate = d / safe_name
        if candidate.exists() and candidate.is_file():
            path = candidate
            break
    if path is None:
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


# ── Agent input request ───────────────────────────────────────────────────────

@router.post("/input/{session_id}/{request_id}")
async def submit_input(session_id: str, request_id: str, body: InputResponse):
    """
    Founder submits their response to an agent input request (e.g. personal info for LLC filing).
    The waiting agent picks this up and continues.
    """
    from backend.core.events import input_response_push, publish
    input_response_push(request_id, body.data)
    await publish(session_id, {"type": "agent_input_received", "request_id": request_id})
    return {"ok": True, "request_id": request_id}


@router.websocket("/llc/stream/{founder_id}")
async def llc_stream(websocket: WebSocket, founder_id: str, company_name: str = "", state: str = "Wyoming"):
    """
    WebSocket endpoint for live LLC filing.
    Playwright runs in a dedicated thread with its own ProactorEventLoop (required on Windows).
    Frames are relayed to the WebSocket via run_coroutine_threadsafe.
    Founder input is bridged via a thread-safe queue.Queue.
    """
    import sys
    import queue
    import threading

    await websocket.accept()
    main_loop = asyncio.get_running_loop()
    input_q: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    async def _send(msg: dict) -> None:
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    def run_in_thread():
        import asyncio as _aio
        import traceback as _tb
        # On Windows use ProactorEventLoop so Playwright can spawn Chromium
        if sys.platform == "win32":
            _loop = _aio.ProactorEventLoop()
        else:
            _loop = _aio.new_event_loop()
        _aio.set_event_loop(_loop)

        async def send_message(msg: dict) -> None:
            if stop_event.is_set():
                return
            future = asyncio.run_coroutine_threadsafe(_send(msg), main_loop)
            try:
                future.result(timeout=10)
            except Exception as e:
                logger.warning("send_message failed: %s", e)

        async def wait_input() -> dict | None:
            deadline = _aio.get_event_loop().time() + 600
            while _aio.get_event_loop().time() < deadline:
                try:
                    return input_q.get_nowait()
                except queue.Empty:
                    await _aio.sleep(0.3)
            return None

        try:
            from backend.tools.llc_filing import file_llc_live
            _loop.run_until_complete(file_llc_live(
                founder_id=founder_id,
                company_name=company_name or "My Company LLC",
                state=state,
                send_message=send_message,
                wait_input=wait_input,
            ))
        except Exception as e:
            err = _tb.format_exc()
            logger.error("LLC filing thread error: %s", err)
            future = asyncio.run_coroutine_threadsafe(
                _send({"type": "error", "message": str(e)}), main_loop
            )
            try: future.result(timeout=5)
            except Exception: pass

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    try:
        async for msg_text in websocket.iter_text():
            try:
                msg = json.loads(msg_text)
                if msg.get("type") == "founder_input":
                    input_q.put(msg.get("data", {}))
                elif msg.get("type") == "cancel":
                    stop_event.set()
                    break
            except Exception:
                pass
    except WebSocketDisconnect:
        stop_event.set()
    except Exception:
        stop_event.set()


# ── Generic Playwright WebSocket runner ───────────────────────────────────────

async def _run_playwright_ws(websocket: WebSocket, coro_fn) -> None:
    """
    Shared boilerplate for all live-browser WebSocket endpoints.
    Spawns a dedicated thread with its own event loop (required for Playwright on Windows).
    Bridges send_message / wait_input / event_q (mouse+key) across thread boundaries.
    """
    import sys
    import queue
    import threading

    await websocket.accept()
    main_loop = asyncio.get_running_loop()
    input_q: queue.Queue = queue.Queue()   # for founder_input (form submissions)
    event_q: queue.Queue = queue.Queue()   # for mouse_event / key_event (canvas interaction)
    stop_event = threading.Event()

    async def _send(msg: dict) -> None:
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    def run_in_thread():
        import asyncio as _aio
        _loop = _aio.ProactorEventLoop() if sys.platform == "win32" else _aio.new_event_loop()
        _aio.set_event_loop(_loop)

        async def send_message(msg: dict) -> None:
            if stop_event.is_set():
                return
            future = asyncio.run_coroutine_threadsafe(_send(msg), main_loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass

        async def wait_input() -> dict | None:
            deadline = _loop.time() + 600
            while _loop.time() < deadline:
                try:
                    return input_q.get_nowait()
                except queue.Empty:
                    await _aio.sleep(0.3)
            return None

        try:
            _loop.run_until_complete(coro_fn(send_message, wait_input, event_q))
        except Exception as e:
            future = asyncio.run_coroutine_threadsafe(
                _send({"type": "error", "message": str(e)}), main_loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    try:
        async for msg_text in websocket.iter_text():
            try:
                msg = json.loads(msg_text)
                mtype = msg.get("type")
                if mtype == "founder_input":
                    input_q.put(msg.get("data", {}))
                elif mtype in ("mouse_event", "mouse_move", "key_event"):
                    event_q.put(msg)
                elif mtype == "cancel":
                    stop_event.set()
                    break
            except Exception:
                pass
    except WebSocketDisconnect:
        stop_event.set()
    except Exception:
        stop_event.set()


# ── Integration connect WebSocket endpoints ───────────────────────────────────

@router.websocket("/connect/github/stream/{founder_id}")
async def connect_github_stream(websocket: WebSocket, founder_id: str):
    from backend.tools.integration_connect import connect_github_live
    await _run_playwright_ws(websocket, lambda sm, wi, eq: connect_github_live(founder_id, sm, wi, eq))


@router.websocket("/connect/vercel/stream/{founder_id}")
async def connect_vercel_stream(websocket: WebSocket, founder_id: str):
    from backend.tools.integration_connect import connect_vercel_live
    await _run_playwright_ws(websocket, lambda sm, wi, eq: connect_vercel_live(founder_id, sm, wi, eq))


@router.websocket("/connect/sendgrid/stream/{founder_id}")
async def connect_sendgrid_stream(websocket: WebSocket, founder_id: str):
    from backend.tools.integration_connect import connect_sendgrid_live
    await _run_playwright_ws(websocket, lambda sm, wi, eq: connect_sendgrid_live(founder_id, sm, wi, eq))


@router.get("/setup/composio/connected/{founder_id}")
async def composio_connected(founder_id: str):
    """Return per-app Composio connection status for the founder."""
    import asyncio
    from backend.tools.integration_connect import get_composio_app_status
    status = await asyncio.to_thread(get_composio_app_status, founder_id)
    return {"founder_id": founder_id, "apps": status}

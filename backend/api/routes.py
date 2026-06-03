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
    BillingCheckoutRequest,
    BillingPortalRequest,
    BrainRecordRequest,
    BrainIngestRequest,
    BrainAskRequest,
    BrainAccessRequest,
    BrainProposalRequest,
    BrainRecordRevisionRequest,
    BrainSyncConfigRequest,
    BrainSyncRequest,
    ContinueRequest,
    CustomStackRequest,
    GoalRequest,
    OrgControlsRequest,
    OrgMemberRequest,
    OrgSubscriptionRequest,
    OrgUsageRequest,
    RejectRequest,
    SetupRequest,
    SaveCredentialRequest,
    SessionAskRequest,
    StackApprovalDecisionRequest,
    StackPackageRequest,
    StackRecommendRequest,
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
from backend.tenant_auth import actor_or_body, require_founder_access, require_org_access

router = APIRouter()


async def _load_session_events(session_id: str) -> list[tuple[int, dict]]:
    from backend.core.events import _event_log, _restore_session

    if session_id not in _event_log:
        await asyncio.to_thread(_restore_session, session_id)
    return _event_log.get(session_id, [])


async def _session_founder_id(session_id: str) -> str:
    events = await _load_session_events(session_id)
    for _, event in events:
        founder_id = event.get("founder_id")
        if founder_id:
            return str(founder_id)
    try:
        from backend.workflow_state import load_session_state
        snapshot = await asyncio.to_thread(load_session_state, session_id)
        digest = (snapshot or {}).get("digest") or {}
        founder_id = digest.get("founder_id") or (snapshot or {}).get("founder_id")
        if founder_id:
            return str(founder_id)
    except Exception:
        pass
    return ""


async def _require_session_access(request: Request, session_id: str, min_role: str = "viewer") -> str:
    founder_id = await _session_founder_id(session_id)
    if founder_id:
        return require_founder_access(request, founder_id, min_role=min_role)
    return actor_or_body(request)


@router.get("/stacks")
async def stacks():
    from backend.stacks import list_stack_templates

    return {"stacks": list_stack_templates()}


@router.get("/agents/catalog")
async def agents_catalog():
    """Return the full catalog of all 6 specialist agents with tools, outputs, and dependencies."""
    from backend.stacks.catalog import get_agent_catalog

    return {"agents": get_agent_catalog()}


@router.post("/stacks/custom")
async def custom_stack_route(body: CustomStackRequest, request: Request):
    """Build a deployable stack package for a hand-picked subset of agents."""
    if body.founder_id:
        require_founder_access(request, body.founder_id, min_role="viewer")
    from backend.stacks.custom import build_custom_stack_package

    result = build_custom_stack_package(
        agents=body.agents,
        instruction=body.instruction,
        founder_id=body.founder_id or "",
        company_name=body.company_name,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Custom stack build failed"))
    return result


@router.post("/stacks/recommend")
async def recommend_stack_route(body: StackRecommendRequest):
    from backend.stacks import recommend_stack

    return recommend_stack(body.instruction, body.company_stage).to_public_dict()


@router.post("/stacks/package")
async def stack_package_route(body: StackPackageRequest, request: Request):
    if body.founder_id:
        require_founder_access(request, body.founder_id, min_role="viewer")
    from backend.stacks import build_goal_stack_package

    return build_goal_stack_package(
        instruction=body.instruction,
        founder_id=body.founder_id or "",
        company_stage=body.company_stage,
        company_name=body.company_name,
    )


@router.get("/stacks/{stack_id}/operating-plan")
async def stack_operating_plan_route(stack_id: str, goal: str = "", company_name: str = ""):
    from backend.stacks import build_stack_operating_plan, get_stack_template

    return build_stack_operating_plan(get_stack_template(stack_id), goal, company_name)


@router.get("/stacks/{stack_id}/execution-blueprint")
async def stack_execution_blueprint_route(stack_id: str, goal: str = "", company_name: str = ""):
    from backend.stacks import build_stack_execution_blueprint, get_stack_template

    return build_stack_execution_blueprint(get_stack_template(stack_id), goal, company_name)


@router.get("/stacks/{stack_id}/quality")
async def stack_quality_route(stack_id: str):
    from backend.stacks import audit_stack_template, get_stack_template

    return audit_stack_template(get_stack_template(stack_id))


@router.get("/stacks/{stack_id}/manifest")
async def stack_manifest_route(stack_id: str, goal: str = "", company_name: str = ""):
    from backend.stacks import build_stack_manifest, get_stack_template

    return build_stack_manifest(get_stack_template(stack_id), goal, company_name)


@router.get("/stacks/{stack_id}/readiness/{founder_id}")
async def stack_readiness_route(stack_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.stacks import stack_readiness

    return stack_readiness(founder_id, stack_id)


@router.get("/stacks/{stack_id}/connector-coverage/{founder_id}")
async def stack_connector_coverage_route(stack_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.connector_coverage import build_connector_coverage

    return build_connector_coverage(founder_id, stack_id)


@router.get("/stacks/{stack_id}/connector-setup/{founder_id}")
async def stack_connector_setup_route(stack_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.connector_setup import build_connector_setup_plan

    return build_connector_setup_plan(founder_id, stack_id)


@router.get("/stacks/{stack_id}/connector-validation/{founder_id}")
async def stack_connector_validation_route(stack_id: str, founder_id: str, request: Request, live: bool = False):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.connector_validation import validate_stack_connectors

    return validate_stack_connectors(founder_id, stack_id, live=live)


@router.post("/goal")
async def submit_goal(body: GoalRequest, request: Request):
    actor_id = require_founder_access(request, body.founder_id, min_role="operator")
    from backend.core.session_ids import new_session_id
    session_id = new_session_id()
    orch = get_orchestrator()
    try:
        from backend.accounts import get_or_create_org, record_usage
        org = get_or_create_org(body.founder_id)
        if org.get("entitlements", {}).get("remaining_runs", 0) <= 0:
            raise HTTPException(status_code=402, detail="Monthly run limit reached for this workspace.")
        record_usage(org["org_id"], actor_id=actor_id, runs=1)
    except HTTPException:
        raise
    except Exception as usage_exc:
        logger.warning("Usage accounting skipped: %s", usage_exc)

    # Credit check — scale plan gets unlimited, others need at least 1 credit to start
    from backend.credits.store import check_credits, get_balance
    from backend.accounts import get_or_create_org as _get_org
    _org = _get_org(body.founder_id)
    _plan = (_org or {}).get("plan", "starter")
    _unlimited = _plan in ("scale", "beta")
    if not _unlimited and get_balance(body.founder_id) < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Purchase more to continue.")
    constraints = dict(body.constraints or {})
    if body.stack_id:
        constraints["stack_id"] = body.stack_id
    constraints["unlimited_credits"] = _unlimited

    # Register session in durable store before launching
    try:
        from backend.core.session_store import register_session as _reg
        _reg(
            session_id=session_id,
            founder_id=body.founder_id,
            goal=body.instruction,
            stack_id=body.stack_id or "",
            company_name=str(constraints.get("company_name", "")),
            agents=list(constraints.get("agents", [])),
        )
    except Exception as _se:
        logger.warning("session_store.register_session failed: %s", _se)

    # Pre-create the SSE queue so the frontend can connect before the first event arrives.
    # Without this, stream_events sees an empty session and yields session_expired immediately.
    from backend.core.events import _get_queue as _pre_queue
    _pre_queue(session_id)

    async def _run():
        try:
            await orch.run(
                goal=body.instruction,
                founder_id=body.founder_id,
                constraints=constraints,
                session_id=session_id,
            )
        except Exception as e:
            logger.error("goal run error session=%s: %s", session_id, e, exc_info=True)
            try:
                await publish(session_id, {"type": "goal_error", "error": str(e)})
            except Exception:
                pass

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


@router.get("/sessions")
async def list_sessions(request: Request, founder_id: str = "", limit: int = 50):
    """List all sessions for a founder, newest first."""
    from backend.core.session_store import list_sessions as _ls
    return {"sessions": _ls(founder_id=founder_id or None, limit=limit)}


@router.get("/sessions/{session_id}/meta")
async def session_meta(session_id: str, request: Request):
    """Full session metadata from durable store."""
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found in store")
    return meta


@router.get("/sessions/{session_id}/replay")
async def replay_session(session_id: str, request: Request):
    """Stream the full event log for a session as SSE — rebuilds frontend from scratch."""
    from backend.core.session_store import load_events as _load
    from backend.core.events import _event_log, _fmt, _restore_session
    import asyncio as _asyncio

    # Load from JSONL or memory
    events = _event_log.get(session_id)
    if not events:
        events = await _asyncio.to_thread(_load, session_id)
    if not events:
        raise HTTPException(status_code=404, detail="Session events not found")

    async def _gen():
        for eid, ev in events:
            yield _fmt(eid, ev)
        yield _fmt(len(events) + 1, {"type": "replay_complete"})

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@router.get("/sessions/{session_id}/cost")
async def session_cost(session_id: str, request: Request):
    """Token usage and estimated USD cost for a session."""
    from backend.core.usage import get_session_cost
    return get_session_cost(session_id)


@router.get("/cost")
async def all_cost(request: Request):
    """Aggregate token usage and cost across all sessions (admin)."""
    from backend.core.usage import get_all_sessions_cost
    return get_all_sessions_cost()


@router.get("/sessions/{session_id}/digest")
async def session_digest(session_id: str, request: Request):
    from backend.session_digest import build_session_digest

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session event log not found")
    return build_session_digest(session_id, events)


@router.get("/sessions/{session_id}/subteam-report")
async def session_subteam_report(session_id: str, request: Request, team: str = "engineering"):
    from backend.session_digest import build_subteam_report

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session event log not found")
    return build_subteam_report(session_id, events, team)


@router.get("/sessions/{session_id}/workboard")
async def session_workboard(session_id: str, request: Request):
    from backend.workboard import build_session_workboard

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session event log not found")
    return build_session_workboard(session_id, events)


@router.get("/sessions/{session_id}/completion-audit")
async def session_completion_audit(session_id: str, request: Request):
    from backend.run_completion_audit import build_run_completion_audit
    from backend.workflow_state import build_session_state, load_session_state

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    state = build_session_state(session_id, events) if events else await asyncio.to_thread(load_session_state, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session state not found")
    return build_run_completion_audit(session_id, state)


@router.get("/sessions/{session_id}/state")
async def session_state(session_id: str, request: Request):
    from backend.workflow_state import build_session_state, load_session_state

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if events:
        return build_session_state(session_id, events)
    snapshot = await asyncio.to_thread(load_session_state, session_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="session state not found")
    return snapshot


@router.post("/sessions/{session_id}/rerun/{agent_name}")
async def rerun_agent(session_id: str, agent_name: str, body: dict, request: Request):
    """Rerun a specific agent within an existing session, picking up all prior context."""
    from backend.core.agent import AgentContext
    from backend.core.factory import get_orchestrator
    from backend.core.events import publish
    import asyncio

    founder_id = body.get("founder_id", "")
    instruction = body.get("instruction", "")
    await _require_session_access(request, session_id, min_role="viewer")

    orch = get_orchestrator()
    agent = orch.specialists.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found. Available: {sorted(orch.specialists.keys())}")

    # Load prior research/context from obsidian vault
    vault_context = ""
    try:
        from backend.tools.obsidian_logger import format_vault_context
        vault_context = format_vault_context(agent_name, 5, founder_id)
    except Exception:
        pass

    # Use provided instruction or fall back to a sensible default
    if not instruction:
        instruction = f"Redo your full workflow for the session. Use any research already in context."

    ctx = AgentContext(
        goal=instruction,
        founder_id=founder_id,
        session_id=session_id,
        shared={"prior_vault_notes": vault_context, "rerun": True},
    )

    await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": f"rerun_{agent_name}", "instruction": instruction})

    async def _run():
        try:
            result = await agent.run(ctx)
            await publish(session_id, {"type": "agent_done", "agent": agent_name, "task_id": f"rerun_{agent_name}", "result": result})
        except Exception as e:
            await publish(session_id, {"type": "agent_error", "agent": agent_name, "task_id": f"rerun_{agent_name}", "error": str(e)})

    asyncio.create_task(_run())
    return {"ok": True, "session_id": session_id, "agent": agent_name, "status": "started"}


@router.post("/sessions/{session_id}/ask")
async def ask_session(session_id: str, body: SessionAskRequest, request: Request):
    from backend.session_digest import answer_session_question

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session event log not found")
    return answer_session_question(session_id, events, body.question)


@router.post("/approve")
async def approve_task(body: ApproveRequest):
    await update_task_status(body.task_id, "approved")
    return {"task_id": body.task_id, "status": "approved"}


@router.post("/reject")
async def reject_task(body: RejectRequest):
    await update_task_status(body.task_id, "rejected")
    return {"task_id": body.task_id, "status": "rejected", "reason": body.reason}


@router.post("/stack/approval")
async def decide_stack_approval(body: StackApprovalDecisionRequest, request: Request):
    actor_id = require_founder_access(request, body.founder_id, min_role="admin") if body.founder_id else actor_or_body(request)
    decision = body.decision.lower().strip()
    if decision not in {"approved", "skipped", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be 'approved', 'skipped', or 'rejected'")
    from backend.approval_workflows import decide_approval_request
    from backend.core.events import approval_decision_push
    workflow = decide_approval_request(
        body.session_id,
        body.gate_key,
        decision,
        request_id=body.request_id,
        actor_id=actor_id,
        actor_role="owner",
        note=body.note,
    )
    if not workflow.get("ok"):
        raise HTTPException(status_code=400, detail=workflow.get("error") or "approval decision failed")
    if body.founder_id:
        try:
            from backend.accounts import record_usage
            record_usage(body.founder_id, actor_id=actor_id, approval_decisions=1)
        except Exception as usage_exc:
            logger.warning("Approval usage accounting skipped: %s", usage_exc)
    event = {
        "type": "stack_approval_decision",
        "gate_key": body.gate_key,
        "decision": decision,
        "founder_id": body.founder_id or actor_id,
        "note": body.note,
        "workflow": workflow,
    }
    approval_decision_push(body.session_id, body.gate_key, event)
    await publish(body.session_id, event)
    return {"ok": True, "session_id": body.session_id, "gate_key": body.gate_key, "decision": decision}


@router.get("/orgs")
async def orgs(request: Request):
    actor_id = actor_or_body(request)
    from backend.accounts import list_orgs, list_orgs_for_user
    return {"orgs": list_orgs() if actor_id == "local_dev" else list_orgs_for_user(actor_id)}


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, request: Request, founder_id: str = ""):
    require_org_access(request, org_id, min_role="viewer")
    from backend.accounts import get_or_create_org
    return get_or_create_org(founder_id or org_id, org_id)


@router.post("/orgs/{org_id}/members")
async def org_member(org_id: str, body: OrgMemberRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="admin")
    from backend.accounts import upsert_member
    return upsert_member(org_id, actor_id=actor_id, user_id=body.user_id, role=body.role, status=body.status)


@router.post("/orgs/{org_id}/subscription")
async def org_subscription(org_id: str, body: OrgSubscriptionRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="owner")
    from backend.accounts import update_subscription
    return update_subscription(
        org_id,
        actor_id=actor_id,
        plan=body.plan,
        status=body.status,
        stripe_customer_id=body.stripe_customer_id,
        stripe_subscription_id=body.stripe_subscription_id,
        current_period_end=body.current_period_end,
    )


@router.post("/orgs/{org_id}/controls")
async def org_controls(org_id: str, body: OrgControlsRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="admin")
    from backend.accounts import update_admin_controls
    return update_admin_controls(org_id, actor_id=actor_id, controls=body.controls)


@router.post("/orgs/{org_id}/usage")
async def org_usage(org_id: str, body: OrgUsageRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="admin")
    from backend.accounts import record_usage
    return record_usage(
        org_id,
        actor_id=actor_id,
        runs=body.runs,
        connector_syncs=body.connector_syncs,
        approval_decisions=body.approval_decisions,
    )


@router.get("/orgs/{org_id}/billing")
async def org_billing_status(org_id: str, request: Request):
    require_org_access(request, org_id, min_role="viewer")
    from backend.billing import billing_config_status
    from backend.accounts import get_or_create_org
    return {"org": get_or_create_org(org_id, org_id), "billing": billing_config_status()}


@router.post("/orgs/{org_id}/billing/checkout")
async def org_billing_checkout(org_id: str, body: BillingCheckoutRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="owner")
    from backend.billing import create_checkout_session
    try:
        return create_checkout_session(
            org_id,
            actor_id=actor_id,
            plan=body.plan,
            success_url=body.success_url or "",
            cancel_url=body.cancel_url or "",
            customer_email=body.customer_email or "",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/orgs/{org_id}/billing/portal")
async def org_billing_portal(org_id: str, body: BillingPortalRequest, request: Request):
    actor_id = require_org_access(request, org_id, min_role="owner")
    from backend.billing import create_customer_portal_session
    try:
        return create_customer_portal_session(org_id, actor_id=actor_id, return_url=body.return_url or "")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/approvals")
async def session_approval_workflow(session_id: str, request: Request):
    await _require_session_access(request, session_id, min_role="viewer")
    from backend.approval_workflows import get_approval_workflow
    return get_approval_workflow(session_id)


def _detect_rerun_intent(instruction: str, available_agents: list[str]) -> dict | None:
    """Use LLM to detect if the message is an agent action request.
    Returns {agent, instruction, tools_only} or None if it's a general chat message.
    """
    try:
        import openai, json as _json
        from backend.config import settings
        client = openai.OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        )
        agents_list = ", ".join(available_agents)
        resp = client.chat.completions.create(
            model=settings.or_planner_model,
            messages=[
                {"role": "system", "content": (
                    f"You are a chat intent classifier for an AI startup assistant. Available agents: {agents_list}.\n\n"
                    "Classify the user's message and return JSON:\n\n"
                    "IF the message asks an agent to do something (run, redo, fix, change, generate, update, make, add, remove anything):\n"
                    '{"intent":"agent_action","agent":"<name>","instruction":"<complete precise instruction for the agent>","scope":"full"|"partial"}\n'
                    "- scope=partial if they only want ONE thing changed (e.g. 'make the logo a star' → only regenerate logo, skip rest)\n"
                    "- scope=full if they want the whole agent rerun\n"
                    "- instruction must be a complete, specific task the agent can execute\n\n"
                    "IF the message is a question or general chat (not asking an agent to do something):\n"
                    '{"intent":"chat"}\n\n'
                    "Agent mapping: logo/design/colors/wireframe/brand → design | landing page/website/deploy → web | "
                    "marketing/ads/tiktok/instagram/email → marketing | legal/privacy/terms/docs → legal | "
                    "code/mvp/technical/build/app → technical | sales/leads/outreach → sales | "
                    "fundraise/investors/ops/pitch → ops | research/market/competitors → research\n\n"
                    "For scope=partial, instruction must tell the agent to ONLY do that one thing and skip everything else.\n"
                    "Example: 'make the logo a star' → agent=design, scope=partial, "
                    'instruction="Regenerate ONLY the logo. Call generate_logo twice: once with style=wordmark and once with style=icon. '
                    'For both, use a star geometric motif in the icon shape. Use the existing brand colors from your previous run. '
                    'Skip color_palette, design_spec, wireframes, and brand_image — only regenerate logos. Call done with {logo_wordmark, logo_icon}."\n\n'
                    "Output ONLY valid JSON. No prose."
                )},
                {"role": "user", "content": instruction},
            ],
            max_tokens=300,
            temperature=0,
            timeout=15.0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown fences
        import re as _re
        raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        parsed = _json.loads(raw)
        if parsed.get("intent") == "agent_action" and parsed.get("agent") in available_agents:
            return {
                "agent": parsed["agent"],
                "instruction": parsed.get("instruction", ""),
                "scope": parsed.get("scope", "full"),
            }
        if parsed.get("intent") == "chat":
            return None
    except Exception as e:
        logger.debug("rerun intent detection failed: %s", e)
    return None


@router.post("/goal/continue")
async def continue_goal(body: ContinueRequest, request: Request):
    """Run follow-up tasks on an existing company session with full vault context."""
    require_founder_access(request, body.founder_id, min_role="operator")
    from backend.core.session_ids import new_session_id
    orch = get_orchestrator()

    # Detect rerun intent via LLM — no regex
    rerun = await asyncio.to_thread(
        _detect_rerun_intent, body.instruction, list(orch.specialists.keys())
    )
    if rerun:
        # Rerun a specific agent in the prior session
        session_id = body.prior_session_id or new_session_id()
        agent_name = rerun["agent"]
        instruction = rerun["instruction"] or f"Redo your full workflow with all available context."

        vault_context = ""
        try:
            from backend.tools.obsidian_logger import format_vault_context
            vault_context = await asyncio.to_thread(format_vault_context, agent_name, 5, body.founder_id)
        except Exception:
            pass

        from backend.core.agent import AgentContext
        ctx = AgentContext(
            goal=instruction,
            founder_id=body.founder_id,
            session_id=session_id,
            shared={"prior_vault_notes": vault_context, "rerun": True},
        )
        agent = orch.specialists[agent_name]
        await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": f"rerun_{agent_name}", "instruction": instruction})
        await publish(session_id, {"type": "chat_intent", "intent": "rerun", "agent": agent_name})

        async def _rerun():
            try:
                result = await agent.run(ctx)
                await publish(session_id, {"type": "agent_done", "agent": agent_name, "task_id": f"rerun_{agent_name}", "result": result})
                await publish(session_id, {"type": "goal_done", "results": {agent_name: result}})
            except Exception as e:
                await publish(session_id, {"type": "agent_error", "agent": agent_name, "error": str(e)})

        asyncio.create_task(_rerun())
        return {"session_id": session_id, "status": "running", "prior_session_id": body.prior_session_id, "rerun": agent_name}

    session_id = new_session_id()

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
async def ask_agent(body: AskRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="viewer")
    from backend.core.agent import AgentContext
    from backend.core.session_ids import new_session_id

    orch = get_orchestrator()
    agent = orch.specialists.get(body.target_agent)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{body.target_agent}' not found. Available: {list(orch.specialists.keys())}")

    ctx = AgentContext(
        goal=body.question,
        founder_id=body.founder_id,
        session_id=f"ask_{new_session_id()}",
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
async def chat_agent(agent_key: str, body: AskRequest, request: Request):
    """
    Lightweight single-turn chat with a specific agent.
    Injects company brain snippets, Obsidian vault notes, and session
    context so the agent answers with full knowledge of the company.
    """
    import re as _re
    import openai as _openai
    from backend.config import settings

    require_founder_access(request, body.founder_id, min_role="viewer")
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
async def steer_session(body: SteerRequest, request: Request):
    """Inject a founder directive into a running session."""
    from backend.core.events import publish, steer_push
    await _require_session_access(request, body.session_id, min_role="operator")
    steer_push(body.session_id, body.message)
    await publish(body.session_id, {
        "type": "founder_steer",
        "message": body.message,
    })
    return {"ok": True, "session_id": body.session_id}


@router.post("/steer/{session_id}")
async def steer_session_path(session_id: str, body: dict, request: Request):
    """Path-param variant — frontend sends POST /steer/{session_id} with {message} body."""
    from backend.core.events import publish, steer_push
    await _require_session_access(request, session_id, min_role="operator")
    message = body.get("message", "")
    steer_push(session_id, message)
    await publish(session_id, {
        "type": "founder_steer",
        "message": message,
    })
    return {"ok": True, "session_id": session_id}


@router.post("/setup")
async def setup_accounts(body: SetupRequest, request: Request):
    """
    Provision GitHub, Vercel, SendGrid accounts from email+password.
    Returns status per service + OAuth URLs for Instagram/TikTok/Meta.
    """
    require_founder_access(request, body.founder_id, min_role="admin")
    from backend.provisioning.account_provisioner import provision_all
    result = await provision_all(
        founder_id=body.founder_id,
        email=body.email,
        password=body.password,
        base_url=body.base_url,
    )
    return result


@router.post("/setup/service")
async def save_service_credential(body: SaveCredentialRequest, request: Request):
    """Save a manually entered credential (GitHub PAT, SendGrid key, Vercel token)."""
    require_founder_access(request, body.founder_id, min_role="admin")
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
async def get_brain(founder_id: str, request: Request, viewer_id: str = ""):
    """Return the founder's normalized company brain graph."""
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import get_company_brain
    return get_company_brain(founder_id, viewer_id or actor_id)


@router.post("/brain/{founder_id}/sync")
async def sync_brain(founder_id: str, body: BrainSyncRequest, request: Request):
    """Sync connected sources and local agent vault notes into the company brain."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import sync_company_brain
    result = await asyncio.to_thread(sync_company_brain, founder_id, body.sources)
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=actor_id, connector_syncs=len(body.sources or []))
    except Exception as usage_exc:
        logger.warning("Connector sync usage accounting skipped: %s", usage_exc)
    return result


@router.get("/brain/{founder_id}/search")
async def search_brain(founder_id: str, request: Request, q: str, limit: int = 8, viewer_id: str = ""):
    """Search company brain records for human UI and agent context."""
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import search_company_brain
    return search_company_brain(founder_id, q, limit, viewer_id or actor_id)


@router.get("/brain/{founder_id}/agent-context")
async def brain_agent_context(founder_id: str, request: Request, q: str, limit: int = 8, viewer_id: str = ""):
    """Compact graph context for IDE/MCP/external agents."""
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import company_brain_agent_context
    return company_brain_agent_context(founder_id, q, limit, viewer_id or actor_id)


@router.post("/brain/{founder_id}/ask")
async def ask_brain(founder_id: str, body: BrainAskRequest, request: Request):
    """Return a cited answer synthesized from matched company-brain records."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import ask_company_brain
    return ask_company_brain(founder_id, body.question, body.limit)


@router.get("/brain/{founder_id}/subteam-report")
async def brain_subteam_report(founder_id: str, request: Request, team: str = "engineering", days: int = 7):
    """Report subteam activity from persisted Company Brain memory."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.company_reports import build_company_subteam_report, persist_company_subteam_report
    report = build_company_subteam_report(founder_id, team, days)
    await asyncio.to_thread(persist_company_subteam_report, report)
    return report


@router.post("/brain/{founder_id}/records")
async def add_brain_record(founder_id: str, body: BrainRecordRequest, request: Request):
    """Add a manual or app-sourced record to the company brain."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
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
        owner_id=body.owner_id or actor_id,
        visibility=body.visibility,
        allowed_roles=body.allowed_roles,
        metadata=body.metadata,
    )


@router.post("/brain/{founder_id}/records/{record_id}/revise")
async def revise_brain_record(founder_id: str, record_id: str, body: BrainRecordRevisionRequest, request: Request):
    """Create a new version of a Company Brain record and deprecate the prior version."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    from backend.tools.company_brain import revise_company_brain_record
    return revise_company_brain_record(
        founder_id=founder_id,
        record_id=record_id,
        title=body.title,
        content=body.content,
        canonical=body.canonical,
        stale_risk=body.stale_risk,
        editor_id=body.editor_id or actor_id,
    )


@router.post("/brain/{founder_id}/access")
async def configure_brain_access(founder_id: str, body: BrainAccessRequest, request: Request):
    """Configure Company Brain team roles and permission grants."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.tools.company_brain import configure_company_brain_access
    return configure_company_brain_access(
        founder_id=founder_id,
        roles=body.roles,
        role_permissions=body.role_permissions,
    )


@router.post("/brain/{founder_id}/ingest")
async def ingest_brain_records(founder_id: str, body: BrainIngestRequest, request: Request):
    """Bulk-ingest normalized records from connector/webhook payloads."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import ingest_company_brain_records
    result = await asyncio.to_thread(
        ingest_company_brain_records,
        founder_id,
        body.source,
        body.records,
    )
    try:
        from backend.connector_sync_ledger import record_connector_sync
        record_connector_sync(
            founder_id,
            body.source,
            status="ok" if result.get("ok") else "error",
            imported=int(result.get("ingested") or 0),
            changed_records=int(result.get("changed_records") or 0),
            error=str(result.get("error") or ""),
            mode="ingest",
        )
    except Exception as ledger_exc:
        logger.warning("Connector ingest ledger accounting skipped: %s", ledger_exc)
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=actor_id, connector_syncs=1)
    except Exception as usage_exc:
        logger.warning("Connector ingest usage accounting skipped: %s", usage_exc)
    return result


@router.post("/brain/{founder_id}/webhooks/{source}")
async def connector_brain_webhook(founder_id: str, source: str, request: Request):
    """Receive provider webhooks and ingest normalized updates into Company Brain."""
    from backend.connector_webhooks import ingest_connector_webhook, parse_verified_connector_webhook

    payload, verification = await parse_verified_connector_webhook(request, founder_id, source)
    if payload.get("type") == "url_verification" and payload.get("challenge") is not None:
        return {"ok": True, "source": source, "challenge": payload["challenge"], "verification": verification}
    event_id = request.headers.get("x-astra-event-id") or request.headers.get("x-github-delivery") or request.headers.get("x-slack-request-timestamp") or ""
    result = await asyncio.to_thread(ingest_connector_webhook, founder_id, source, payload, event_id)
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=f"{source}_webhook", connector_syncs=1)
    except Exception as usage_exc:
        logger.warning("Connector webhook usage accounting skipped: %s", usage_exc)
    return {**result, "verification": verification}


@router.post("/brain/{founder_id}/import")
async def import_brain_sources(founder_id: str, body: BrainSyncRequest, request: Request):
    """Import actual records from connected providers into the company brain."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain_connectors import import_company_brain_sources
    result = await asyncio.to_thread(
        import_company_brain_sources,
        founder_id,
        body.sources,
        body.limit,
    )
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=actor_id, connector_syncs=len(result.get("imported_sources", [])))
    except Exception as usage_exc:
        logger.warning("Connector import usage accounting skipped: %s", usage_exc)
    return result


@router.get("/brain/{founder_id}/sync/status")
async def brain_sync_status(founder_id: str, request: Request):
    """Return continuous sync settings and recent run history."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import get_company_brain_sync_status
    return get_company_brain_sync_status(founder_id)


@router.post("/brain/{founder_id}/sync/config")
async def configure_brain_sync(founder_id: str, body: BrainSyncConfigRequest, request: Request):
    """Configure continuous sync for connected providers."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.tools.company_brain import configure_company_brain_sync
    return configure_company_brain_sync(
        founder_id=founder_id,
        enabled=body.enabled,
        sources=body.sources,
        interval_minutes=body.interval_minutes,
    )


@router.post("/brain/{founder_id}/sync/run")
async def run_brain_sync(founder_id: str, body: BrainSyncRequest, request: Request):
    """Run continuous-sync import now, regardless of schedule."""
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import configure_company_brain_sync, run_company_brain_sync
    if body.sources:
        configure_company_brain_sync(founder_id, enabled=True, sources=body.sources, interval_minutes=60)
    result = await asyncio.to_thread(run_company_brain_sync, founder_id, True)
    try:
        from backend.accounts import record_usage
        imported = (((result.get("import") or {}).get("imported_sources")) or [])
        record_usage(founder_id, actor_id=actor_id, connector_syncs=len(imported))
    except Exception as usage_exc:
        logger.warning("Continuous sync usage accounting skipped: %s", usage_exc)
    return result


@router.get("/brain/scheduler/status")
async def brain_scheduler_status(request: Request):
    """Return process-local company-brain scheduler status."""
    actor_or_body(request)
    from backend.tools.company_brain_scheduler import get_company_brain_scheduler_status
    return get_company_brain_scheduler_status()


@router.post("/brain/scheduler/run-due")
async def run_due_brain_syncs(request: Request):
    """Run all currently due company-brain sync jobs."""
    actor_or_body(request)
    import asyncio
    from backend.tools.company_brain import run_due_company_brain_syncs
    return await asyncio.to_thread(run_due_company_brain_syncs)


@router.post("/brain/{founder_id}/maintain")
async def maintain_brain(founder_id: str, request: Request):
    """Run drift, canonical-gap, and contradiction detection."""
    require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import maintain_company_brain
    return await asyncio.to_thread(maintain_company_brain, founder_id)


@router.post("/brain/{founder_id}/proposals/{proposal_id}")
async def update_brain_proposal(founder_id: str, proposal_id: str, body: BrainProposalRequest, request: Request):
    """Update a maintenance proposal status."""
    require_founder_access(request, founder_id, min_role="operator")
    from backend.tools.company_brain import resolve_company_brain_proposal
    return resolve_company_brain_proposal(founder_id, proposal_id, body.status)


# ── Stripe Standard Connect ───────────────────────────────────────────────────

@router.get("/stripe/oauth-url/{founder_id}")
async def stripe_oauth_url(founder_id: str, request: Request, email: str = "", frontend_base: str = "http://localhost:3003"):
    """
    Return the Stripe OAuth URL to send the founder to connect/create their Stripe account.
    The redirect_uri points back to this backend's /stripe/callback endpoint.
    """
    require_founder_access(request, founder_id, min_role="admin")
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
async def stripe_status(founder_id: str, request: Request):
    """Check if the founder has connected Stripe and whether their account is active."""
    require_founder_access(request, founder_id, min_role="viewer")
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
async def stripe_data(founder_id: str, request: Request):
    """Return live balance, charges, payouts, and revenue metrics from the founder's Stripe account."""
    require_founder_access(request, founder_id, min_role="viewer")
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
async def stripe_upgrade_ein(founder_id: str, body: StripeEINUpgradeRequest, request: Request):
    """
    Record that the founder has upgraded their Stripe account to their LLC/EIN.
    With Standard Connect the founder updates Stripe directly — this marks it complete in Astra.
    TODO: Auto-trigger this after NWRA LLC filing + IRS EIN confirmation.
    """
    require_founder_access(request, founder_id, min_role="admin")
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
async def github_oauth_url(founder_id: str, request: Request):
    """Return the GitHub OAuth authorization URL."""
    require_founder_access(request, founder_id, min_role="admin")
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
async def get_setup_status(founder_id: str, request: Request):
    """Returns which services are connected for this founder."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.provisioning.account_provisioner import get_founder_setup_status
    return await get_founder_setup_status(founder_id)


@router.post("/setup/auto-connect/{founder_id}")
async def auto_connect_integrations(founder_id: str, request: Request):
    """
    Apply all available platform credentials for this founder and return
    deterministic per-service auto-connect status.
    """
    require_founder_access(request, founder_id, min_role="admin")
    from backend.provisioning.integration_automation import auto_connect_status
    return auto_connect_status(founder_id, apply=True)


@router.get("/setup/auto-connect/{founder_id}")
async def get_auto_connect_status(founder_id: str, request: Request):
    """Preview per-service automation status without applying changes."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.provisioning.integration_automation import auto_connect_status
    return auto_connect_status(founder_id, apply=False)


@router.get("/setup/composio/connect/{founder_id}")
async def composio_connect(founder_id: str, request: Request, apps: str = "github,gmail,linkedin,googlecalendar,notion,linear"):
    """
    Returns Composio OAuth URLs for the requested apps.
    Founder clicks each URL to authenticate — Composio stores tokens mapped to founder_id.
    apps: comma-separated list, defaults to all supported apps.
    """
    require_founder_access(request, founder_id, min_role="admin")
    import asyncio
    from backend.tools.composio_tools import connect_founder_tools
    app_list = [a.strip() for a in apps.split(",") if a.strip()]
    result = await asyncio.to_thread(connect_founder_tools, founder_id, app_list)
    return {"founder_id": founder_id, "oauth_urls": result}


@router.get("/vault/{founder_id}")
async def get_vault_sessions(founder_id: str, request: Request):
    """List all sessions for a founder with per-agent note summaries."""
    require_founder_access(request, founder_id, min_role="viewer")
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
async def get_vault_note(founder_id: str, request: Request, session_id: str, agent: str):
    """Return full markdown content of one agent note."""
    require_founder_access(request, founder_id, min_role="viewer")
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


@router.post("/webhooks/stripe")
async def platform_stripe_webhook(request: Request):
    """Stripe webhook for Astra workspace subscriptions and entitlements."""
    from backend.config import settings
    from backend.billing import apply_platform_billing_event, verify_stripe_signature

    body = await request.body()
    signature = request.headers.get("stripe-signature", "")
    if settings.stripe_webhook_secret and not verify_stripe_signature(body, signature, settings.stripe_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Stripe signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    result = apply_platform_billing_event(payload)
    logger.info("platform stripe webhook: %s handled=%s", payload.get("type"), result.get("handled"))
    return result


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
async def create_product(founder_id: str, body: StripeProductRequest, request: Request):
    """Create a Stripe product + price + payment link for the founder."""
    require_founder_access(request, founder_id, min_role="admin")
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
async def list_products(founder_id: str, request: Request):
    """List all Stripe products with prices and payment links."""
    require_founder_access(request, founder_id, min_role="viewer")
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
async def register_webhook(founder_id: str, body: StripeWebhookRegisterRequest, request: Request):
    """Register a Stripe webhook endpoint for the founder's account."""
    require_founder_access(request, founder_id, min_role="admin")
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
    from backend.billing import verify_stripe_signature

    body = await request.body()
    creds = load_credentials(founder_id, "stripe") or {}
    webhook_secret = creds.get("webhook_secret") or ""
    if webhook_secret and not verify_stripe_signature(body, request.headers.get("stripe-signature", ""), webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.")
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
    try:
        from backend.connector_sync_ledger import record_connector_webhook
        record_connector_webhook(
            founder_id,
            "stripe",
            event_id=event.get("id", ""),
            event_type=event_type,
            changed_records=1,
            cursor=str(payload.get("created") or event.get("id") or ""),
        )
    except Exception as ledger_exc:
        logger.warning("Stripe webhook connector ledger skipped: %s", ledger_exc)
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
async def stripe_events(founder_id: str, request: Request, limit: int = 20):
    """Return recent Stripe webhook events/alerts for the founder."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.stripe_tools import get_webhook_events
    return {"events": get_webhook_events(founder_id, limit)}


# ── Agent input request ───────────────────────────────────────────────────────

@router.post("/input/{session_id}/{request_id}")
async def submit_input(session_id: str, request_id: str, body: InputResponse, request: Request):
    """
    Founder submits their response to an agent input request (e.g. personal info for LLC filing).
    The waiting agent picks this up and continues.
    """
    from backend.core.events import input_response_push, publish
    await _require_session_access(request, session_id, min_role="operator")
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
                    data = msg.get("data", {})
                    if data.get("ssn"):
                        from backend.core.pii_vault import record_ssn_receipt
                        record_ssn_receipt(founder_id, session_id=None)
                    input_q.put(data)
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
async def composio_connected(founder_id: str, request: Request):
    """Return per-app Composio connection status for the founder."""
    require_founder_access(request, founder_id, min_role="viewer")
    import asyncio
    from backend.tools.integration_connect import get_composio_app_status
    status = await asyncio.to_thread(get_composio_app_status, founder_id)
    return {"founder_id": founder_id, "apps": status}


# ── Outreach tool ─────────────────────────────────────────────────────────────

@router.get("/outreach/search/people")
async def outreach_search_people(
    request: Request,
    founder_id: str,
    titles: str = "",
    seniorities: str = "",
    locations: str = "",
    industries: str = "",
    company_sizes: str = "",
    funding_stages: str = "",
    domains_include: str = "",
    domains_exclude: str = "",
    keywords: str = "",
    page: int = 1,
    per_page: int = 25,
):
    """
    Search contacts. Priority:
      1. Local Supabase DB (free, instant)
      2. Apollo API (if available on plan)
      3. Web scraping fallback
    """
    require_founder_access(request, founder_id, min_role="viewer")

    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    titles_list = _split(titles)
    seniorities_list = _split(seniorities)
    locations_list = _split(locations)
    industries_list = _split(industries)
    sizes_list = _split(company_sizes)
    domains_inc = _split(domains_include)
    domains_exc = _split(domains_exclude)
    keywords_list = _split(keywords)

    # 1. Query local DB first
    from backend.tools.contact_scraper import search_local_contacts
    local = await asyncio.to_thread(
        search_local_contacts,
        founder_id=founder_id,
        titles=titles_list or None,
        industries=industries_list or None,
        locations=locations_list or None,
        company_sizes=sizes_list or None,
        seniorities=seniorities_list or None,
        page=page,
        limit=per_page,
    )
    if local["contacts"]:
        from backend.tools.contact_seeder import is_seeding
        return {**local, "source": "local_db", "seeding": is_seeding(founder_id)}

    # Kick off the global Hunter seed if pool is empty
    from backend.tools.contact_seeder import seed_contact_database, is_seeding, GLOBAL_FOUNDER_ID
    if not is_seeding(founder_id):
        try:
            db = get_supabase()
            global_count = db.table("outreach_contacts").select("id", count="exact").eq(
                "founder_id", GLOBAL_FOUNDER_ID
            ).limit(1).execute()
            if (global_count.count or 0) == 0:
                import threading
                threading.Thread(target=seed_contact_database, daemon=True).start()
                logger.info("[outreach] Auto-seeding global Hunter contact pool from search")
        except Exception:
            pass

    # 2. Try Apollo
    try:
        from backend.tools.apollo_tools import apollo_search_people
        result = await asyncio.to_thread(
            apollo_search_people,
            titles=titles_list,
            seniorities=seniorities_list,
            locations=locations_list,
            industries=industries_list,
            company_sizes=sizes_list,
            funding_stages=_split(funding_stages),
            domains_include=domains_inc,
            domains_exclude=domains_exc,
            keywords=keywords_list,
            page=page,
            per_page=per_page,
        )
        if result.get("contacts") and "error" not in result:
            # Cache results in local DB for next time
            asyncio.create_task(asyncio.to_thread(
                _store_contacts_background, founder_id, result["contacts"]
            ))
            return {**result, "source": "apollo"}
    except Exception as e:
        logger.warning("Apollo search failed, falling back to scraper: %s", e)

    # 3. If seeding is running, return empty + seeding flag so UI shows spinner
    if is_seeding(founder_id):
        return {"contacts": [], "total": 0, "page": page, "source": "seeding", "seeding": True}

    # 4. Web scraping fallback (quick single-query scrape)
    from backend.tools.contact_scraper import discover_via_web_search
    scraped = await asyncio.to_thread(
        discover_via_web_search,
        titles=titles_list or ["founder", "CEO"],
        industries=industries_list or None,
        locations=locations_list or None,
        limit=per_page,
    )
    if scraped:
        asyncio.create_task(asyncio.to_thread(
            _store_contacts_background, founder_id, scraped
        ))
    return {"contacts": scraped, "total": len(scraped), "page": page, "source": "scraper", "seeding": False}


def _store_contacts_background(founder_id: str, contacts: list[dict]) -> None:
    """Fire-and-forget: cache contacts in local DB."""
    try:
        from backend.db.client import get_supabase
        db = get_supabase()
        rows = [{
            "founder_id": founder_id,
            "email": c.get("email", ""),
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "title": c.get("title", ""),
            "company_name": c.get("company_name", ""),
            "company_domain": c.get("company_domain", ""),
            "linkedin_url": c.get("linkedin_url", ""),
            "city": c.get("city", ""),
            "country": c.get("country", ""),
            "industry": c.get("company_industry", c.get("industry", "")),
            "company_size": c.get("company_size", ""),
            "seniority": c.get("seniority", ""),
            "source": c.get("source", "api"),
        } for c in contacts if c.get("email")]
        if rows:
            db.table("outreach_contacts").upsert(
                rows, on_conflict="founder_id,email", ignore_duplicates=True
            ).execute()
    except Exception as e:
        logger.warning("Background contact store failed: %s", e)


@router.post("/outreach/discover/{founder_id}")
async def discover_contacts(founder_id: str, body: dict, request: Request):
    """
    Trigger bulk contact discovery from free sources (web search, GitHub,
    HackerNews, website scraping) and store results in the local database.
    """
    require_founder_access(request, founder_id, min_role="operator")
    from backend.tools.contact_scraper import bulk_discover_and_store

    result = await asyncio.to_thread(
        bulk_discover_and_store,
        founder_id=founder_id,
        titles=body.get("titles"),
        industries=body.get("industries"),
        locations=body.get("locations"),
        domains=body.get("domains"),
        github_orgs=body.get("github_orgs"),
        hn_keyword=body.get("hn_keyword", ""),
        limit_per_source=body.get("limit_per_source", 50),
    )
    return result


@router.post("/outreach/find-contacts/{founder_id}")
async def find_contacts_for_audience(founder_id: str, body: dict, request: Request):
    """
    Main outreach entry point. Takes a plain-English target audience description,
    searches the web for matching companies, runs Hunter domain search on each,
    and stores all contacts in the founder's outreach_contacts table.

    Body: { "target_audience": "restaurant owners in the US", "limit": 10 }
    """
    require_founder_access(request, founder_id, min_role="operator")

    target_audience = (body.get("target_audience") or "").strip()
    if not target_audience:
        raise HTTPException(status_code=400, detail="target_audience is required")

    limit = min(int(body.get("limit", 8)), 15)  # max 15 domains = 15 Hunter credits

    def _run():
        from backend.tools.hunter_tools import hunter_search_by_domains

        audience_lower = target_audience.lower()

        # Curated keyword → domain map.
        # Each entry maps audience keywords to domains of ACTUAL companies IN that industry
        # (not software vendors for that industry). Hunter domain search finds employees
        # at these companies — executives, owners, and decision makers.
        _INDUSTRY_MAP = [
            # Restaurant / Food Service — actual restaurant chains & food companies
            (["restaurant", "food service", "dining", "cafe", "bar", "kitchen", "eatery", "catering", "food and beverage", "f&b", "food"], [
                "darden.com", "rbi.com", "jackinthebox.com", "wingstop.com",
                "sweetgreen.com", "portillos.com", "dutchbros.com", "shakeshack.com",
                "firstwatch.com", "focusbrands.com", "noodles.com", "carrols.com",
            ]),
            # Hotels / Hospitality — actual hotel chains & lodging companies
            (["hotel", "lodging", "motel", "resort", "inn", "hospitality management", "bed and breakfast", "hospitality"], [
                "marriott.com", "hilton.com", "hyatt.com", "ihg.com",
                "choicehotels.com", "wyndhamhotels.com", "bestwestern.com",
                "acehotel.com", "sonesta.com", "omnihotels.com",
            ]),
            # E-commerce / DTC — actual consumer brands, not their platforms
            (["e-commerce", "ecommerce", "online store", "retail brand", "dtc", "direct to consumer", "consumer brand", "shop"], [
                "allbirds.com", "warbyparker.com", "bombas.com", "casper.com",
                "gymshark.com", "everlane.com", "glossier.com", "mejuri.com",
                "alo.com", "vuori.com", "brooklinen.com", "saatva.com",
            ]),
            # Retail — physical/omnichannel retail chains
            (["retail", "store", "boutique", "department store", "brick and mortar", "fashion retail"], [
                "gap.com", "jcrew.com", "anthropologie.com", "nordstrom.com",
                "williams-sonoma.com", "crateandbarrel.com", "restorationhardware.com",
                "macys.com", "bloomingdales.com",
            ]),
            # SaaS / Developer Tools — software companies targeting other software people
            (["saas", "b2b software", "developer tools", "engineering", "cto", "tech startup", "software company", "platform", "developer"], [
                "vercel.com", "supabase.com", "linear.app", "notion.so",
                "posthog.com", "segment.com", "amplitude.com", "airtable.com",
                "retool.com", "figma.com", "loom.com", "intercom.com",
            ]),
            # Startups / VC-backed founders
            (["startup", "founder", "venture", "early stage", "seed stage", "series a", "yc", "y combinator"], [
                "stripe.com", "brex.com", "mercury.com", "deel.com",
                "ramp.com", "openai.com", "anthropic.com", "scale.ai",
                "huggingface.co", "cohere.com", "together.ai", "mistral.ai",
            ]),
            # Healthcare / Medical — actual providers & health companies
            (["healthcare", "health", "medical", "clinic", "hospital", "doctor", "pharma", "biotech", "healthtech"], [
                "teladochealth.com", "hcahealthcare.com", "davita.com",
                "labcorp.com", "questdiagnostics.com", "uhg.com",
                "cigna.com", "humana.com", "anthem.com", "centene.com",
            ]),
            # Real Estate — brokerages and property companies
            (["real estate", "property", "realty", "mortgage", "broker", "agent", "realtor", "proptech"], [
                "remax.com", "century21.com", "coldwellbanker.com", "kw.com",
                "compass.com", "redfin.com", "opendoor.com", "cbre.com",
                "jll.com", "cushwake.com", "colliers.com",
            ]),
            # Fintech / Finance — actual fintech companies
            (["fintech", "finance", "banking", "payments", "lending", "insurance", "wealthtech", "insurtech", "accounting"], [
                "chime.com", "sofi.com", "robinhood.com", "coinbase.com",
                "lemonade.com", "rootinsurance.com", "betterment.com",
                "affirm.com", "klarna.com", "marqeta.com",
            ]),
            # Marketing / Advertising — actual agencies
            (["marketing agency", "advertising agency", "digital agency", "seo agency", "content agency", "pr firm", "creative studio", "marketing", "advertising", "agency"], [
                "ogilvy.com", "bbdo.com", "grey.com", "edelman.com",
                "weberfandhandwick.com", "havas.com", "dentsu.com",
                "publicisgroupe.com", "interpublic.com",
            ]),
            # HR / Staffing — actual staffing and recruiting firms
            (["hr", "human resources", "recruiting", "hiring agency", "talent", "staffing", "workforce", "people ops"], [
                "adecco.com", "manpowergroup.com", "randstadusa.com",
                "kellyservices.com", "roberthalf.com", "aerotek.com",
                "kforce.com", "heidrick.com", "spencerstuart.com",
            ]),
            # Education / EdTech — actual education companies
            (["education", "edtech", "school", "university", "learning", "training", "online course", "tutoring"], [
                "pearson.com", "chegg.com", "kaplan.com", "2u.com",
                "duolingo.com", "coursera.org", "udemy.com", "masterclass.com",
            ]),
            # Logistics / Supply Chain — actual logistics companies
            (["logistics", "supply chain", "shipping", "freight", "warehouse", "fulfillment", "delivery", "trucking"], [
                "ups.com", "fedex.com", "xpo.com", "jbhunt.com",
                "chrobinson.com", "echo.com", "coyote.com", "freightos.com",
            ]),
            # Construction / Trades — actual construction and architecture firms
            (["construction", "contractor", "builder", "architecture", "civil engineering", "hvac", "plumbing", "trade"], [
                "aecom.com", "jacobs.com", "wsp.com", "hdr.com",
                "bechtel.com", "fluor.com", "turner.com", "skanska.com",
            ]),
            # Legal — actual law firms
            (["legal", "law firm", "attorney", "lawyer", "legal tech", "compliance", "law", "counsel"], [
                "kirkland.com", "lathamwatkins.com", "skadden.com",
                "cooley.com", "wilsonsonsini.com", "fenwick.com",
                "akerman.com", "foley.com", "gunderson.com",
            ]),
            # Fitness / Wellness — actual gym chains and wellness companies
            (["fitness", "gym", "wellness", "yoga", "pilates", "crossfit", "health club", "studio", "sport"], [
                "equinox.com", "planetfitness.com", "lifetimefitness.com",
                "orangetheory.com", "f45training.com", "anytimefitness.com",
                "soulcycle.com", "peloton.com", "crunch.com",
            ]),
            # Media / Entertainment — actual media companies
            (["media", "entertainment", "content", "streaming", "gaming", "podcast", "publishing", "news"], [
                "netflix.com", "spotify.com", "buzzfeed.com", "vox.com",
                "axios.com", "substack.com", "discord.com", "twitch.tv",
            ]),
            # Consumer Apps / Marketplaces
            (["consumer app", "mobile app", "marketplace", "consumer tech", "social app", "platform"], [
                "doordash.com", "instacart.com", "airbnb.com", "lyft.com",
                "turo.com", "rover.com", "bumble.com", "offerup.com",
            ]),
            # Consulting / Professional Services
            (["consulting", "management consulting", "professional services", "advisory", "freelance", "independent"], [
                "mckinsey.com", "bain.com", "bcg.com", "deloitte.com",
                "pwc.com", "kpmg.com", "ey.com", "accenture.com",
            ]),
        ]

        seen: set[str] = set()
        domains: list[str] = []

        for keywords, industry_domains in _INDUSTRY_MAP:
            if any(kw in audience_lower for kw in keywords):
                for d in industry_domains:
                    if d not in seen and len(domains) < limit:
                        seen.add(d)
                        domains.append(d)

        if not domains:
            return {
                "contacts_found": 0, "contacts_stored": 0, "domains_searched": [],
                "error": f"No matching companies found for '{target_audience}'. Try terms like: restaurant owners, SaaS CTOs, e-commerce founders, healthcare startups, real estate agents.",
            }

        result = hunter_search_by_domains(
            founder_id=founder_id,
            domains=domains[:limit],
            seniority="",
            department="",
        )
        result["domains_searched"] = domains[:limit]
        return result

    result = await asyncio.to_thread(_run)
    return result


@router.get("/outreach/search/companies")
async def outreach_search_companies(
    request: Request,
    founder_id: str,
    locations: str = "",
    industries: str = "",
    company_sizes: str = "",
    funding_stages: str = "",
    keywords: str = "",
    technologies: str = "",
    page: int = 1,
    per_page: int = 25,
):
    """Search Apollo for companies with filters."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.apollo_tools import apollo_search_companies

    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    result = await asyncio.to_thread(
        apollo_search_companies,
        locations=_split(locations),
        industries=_split(industries),
        company_sizes=_split(company_sizes),
        funding_stages=_split(funding_stages),
        keywords=_split(keywords),
        technologies=_split(technologies),
        page=page,
        per_page=per_page,
    )
    return result


@router.get("/outreach/domain/{domain}")
async def outreach_domain_search(
    domain: str,
    request: Request,
    founder_id: str,
    department: str = "",
    seniority: str = "",
    limit: int = 10,
):
    """Hunter domain search — all emails at a company domain."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.hunter_tools import hunter_domain_search
    return await asyncio.to_thread(
        hunter_domain_search,
        domain=domain,
        department=department,
        seniority=seniority,
        limit=limit,
    )


@router.get("/outreach/find-email")
async def outreach_find_email(
    request: Request,
    founder_id: str,
    domain: str,
    first_name: str,
    last_name: str,
):
    """Hunter email finder — find email for a person at a domain."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.hunter_tools import hunter_find_email
    return await asyncio.to_thread(hunter_find_email, domain=domain, first_name=first_name, last_name=last_name)


@router.get("/outreach/verify-email")
async def outreach_verify_email(request: Request, founder_id: str, email: str):
    """Hunter email verifier."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.hunter_tools import hunter_verify_email
    return await asyncio.to_thread(hunter_verify_email, email=email)


@router.get("/outreach/enrich/person")
async def outreach_enrich_person(request: Request, founder_id: str, email: str):
    """Combined Hunter + Apollo person enrichment."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.hunter_tools import hunter_enrich_combined
    from backend.tools.apollo_tools import apollo_enrich_person

    hunter_data, apollo_data = await asyncio.gather(
        asyncio.to_thread(hunter_enrich_combined, email=email),
        asyncio.to_thread(apollo_enrich_person, email=email),
    )
    # Merge: Apollo is authoritative for title/company, Hunter for verification
    result = {**hunter_data}
    if isinstance(apollo_data, dict) and "error" not in apollo_data:
        result["apollo"] = apollo_data
    return result


@router.get("/outreach/enrich/company")
async def outreach_enrich_company(request: Request, founder_id: str, domain: str):
    """Combined Hunter + Apollo company enrichment."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.hunter_tools import hunter_enrich_company
    from backend.tools.apollo_tools import apollo_enrich_company

    hunter_data, apollo_data = await asyncio.gather(
        asyncio.to_thread(hunter_enrich_company, domain=domain),
        asyncio.to_thread(apollo_enrich_company, domain=domain),
    )
    result = {**hunter_data}
    if isinstance(apollo_data, dict) and "error" not in apollo_data:
        result["apollo"] = apollo_data
    return result


# ── Outreach contacts (saved to DB) ──────────────────────────────────────────

@router.post("/outreach/contacts/{founder_id}")
async def save_outreach_contacts(founder_id: str, body: dict, request: Request):
    """Save a list of contacts to the founder's outreach database."""
    require_founder_access(request, founder_id, min_role="operator")
    contacts = body.get("contacts", [])
    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts provided")

    db = get_supabase()
    rows = []
    for c in contacts:
        rows.append({
            "founder_id": founder_id,
            "email": c.get("email", ""),
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "title": c.get("title", ""),
            "company_name": c.get("company_name", ""),
            "company_domain": c.get("company_domain", ""),
            "linkedin_url": c.get("linkedin_url", ""),
            "city": c.get("city", ""),
            "state": c.get("state", ""),
            "country": c.get("country", ""),
            "industry": c.get("company_industry", c.get("industry", "")),
            "company_size": c.get("company_size", ""),
            "funding_stage": c.get("company_funding_stage", c.get("funding_stage", "")),
            "seniority": c.get("seniority", ""),
            "apollo_id": c.get("apollo_id") or None,
            "source": c.get("source", "apollo"),
        })

    result = db.table("outreach_contacts").upsert(
        rows, on_conflict="founder_id,email", ignore_duplicates=False
    ).execute()
    return {"saved": len(rows), "founder_id": founder_id}


@router.get("/outreach/contacts/{founder_id}")
async def get_outreach_contacts(
    founder_id: str,
    request: Request,
    status: str = "",
    page: int = 1,
    limit: int = 25,
):
    """List saved contacts. Auto-seeds the DB on first visit (0 contacts)."""
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    query = db.table("outreach_contacts").select("*").eq("founder_id", founder_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).range((page - 1) * limit, page * limit - 1).execute()

    contacts = result.data or []

    # Auto-seed the global Hunter pool on first ever use (runs once, shared by all founders)
    if not contacts and page == 1 and not status:
        from backend.tools.contact_seeder import seed_contact_database, is_seeding, GLOBAL_FOUNDER_ID
        if not is_seeding(founder_id):
            # Check if __global__ pool exists
            try:
                global_count = db.table("outreach_contacts").select("id", count="exact").eq(
                    "founder_id", GLOBAL_FOUNDER_ID
                ).limit(1).execute()
                pool_empty = (global_count.count or 0) == 0
            except Exception:
                pool_empty = True

            if pool_empty:
                import threading
                threading.Thread(target=seed_contact_database, daemon=True).start()
                logger.info("[outreach] Auto-seeding global Hunter contact pool")

    from backend.tools.contact_seeder import is_seeding
    return {
        "contacts": contacts,
        "page": page,
        "founder_id": founder_id,
        "seeding": is_seeding(founder_id),
    }


@router.patch("/outreach/contacts/{founder_id}/{contact_id}")
async def update_outreach_contact(founder_id: str, contact_id: str, body: dict, request: Request):
    """Update a contact's status or tags."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()
    allowed = {k: v for k, v in body.items() if k in ("status", "tags", "title", "company_name")}
    result = db.table("outreach_contacts").update(allowed).eq("id", contact_id).eq("founder_id", founder_id).execute()
    return result.data[0] if result.data else {}


# ── Outreach lists ────────────────────────────────────────────────────────────

@router.get("/outreach/lists/{founder_id}")
async def get_outreach_lists(founder_id: str, request: Request):
    """List all saved contact lists."""
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    result = db.table("outreach_lists").select("*").eq("founder_id", founder_id).order("created_at", desc=True).execute()
    return {"lists": result.data}


@router.post("/outreach/lists/{founder_id}")
async def create_outreach_list(founder_id: str, body: dict, request: Request):
    """Create a contact list and optionally add contacts to it."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()
    contact_ids = body.pop("contact_ids", [])

    row = {
        "founder_id": founder_id,
        "name": body.get("name", "Untitled List"),
        "description": body.get("description", ""),
        "filters": body.get("filters", {}),
        "contact_count": len(contact_ids),
    }
    list_result = db.table("outreach_lists").insert(row).execute()
    list_id = list_result.data[0]["id"]

    if contact_ids:
        members = [{"list_id": list_id, "contact_id": cid} for cid in contact_ids]
        db.table("outreach_list_members").insert(members).execute()

    return list_result.data[0]


@router.get("/outreach/lists/{founder_id}/{list_id}/contacts")
async def get_list_contacts(founder_id: str, list_id: str, request: Request):
    """Get all contacts in a list."""
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    members = db.table("outreach_list_members").select("contact_id").eq("list_id", list_id).execute()
    contact_ids = [m["contact_id"] for m in members.data]
    if not contact_ids:
        return {"contacts": []}
    contacts = db.table("outreach_contacts").select("*").in_("id", contact_ids).execute()
    return {"contacts": contacts.data}


# ── Outreach campaigns ────────────────────────────────────────────────────────

@router.get("/outreach/campaigns/{founder_id}")
async def get_campaigns(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    result = db.table("outreach_campaigns").select("*").eq("founder_id", founder_id).order("created_at", desc=True).execute()
    return {"campaigns": result.data}


@router.post("/outreach/campaigns/{founder_id}")
async def create_campaign(founder_id: str, body: dict, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()
    row = {
        "founder_id": founder_id,
        "name": body.get("name", "New Campaign"),
        "from_name": body.get("from_name", ""),
        "from_email": body.get("from_email", ""),
        "reply_to": body.get("reply_to", ""),
        "steps": body.get("steps", []),
        "product_name": body.get("product_name", ""),
        "value_prop": body.get("value_prop", ""),
        "daily_limit": body.get("daily_limit", 50),
        "send_provider": body.get("send_provider", "gmail"),
    }
    result = db.table("outreach_campaigns").insert(row).execute()
    return result.data[0]


@router.patch("/outreach/campaigns/{founder_id}/{campaign_id}")
async def update_campaign(founder_id: str, campaign_id: str, body: dict, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()
    allowed = {k: v for k, v in body.items() if k in (
        "name", "status", "from_name", "from_email", "reply_to",
        "steps", "product_name", "value_prop", "daily_limit", "send_provider"
    )}
    result = db.table("outreach_campaigns").update(allowed).eq("id", campaign_id).eq("founder_id", founder_id).execute()
    return result.data[0] if result.data else {}


@router.post("/outreach/campaigns/{founder_id}/{campaign_id}/contacts")
async def add_contacts_to_campaign(founder_id: str, campaign_id: str, body: dict, request: Request):
    """Enroll contacts from a list (or explicit IDs) into a campaign."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()

    contact_ids: list[str] = body.get("contact_ids", [])
    list_id = body.get("list_id")

    if list_id and not contact_ids:
        members = db.table("outreach_list_members").select("contact_id").eq("list_id", list_id).execute()
        contact_ids = [m["contact_id"] for m in members.data]

    if not contact_ids:
        raise HTTPException(status_code=400, detail="No contacts to enroll")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "campaign_id": campaign_id,
            "contact_id": cid,
            "founder_id": founder_id,
            "status": "active",
            "next_send_at": now,
        }
        for cid in contact_ids
    ]
    db.table("outreach_campaign_contacts").upsert(rows, on_conflict="campaign_id,contact_id", ignore_duplicates=True).execute()
    return {"enrolled": len(rows)}


@router.get("/outreach/campaigns/{founder_id}/{campaign_id}/contacts")
async def get_campaign_contacts(founder_id: str, campaign_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    result = db.table("outreach_campaign_contacts").select(
        "*, outreach_contacts(first_name, last_name, email, company_name, title)"
    ).eq("campaign_id", campaign_id).execute()
    return {"contacts": result.data}


@router.get("/outreach/campaigns/{founder_id}/{campaign_id}/stats")
async def get_campaign_stats(founder_id: str, campaign_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_supabase()
    events = db.table("outreach_email_events").select("event_type").eq("campaign_id", campaign_id).execute()
    counts: dict[str, int] = {}
    for e in events.data:
        et = e["event_type"]
        counts[et] = counts.get(et, 0) + 1

    sent = counts.get("sent", 0)
    return {
        "sent": sent,
        "opened": counts.get("opened", 0),
        "clicked": counts.get("clicked", 0),
        "replied": counts.get("replied", 0),
        "bounced": counts.get("bounced", 0),
        "open_rate": round(counts.get("opened", 0) / sent * 100, 1) if sent else 0,
        "click_rate": round(counts.get("clicked", 0) / sent * 100, 1) if sent else 0,
        "reply_rate": round(counts.get("replied", 0) / sent * 100, 1) if sent else 0,
    }


@router.post("/outreach/campaigns/{founder_id}/{campaign_id}/generate-steps")
async def generate_campaign_steps(founder_id: str, campaign_id: str, request: Request):
    """Generate LLM email sequence steps for a campaign."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()
    campaigns = db.table("outreach_campaigns").select("*").eq("id", campaign_id).eq("founder_id", founder_id).execute()
    if not campaigns.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = campaigns.data[0]

    from backend.tools.lead_finder import build_outreach_sequence
    steps = await asyncio.to_thread(
        build_outreach_sequence,
        product_name=campaign.get("product_name", "the product"),
        value_prop=campaign.get("value_prop", ""),
        lead_name="{{first_name}}",
        lead_company="{{company_name}}",
        lead_title="{{title}}",
        sequence_length=3,
    )

    db.table("outreach_campaigns").update({"steps": steps}).eq("id", campaign_id).execute()
    return {"steps": steps, "campaign_id": campaign_id}


@router.post("/outreach/campaigns/{founder_id}/{campaign_id}/send-batch")
async def send_campaign_batch(founder_id: str, campaign_id: str, request: Request):
    """
    Send the next due email to each active contact in the campaign via the
    founder's connected Gmail (Composio). Respects daily_limit.
    """
    require_founder_access(request, founder_id, min_role="operator")
    db = get_supabase()

    # Load campaign + steps
    camp_res = db.table("outreach_campaigns").select("*").eq("id", campaign_id).eq("founder_id", founder_id).execute()
    if not camp_res.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = camp_res.data[0]
    steps: list[dict] = campaign.get("steps") or []
    daily_limit: int = campaign.get("daily_limit") or 50

    if not steps:
        raise HTTPException(status_code=400, detail="No steps — generate the email sequence first")

    from datetime import datetime, timedelta, timezone
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    # Contacts due for their next step
    due_res = db.table("outreach_campaign_contacts").select(
        "*, outreach_contacts(first_name, last_name, email, company_name, title)"
    ).eq("campaign_id", campaign_id).eq("status", "active").lte("next_send_at", now_iso).limit(daily_limit).execute()

    sent = failed = skipped = 0

    for cc in (due_res.data or []):
        contact = cc.get("outreach_contacts") or {}
        to_email = contact.get("email", "")
        if not to_email:
            skipped += 1
            continue

        step_idx = cc.get("current_step", 0)
        if step_idx >= len(steps):
            db.table("outreach_campaign_contacts").update({"status": "completed"}).eq("id", cc["id"]).execute()
            skipped += 1
            continue

        step = steps[step_idx]

        def _merge(text: str) -> str:
            return (
                text
                .replace("{{first_name}}", contact.get("first_name", "there"))
                .replace("{{last_name}}", contact.get("last_name", ""))
                .replace("{{company_name}}", contact.get("company_name", "your company"))
                .replace("{{title}}", contact.get("title", ""))
            )

        subject = _merge(step.get("subject", ""))
        body = _merge(step.get("body", ""))

        from backend.tools.composio_tools import composio_gmail_send
        result = await asyncio.to_thread(composio_gmail_send, founder_id, to_email, subject, body)

        success = "error" not in result

        # Record send event
        db.table("outreach_email_events").insert({
            "founder_id": founder_id,
            "campaign_id": campaign_id,
            "campaign_contact_id": cc["id"],
            "contact_id": cc["contact_id"],
            "event_type": "sent" if success else "failed",
            "step_index": step_idx,
        }).execute()

        if success:
            sent += 1
            next_idx = step_idx + 1
            if next_idx >= len(steps):
                db.table("outreach_campaign_contacts").update({
                    "status": "completed",
                    "current_step": next_idx,
                    "last_sent_at": now_iso,
                }).eq("id", cc["id"]).execute()
            else:
                days_gap = steps[next_idx].get("send_day", 3) - step.get("send_day", 1)
                next_send = (now_dt + timedelta(days=max(days_gap, 1))).isoformat()
                db.table("outreach_campaign_contacts").update({
                    "current_step": next_idx,
                    "last_sent_at": now_iso,
                    "next_send_at": next_send,
                }).eq("id", cc["id"]).execute()
        else:
            failed += 1
            logger.warning("Gmail send failed for %s: %s", to_email, result.get("error"))

    return {"sent": sent, "failed": failed, "skipped": skipped, "total_due": len(due_res.data or [])}


# ── Email tracking pixels ─────────────────────────────────────────────────────

_TRACKING_GIF = bytes.fromhex(
    "47494638396101000100800000ffffff"
    "00000021f90401000000002c00000000"
    "010001000002024401003b"
)


@router.get("/track/open/{founder_id}/{campaign_id}/{cc_id}/{step_index}")
async def track_open(founder_id: str, campaign_id: str, cc_id: str, step_index: int):
    """Record email open event. Returns 1x1 transparent GIF."""
    from fastapi.responses import Response
    try:
        db = get_supabase()
        # Get contact_id from campaign_contact
        cc = db.table("outreach_campaign_contacts").select("contact_id").eq("id", cc_id).execute()
        contact_id = cc.data[0]["contact_id"] if cc.data else None
        db.table("outreach_email_events").insert({
            "founder_id": founder_id,
            "campaign_id": campaign_id,
            "campaign_contact_id": cc_id,
            "contact_id": contact_id,
            "event_type": "opened",
            "step_index": step_index,
        }).execute()
    except Exception as e:
        logger.warning("Track open failed: %s", e)
    return Response(content=_TRACKING_GIF, media_type="image/gif", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


@router.get("/track/click/{founder_id}/{campaign_id}/{cc_id}/{step_index}")
async def track_click(founder_id: str, campaign_id: str, cc_id: str, step_index: int, url: str = ""):
    """Record click event and redirect to original URL."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import unquote
    try:
        db = get_supabase()
        cc = db.table("outreach_campaign_contacts").select("contact_id").eq("id", cc_id).execute()
        contact_id = cc.data[0]["contact_id"] if cc.data else None
        db.table("outreach_email_events").insert({
            "founder_id": founder_id,
            "campaign_id": campaign_id,
            "campaign_contact_id": cc_id,
            "contact_id": contact_id,
            "event_type": "clicked",
            "step_index": step_index,
            "url": unquote(url),
        }).execute()
    except Exception as e:
        logger.warning("Track click failed: %s", e)
    return RedirectResponse(url=unquote(url) or "/", status_code=302)

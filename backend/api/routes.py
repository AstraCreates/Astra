import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

# Short-TTL nonce store for OAuth state parameters.
# Maps random nonce → (founder_id, expiry_unix). Consumed on use.
_oauth_states: dict[str, tuple[str, float]] = {}
_oauth_states_lock = threading.Lock()
_OAUTH_STATE_TTL = 600  # 10 minutes


def _oauth_state_create(founder_id: str) -> str:
    nonce = secrets.token_urlsafe(32)
    with _oauth_states_lock:
        _oauth_states[nonce] = (founder_id, time.time() + _OAUTH_STATE_TTL)
    return nonce


def _oauth_state_consume(nonce: str) -> str | None:
    """Return founder_id and delete the entry, or None if missing/expired."""
    with _oauth_states_lock:
        entry = _oauth_states.pop(nonce, None)
    if entry is None:
        return None
    founder_id, expiry = entry
    if time.time() > expiry:
        return None
    return founder_id


def _run_option_exclusions(technical_scope: str | None, marketing_channels: str | None) -> list[str]:
    """Translate the founder-facing technical_scope/marketing_channels enums into
    an agent-name exclusion list consumed by Orchestrator.run/continue_run.
    Unset/"both" excludes nothing — today's default behavior is unchanged."""
    exclude: list[str] = []
    if technical_scope == "none":
        exclude += ["technical", "web"]
    elif technical_scope == "website":
        exclude.append("technical")
    elif technical_scope == "technical":
        exclude.append("web")
    if marketing_channels == "organic":
        exclude.append("marketing_paid")
    return exclude


def _public_base_url(url: str, *, default: str) -> str:
    """Normalize public callback/redirect bases.

    Local development keeps http://localhost, but any non-local public host is
    upgraded to https to match how nginx serves the production app and how
    OAuth providers register redirect URIs.
    """
    raw = (url or default).strip() or default
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1", ""}:
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment)).rstrip("/")
    return raw.rstrip("/")

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

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
    AutomationTriggerRequest,
    AutomationFlowSaveRequest,
    AutomationFlowRunRequest,
    AutomationDraftRequest,
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


def _analyze_goal(instruction: str) -> tuple[str | None, str | None]:
    """LLM analysis of goal. Returns (stack_id, business_profile).
    stack_id: 'ecomm' | 'local_service' | None (saas/default)
    business_profile: 2-3 sentence summary of the business for agent context.
    Fails open: returns (None, None) on any error.
    """
    try:
        import json as _json
        from backend.tools._llm import generate
        prompt = (
            "You are analyzing a founder's business goal to understand what they are building.\n\n"
            f"Goal text:\n{instruction}\n\n"
            "Tasks:\n"
            "1. Write a concise 2-3 sentence business profile that captures: what they're building, "
            "who it serves, and what problem it solves. This will be injected as context for AI agents "
            "— be specific, not generic.\n"
            "2. Classify the business type:\n"
            "   - ecomm: online store selling physical/digital products, print-on-demand, dropshipping\n"
            "   - local_service: brick-and-mortar, appointment-based, in-person services\n"
            "   - saas: software, app, platform, API, agency, content/creator\n\n"
            "Respond with a JSON object:\n"
            '{"stack_id": "ecomm"|"local_service"|"saas", "business_profile": "..."}'
        )
        raw = generate(prompt, model="fast", temperature=0.0, json_mode=True)
        # Strip markdown fences if present
        import re as _re
        raw = _re.sub(r"```(?:json)?|```", "", raw).strip()
        data = _json.loads(raw)
        stack_id = data.get("stack_id", "saas")
        profile = (data.get("business_profile") or "").strip()
        return (stack_id if stack_id in ("ecomm", "local_service") else None, profile or None)
    except Exception:
        return (None, None)


def _write_env_key(key: str, value: str) -> None:
    # A newline in either key or value lets a caller inject arbitrary extra
    # lines into the .env file (e.g. value="foo\nASTRA_REQUIRE_AUTH=false"),
    # smuggling in unrelated env vars. Reject rather than silently strip —
    # a legitimate key/value should never contain a line break.
    if "\n" in key or "\r" in key or "\n" in value or "\r" in value:
        raise ValueError(f"_write_env_key: key/value for {key!r} must not contain newline characters")
    env_path = ".env"
    try:
        try:
            with open(env_path) as fh:
                lines = fh.readlines()
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
        with open(env_path, "w") as fh:
            fh.writelines(lines)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not write %s to .env: %s", key, e)
import asyncio
from fastapi.responses import StreamingResponse

from backend.db.client import get_supabase, get_outreach_db, update_task_status
from backend.core.factory import get_orchestrator
from backend.core.events import stream_events, publish
from backend.control_plane.rollout import assign_run_features
from backend.tenant_auth import actor_or_body, require_founder_access, require_org_access

router = APIRouter()


def _require_company_scope(
    request: Request,
    founder_id: str,
    company_id: str | None = None,
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


async def _load_session_events(session_id: str) -> list[tuple[int, dict]]:
    from backend.core.events import _event_log, _restore_session

    if session_id not in _event_log:
        await asyncio.to_thread(_restore_session, session_id)
    return _event_log.get(session_id, [])


async def _session_founder_id(session_id: str) -> str:
    # Session metadata is the cheap, durable ownership source. Do this before
    # restoring a potentially large event log so lightweight routes such as
    # /sessions/{id}/meta remain responsive while research is running.
    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(session_id)
        owner = str((meta or {}).get("founder_id") or "")
        if owner:
            return owner
    except Exception:
        pass
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
    raise HTTPException(status_code=404, detail="Session owner could not be resolved")


@router.get("/automations/session")
async def automations_session(founder_id: str, request: Request):
    """Legacy embedded-automations bridge endpoint."""
    require_founder_access(request, founder_id, min_role="viewer")
    raise HTTPException(status_code=410, detail="Embedded automations session bridge has been retired.")


@router.get("/automations/overview")
async def automations_overview(founder_id: str, request: Request):
    """Return Astra-native automations page data without embedding a third-party UI."""
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.config import settings
    from backend.tools.automation_runtime import automation_list_flows, starter_automation_catalog

    workflows: list[dict[str, object]] = []
    installed_paths: set[str] = set()
    runtime_status = "standby"
    runtime_detail = "Astra's native automations workspace is live. Runtime wiring is still being finalized."

    if settings.automation_token:
        try:
            result = await automation_list_flows()
            records = result.get("items") if isinstance(result, dict) else None
            if isinstance(records, list):
                installed_paths = {
                    str(item.get("path") or item.get("id") or "").strip("/")
                    for item in records
                    if isinstance(item, dict)
                }
                workflows = [
                    {
                        "id": str(item.get("path") or item.get("id") or ""),
                        "name": str(item.get("summary") or item.get("path") or item.get("id") or "Untitled automation"),
                        "active": not bool(item.get("archived", False)),
                        "updated_at": item.get("edited_at") or item.get("updatedAt") or item.get("updated_at"),
                    }
                    for item in records[:8]
                    if isinstance(item, dict)
                ]
                runtime_status = "connected"
                runtime_detail = f"Automation runtime connected. Showing {len(workflows)} flows."
            else:
                runtime_status = "degraded"
                runtime_detail = str(result.get("error") or "Automation runtime returned an unexpected response")
        except Exception as e:
            runtime_status = "degraded"
            runtime_detail = f"Could not load automation flows: {e}"
    else:
        runtime_status = "setup_needed"
        runtime_detail = "Automation runtime is configured for Windmill, but its API token is not set yet."

    return {
        "provider": "astra",
        "native": True,
        "runtime": {
            "status": runtime_status,
            "detail": runtime_detail,
        },
        "workflows": workflows,
        "workflow_count": len(workflows),
        "templates": [
            {
                **template,
                "installed": template["path"].strip("/") in installed_paths,
            }
            for template in starter_automation_catalog()
        ],
        "next_steps": [
            "Keep auth inside Astra only.",
            "Use this page as the control center for templates, runs, and approvals.",
            "Add builder actions behind Astra-native UI instead of embedding a separate app.",
        ],
    }


@router.post("/automations/templates/install_all")
async def automations_install_all(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="editor")
    from backend.tools.automation_runtime import automation_install_all_starters

    return await automation_install_all_starters()


@router.post("/automations/templates/{template_key}/install")
async def automations_install_template(template_key: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="editor")
    from backend.tools.automation_runtime import automation_install_starter

    result = await automation_install_starter(template_key)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result


@router.post("/automations/templates/{template_key}/run")
async def automations_run_template(template_key: str, body: AutomationTriggerRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="editor")
    from backend.tools.automation_runtime import (
        STARTER_AUTOMATIONS,
        automation_default_payload,
        automation_trigger_flow,
    )

    template = STARTER_AUTOMATIONS.get(template_key)
    if not template:
        raise HTTPException(status_code=404, detail="Unknown automation template")

    payload = automation_default_payload(template_key)
    payload.update(body.payload or {})
    result = await automation_trigger_flow(template["path"], payload, founder_id=body.founder_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return {"ok": True, "result": result, "path": template["path"]}


# ── Automations canvas: native flow builder (agent/prompt/action nodes) ────────

@router.get("/automations/flows")
async def automations_list_flows(founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.core import automation_store
    return {"flows": automation_store.list_flows(founder_id)}


@router.get("/automations/flows/{flow_id}")
async def automations_get_flow(flow_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.core import automation_store
    flow = automation_store.get_flow(founder_id, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.post("/automations/flows")
async def automations_save_flow(body: AutomationFlowSaveRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="editor")
    from backend.core import automation_store
    return automation_store.save_flow(
        body.founder_id, body.name, body.nodes, body.edges, flow_id=body.flow_id,
    )


@router.post("/automations/flows/draft")
async def automations_draft_flow(body: AutomationDraftRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="editor")
    from backend.tools.automation_drafts import draft_flow_from_prompt
    return draft_flow_from_prompt(body.prompt)


@router.delete("/automations/flows/{flow_id}")
async def automations_delete_flow(flow_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="editor")
    from backend.core import automation_store
    if not automation_store.delete_flow(founder_id, flow_id):
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"ok": True}


@router.post("/automations/flows/{flow_id}/run")
async def automations_run_flow(flow_id: str, body: AutomationFlowRunRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="editor")
    from backend.core import automation_store
    if not automation_store.get_flow(body.founder_id, flow_id):
        raise HTTPException(status_code=404, detail="Flow not found")

    from backend.tools.automation_graph import run_automation_flow
    import asyncio

    run = automation_store.create_run(body.founder_id, flow_id)
    asyncio.create_task(run_automation_flow(body.founder_id, flow_id, run["run_id"]))
    return {"ok": True, "run_id": run["run_id"], "status": "running"}


@router.post("/automations/hooks/{token}")
async def automations_webhook_trigger(token: str, request: Request):
    """Public trigger endpoint for external webhooks (Stripe, Typeform, a
    cron pinger, etc). No founder auth — protected by the opaque token alone,
    same shape as n8n/Zapier webhook URLs. Deliberately just the token in the
    path: founder_id is derived from the founder's email (see
    normalizeEmailToFounderId) and has no business appearing in a URL meant
    to be pasted into a third-party service's webhook config."""
    from backend.core import automation_store
    resolved = automation_store.resolve_webhook_token(token)
    if not resolved:
        raise HTTPException(status_code=404, detail="Not found")
    founder_id, flow_id = resolved
    flow = automation_store.get_flow(founder_id, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    from backend.tools.automation_graph import run_automation_flow
    import asyncio

    run = automation_store.create_run(founder_id, flow_id)
    asyncio.create_task(run_automation_flow(founder_id, flow_id, run["run_id"], trigger_payload=payload))
    return {"ok": True, "run_id": run["run_id"], "status": "running"}


@router.get("/automations/flows/{flow_id}/runs")
async def automations_list_runs(flow_id: str, founder_id: str, request: Request, limit: int = 20):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.core import automation_store
    return {"runs": automation_store.list_runs(founder_id, flow_id=flow_id, limit=limit)}


@router.get("/automations/runs/{run_id}")
async def automations_get_run(run_id: str, founder_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    from backend.core import automation_store
    run = automation_store.get_run(founder_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/stacks")
async def stacks():
    from backend.stacks import list_stack_templates

    return {"stacks": list_stack_templates()}


@router.get("/agents/catalog")
async def agents_catalog():
    """Return the full catalog of all 6 specialist agents with tools, outputs, and dependencies."""
    from backend.stacks.catalog import get_agent_catalog

    return {"agents": get_agent_catalog()}


@router.get("/automations/integration-catalog")
async def automations_integration_catalog(response: Response):
    """Return the full integration-block registry for the automations canvas palette.
    Static per-deploy (the registry is a Python module, not per-founder data) — cache
    it client-side so the canvas doesn't refetch the same ~38-block payload on every load."""
    from backend.tools.automation_blocks import catalog

    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"blocks": catalog()}


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


async def _reconcile_orphaned_agents(session_id: str, reason: str) -> None:
    """Flip any agent still 'running'/'waiting' to error.

    When a run ends abnormally (top-level exception, kill, cancellation) the
    orchestrator may not emit a terminal event for in-flight or not-yet-started
    agents, leaving them frozen in the UI. Emitting agent_error reconciles the
    state reducer so the dashboard/session view stop showing live spinners.
    """
    try:
        from backend.core.session_store import load_events
        from backend.workflow_state import build_session_state
        events = await asyncio.to_thread(load_events, session_id) or []
        state = build_session_state(session_id, events)
        for name, ag in (state.get("agents") or {}).items():
            if (ag or {}).get("status") in ("running", "waiting"):
                await publish(session_id, {
                    "type": "agent_error", "agent": name,
                    "task_id": (ag or {}).get("task_id") or "", "error": reason,
                })
    except Exception:
        pass


@router.post("/goal")
async def submit_goal(body: GoalRequest, request: Request):
    actor_id = require_founder_access(request, body.founder_id, min_role="operator")
    # Validate the initial prompt: minimum length + disallowed-content screen.
    from backend.safety.content_filter import screen_goal
    _ok, _reason = screen_goal(body.instruction)
    if not _ok:
        raise HTTPException(status_code=400, detail=_reason)
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
    _inferred_stack, _business_profile = _analyze_goal(body.instruction)
    _effective_stack = body.stack_id or _inferred_stack or ""
    if _effective_stack:
        constraints["stack_id"] = _effective_stack
    constraints["unlimited_credits"] = _unlimited
    _exclude_agents = _run_option_exclusions(body.technical_scope, body.marketing_channels)
    if _exclude_agents:
        constraints["exclude_agents"] = _exclude_agents
    if body.research_depth:
        constraints["research_depth"] = body.research_depth
    # Prepend LLM-generated business profile so all agents have full context
    _goal_instruction = body.instruction
    if _business_profile and "---" not in body.instruction[:80]:
        _goal_instruction = f"Business profile:\n{_business_profile}\n\n---\n{body.instruction}"

    # Create or resolve workspace + chapter
    _workspace_id: str = ""
    _chapter_id: str = ""
    try:
        from backend.core import workspace_store as _wss
        _ws_name = (body.workspace_name or "").strip() or body.instruction[:60]
        _requested_company_id = body.company_id or body.workspace_id
        if _requested_company_id:
            # Add a new chapter to an existing workspace
            _company = _wss.get_workspace(_requested_company_id)
            if not _company:
                raise HTTPException(status_code=404, detail="Company not found")
            require_founder_access(
                request,
                str(_company.get("founder_id") or ""),
                min_role="operator",
            )
            _workspace_id = _requested_company_id
        else:
            # Reuse an existing workspace with the same company name if one exists,
            # so multiple runs for the same company don't scatter into separate workspaces.
            _existing = None
            if body.workspace_name:
                from backend.core.workspace_store import find_workspace_by_name as _fwbn
                _existing = _fwbn(body.founder_id, body.workspace_name)
            if _existing:
                _workspace_id = _existing["workspace_id"]
            else:
                _ws = _wss.create_workspace(
                    founder_id=body.founder_id,
                    name=_ws_name,
                    goal=_goal_instruction,
                    stack_id=_effective_stack or "idea_to_revenue",
                )
                _workspace_id = _ws["workspace_id"]
        _ch = _wss.create_chapter(workspace_id=_workspace_id, session_id=session_id)
        _chapter_id = _ch["chapter_id"]
        constraints["company_id"] = _workspace_id
        constraints["workspace_id"] = _workspace_id
    except HTTPException:
        raise
    except Exception as _we:
        logger.warning("workspace creation failed (non-fatal): %s", _we)

    # Register session in durable store before launching
    try:
        from backend.core.session_store import merge_session_meta as _merge_meta, register_session as _reg
        _reg(
            session_id=session_id,
            founder_id=body.founder_id,
            goal=_goal_instruction,
            stack_id=_effective_stack,
            company_name=str(constraints.get("company_name", "")),
            agents=list(constraints.get("agents", [])),
            workspace_id=_workspace_id,
            company_id=_workspace_id or body.founder_id,
            chapter_id=_chapter_id,
            kind="user",
        )
        _merge_meta(session_id, constraints=constraints, engine="legacy")
    except Exception as _se:
        logger.warning("session_store.register_session failed: %s", _se)

    # Pre-create the SSE queue so the frontend can connect before the first event arrives.
    # Without this, stream_events sees an empty session and yields session_expired immediately.
    from backend.core.events import _get_queue as _pre_queue
    _pre_queue(session_id)

    # Durable control-plane run record (Wave 1). Dual-write, best-effort,
    # additive alongside session_store above -- never fails the request
    # (durable_create_run swallows its own errors). AWAITED, not
    # fire-and-forget: astra_run_events has an FK to astra_runs, so any
    # event published before this insert lands would silently drop (events
    # dual-write is also best-effort) -- the row must exist first.
    try:
        from backend.control_plane.models import Run
        from backend.control_plane.supabase_repositories import durable_create_run
        await durable_create_run(Run(
            id=session_id,
            owner_id=body.founder_id,
            org_id=_workspace_id or body.founder_id,
            company_id=_workspace_id or body.founder_id,
            workspace_id=_workspace_id,
            chapter_id=_chapter_id,
            goal=_goal_instruction,
            stack_id=_effective_stack,
        ))
    except Exception as _dre:
        logger.warning("durable_create_run dispatch failed: %s", _dre)

    # ── Feature flag: route to Temporal or legacy ──────────────────────────
    # Resolved ONCE, here, and persisted on the run record -- per the plan
    # invariant, flags must never be re-evaluated for an in-flight run (a
    # rollout_percent change mid-run must not move the run between engines).
    # Store the whole dict, not just engine: anything checking
    # event_stream_v2/model_gateway_v2/etc for this specific run later must
    # read this persisted value, not call assign_run_features() again.
    _features = assign_run_features(_workspace_id or body.founder_id, session_id)
    _use_temporal = _features.get("engine") == "temporal"
    try:
        from backend.core.session_store import merge_session_meta as _merge_features
        _merge_features(session_id, feature_assignment=_features, engine=_features.get("engine", "legacy"))
    except Exception as _fe:
        logger.warning("session_store.merge_session_meta (feature_assignment) failed: %s", _fe)

    if _use_temporal:
        # Dispatch through Temporal durable execution
        try:
            from backend.control_plane.temporal.dispatch import start_run
            _dispatch = await start_run(
                run_id=session_id,
                founder_id=body.founder_id,
                company_id=_workspace_id or body.founder_id,
                workspace_id=_workspace_id,
                chapter_id=_chapter_id,
            )
            try:
                from backend.core.session_store import merge_session_meta as _merge_meta
                _merge_meta(
                    session_id,
                    engine="temporal",
                    constraints=constraints,
                    workflow_id=_dispatch.get("workflow_id", ""),
                    temporal_task_queue=_dispatch.get("task_queue", ""),
                )
            except Exception as _me:
                logger.warning("session_store.merge_session_meta failed: %s", _me)
            return {
                "session_id": session_id,
                "status": "running",
                "engine": "temporal",
                "company_id": _workspace_id or body.founder_id,
                "workspace_id": _workspace_id,
                "chapter_id": _chapter_id,
            }
        except Exception as _temporal_exc:
            logger.warning("Temporal dispatch failed, falling back to legacy: %s", _temporal_exc)
            # Dispatch never actually started on Temporal -- correct the persisted
            # engine so the run record doesn't claim an engine that didn't run it.
            try:
                _features = dict(_features, engine="legacy")
                _merge_features(session_id, feature_assignment=_features, engine="legacy")
            except Exception as _fe2:
                logger.warning("session_store.merge_session_meta (engine correction) failed: %s", _fe2)
            # Fall through to legacy path

    async def _run():
        from backend.core import cancellation
        _final_status = "done"
        try:
            await orch.run(
                goal=_goal_instruction,
                founder_id=body.founder_id,
                constraints=constraints,
                session_id=session_id,
            )
        except asyncio.CancelledError:
            _final_status = "killed"
            logger.info("goal run killed session=%s", session_id)
            try:
                from backend.core.session_store import update_session_status
                update_session_status(session_id, "killed")
                await _reconcile_orphaned_agents(session_id, "Run stopped by user.")
                await publish(session_id, {"type": "goal_error", "error": "Run stopped by user.", "killed": True})
            except Exception:
                pass
        except Exception as e:
            _final_status = "error"
            logger.error("goal run error session=%s: %s", session_id, e, exc_info=True)
            try:
                await _reconcile_orphaned_agents(session_id, "Run failed before this agent completed.")
                await publish(session_id, {"type": "goal_error", "error": str(e)})
            except Exception:
                pass
        finally:
            cancellation.clear(session_id)
            # Update chapter status when the session ends
            if _workspace_id and _chapter_id:
                try:
                    from backend.core import workspace_store as _wss2
                    _wss2.update_chapter(_workspace_id, _chapter_id, status=_final_status)
                except Exception as _ce:
                    logger.warning("chapter status update failed: %s", _ce)

    _task = asyncio.create_task(_run())
    from backend.core import cancellation
    cancellation.register_task(session_id, _task)
    return {
        "session_id": session_id,
        "status": "running",
        "company_id": _workspace_id or body.founder_id,
        "workspace_id": _workspace_id,
        "chapter_id": _chapter_id,
    }


@router.get("/stream/{session_id}")
async def stream_goal(session_id: str, request: Request):
    await _require_session_access(request, session_id, min_role="viewer")
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
    })


@router.get("/sessions")
async def list_sessions(
    request: Request,
    founder_id: str = "",
    company_id: str = "",
    limit: int = 50,
):
    """List all sessions for a founder, newest first."""
    from backend.core.session_store import list_sessions as _ls
    if founder_id:
        require_founder_access(request, founder_id, min_role="viewer")
    if company_id:
        from backend.core.workspace_store import get_workspace
        company = get_workspace(company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        require_founder_access(
            request,
            str(company.get("founder_id") or ""),
            min_role="viewer",
        )
    # Offload the blocking index.json read so it doesn't stall the event loop
    # (single worker serves all sessions — sync file I/O here serializes them).
    sessions = await asyncio.to_thread(
        _ls,
        founder_id or None,
        limit,
        company_id or None,
    )
    return {"sessions": sessions}


async def _teardown_workspace(session_id: str) -> None:
    """Delete the workspace tree for a session. Best-effort, offloaded to thread."""
    try:
        from backend.tools.git_tools import remove_workspace
        await asyncio.to_thread(remove_workspace, session_id)
    except Exception as e:
        logger.warning("workspace teardown failed for %s: %s", session_id, e)


async def _cancel_temporal_session_if_needed(session_id: str, meta: dict | None) -> bool:
    if str((meta or {}).get("engine") or "") != "temporal":
        return False
    try:
        from backend.control_plane.temporal.dispatch import cancel_run
        return await cancel_run(session_id)
    except Exception as exc:
        logger.warning("Temporal cancellation failed for %s: %s", session_id, exc)
        return False


async def _teardown_session_artifacts(session_id: str) -> None:
    """Stop the session's live preview (free its port) and delete its workspace
    tree. Best-effort, offloaded to threads (rmtree + subprocess can block).

    Preview is keyed by root session ID — killing a child session leaves the preview
    running. Only an explicit delete of the root (or delete_all) should stop it.
    """
    try:
        from backend.tools.local_preview import stop_local_preview
        from backend.core.session_store import get_session_meta
        meta = await asyncio.to_thread(get_session_meta, session_id)
        # Root session has no parent — stop its preview; child deletes leave it running
        if not (meta or {}).get("parent_session_id"):
            await asyncio.to_thread(stop_local_preview, session_id)
    except Exception as e:
        logger.warning("preview teardown failed for %s: %s", session_id, e)
    await _teardown_workspace(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session_route(session_id: str, request: Request):
    """Permanently delete a session. Only the owning founder (or an authorized org member) may delete."""
    from backend.core.session_store import get_session_meta, delete_session as _del
    meta = get_session_meta(session_id)
    if not meta:
        # Nothing to delete server-side; treat as success so the client can drop it locally.
        return {"ok": True, "deleted": False}
    owner = str(meta.get("founder_id") or "")
    if owner:
        require_founder_access(request, owner, min_role="operator")
    # Kill any live run first — otherwise the orchestrator keeps writing and would
    # re-persist the session right after we delete it (so it reappears on refresh).
    try:
        from backend.core import cancellation
        cancellation.request_kill(session_id)
    except Exception:
        pass
    await _cancel_temporal_session_if_needed(session_id, meta)
    # Shut down the live preview + delete the workspace before dropping the session.
    await _teardown_session_artifacts(session_id)
    # Clean up any company goal this session spawned (so deleted sessions don't
    # leave stale goals/operating-runs in the /goals view).
    try:
        from backend.missions.company_goal import handle_session_deleted
        await asyncio.to_thread(handle_session_deleted, session_id)
    except Exception as e:
        logger.warning("company goal cleanup failed for %s: %s", session_id, e)
    removed = _del(session_id)
    return {"ok": True, "deleted": removed}


@router.post("/attachments/ingest/{founder_id}")
async def ingest_attachment_route(founder_id: str, body: dict, request: Request):
    """Convert an uploaded file (text/PDF/image) into agent-readable text and,
    when persist=true, save it to the founder's Library for reuse."""
    require_founder_access(request, founder_id, min_role="operator")
    import base64
    filename = (body.get("filename") or "file").strip()
    filename = filename.replace("\\", "_").replace("/", "_")[:180] or "file"
    mime = (body.get("mime") or "").strip()
    data_b64 = body.get("data_base64") or ""
    if not data_b64:
        raise HTTPException(status_code=400, detail="data_base64 is required")
    try:
        data = base64.b64decode(data_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64 data")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB).")

    from backend.tools.attachment_ingest import ingest_attachment
    result = await asyncio.to_thread(ingest_attachment, filename, mime, data)

    library_id = None
    if body.get("persist") and result.get("content") and not result.get("error"):
        try:
            from backend.library.store import create_file
            rec = await asyncio.to_thread(
                create_file, founder_id, "uploads", filename, result["content"], False
            )
            library_id = rec.get("id")
        except Exception as e:
            logger.warning("attachment persist failed: %s", e)

    content_len = len(str(result.get("content") or ""))
    return {
        "filename": filename,
        **result,
        "library_id": library_id,
        "summary": (
            f"Read {content_len:,} characters from {filename}"
            + (" and saved it to Library." if library_id else ".")
            if content_len
            else str(result.get("error") or "No readable content extracted.")
        ),
    }


@router.post("/sessions/{session_id}/kill")
async def kill_session(session_id: str, request: Request):
    """Immediately stop a running session — cancels the in-flight task and
    flags it killed so the orchestrator won't continue. Only the owner may kill."""
    from backend.core.session_store import get_session_meta, update_session_status
    meta = get_session_meta(session_id)
    owner = str((meta or {}).get("founder_id") or "")
    if owner:
        require_founder_access(request, owner, min_role="operator")
    from backend.core import cancellation
    cancelled = cancellation.request_kill(session_id)
    cancelled = (await _cancel_temporal_session_if_needed(session_id, meta)) or cancelled
    try:
        update_session_status(session_id, "killed")
    except Exception:
        pass
    # A kill can interrupt the in-flight run before agents emit their own
    # terminal events, so reconcile their state eagerly for the UI.
    await _reconcile_orphaned_agents(session_id, "Run stopped by user.")
    # Do NOT tear down the preview on kill — the site stays live until the session
    # is explicitly deleted. Only delete the workspace (build artifacts).
    await _teardown_workspace(session_id)
    try:
        await publish(session_id, {"type": "goal_error", "error": "Run stopped by user.", "killed": True})
    except Exception:
        pass
    return {"ok": True, "killed": cancelled, "session_id": session_id, "active_attempts_cancelled": cancelled}


@router.post("/sessions/{session_id}/stop-agent/{agent_name}")
async def stop_agent(session_id: str, agent_name: str, request: Request):
    """Instantly stop ONE running agent without killing the rest of the run. The agent
    halts at its next loop step. Only the session owner may stop."""
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(session_id)
    owner = str((meta or {}).get("founder_id") or "")
    if owner:
        require_founder_access(request, owner, min_role="operator")
    from backend.core import cancellation
    cancellation.request_kill_agent(session_id, agent_name)
    try:
        await publish(session_id, {"type": "agent_stop_requested", "agent": agent_name.lower().strip()})
    except Exception:
        pass
    return {"ok": True, "stopped": agent_name, "session_id": session_id}


@router.post("/sessions/{session_id}/pause")
async def pause_session_route(session_id: str, request: Request):
    """Pause a running session — new agents will not start until resumed."""
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(session_id)
    owner = str((meta or {}).get("founder_id") or "")
    if owner:
        require_founder_access(request, owner, min_role="operator")
    from backend.core.cancellation import pause_session
    pause_session(session_id)
    return {"ok": True, "paused": True}


@router.post("/sessions/{session_id}/resume")
async def resume_session_route(session_id: str, request: Request):
    """Resume a paused session."""
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(session_id)
    owner = str((meta or {}).get("founder_id") or "")
    if owner:
        require_founder_access(request, owner, min_role="operator")
    from backend.core.cancellation import resume_session
    resume_session(session_id)
    return {"ok": True, "paused": False}


@router.post("/sessions/{session_id}/restart-preview")
async def restart_preview_route(session_id: str, request: Request):
    """Restart the local preview server for this session's workspace.
    Safe to call when the preview shows 'starting up' after a backend restart."""
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(session_id) or {}
    owner = str(meta.get("founder_id") or "")
    if not owner:
        raise HTTPException(status_code=404, detail="session not found")
    require_founder_access(request, owner, min_role="viewer")
    try:
        from backend.tools.git_tools import _root_session_id, WORKSPACE_ROOT as _WORKSPACE_ROOT
        from backend.tools.local_preview import start_local_preview
        import pathlib
        root_sid = _root_session_id(session_id)
        ws_root = pathlib.Path(_WORKSPACE_ROOT)
        workspace = None
        for candidate in ws_root.glob(f"{root_sid}"):
            workspace = candidate
            break
        if workspace is None:
            for candidate in ws_root.glob(f"*"):
                if (candidate / ".oc_session_id").exists():
                    oc = (candidate / ".oc_session_id").read_text().strip()
                    if oc and root_sid.startswith(oc[:8]):
                        workspace = candidate
                        break
        if workspace is None:
            return {"ok": False, "error": "workspace not found for this session"}
        # Find the most recently modified subdir inside the session workspace
        inner = workspace
        subdirs = sorted([p for p in workspace.iterdir() if p.is_dir() and (p / "package.json").exists()],
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if subdirs:
            inner = subdirs[0]
        company_name = meta.get("company") or meta.get("project_name") or ""
        url = await asyncio.to_thread(start_local_preview, str(inner), root_sid, company_name)
        return {"ok": True, "preview_url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/sessions/{session_id}/images")
async def session_images(session_id: str, request: Request):
    """Return design images (logos, brand board) with full base64 from the durable
    store. SSE strips large base64 to avoid browser crashes, so the preview fetches
    the real images here."""
    await _require_session_access(request, session_id, min_role="viewer")
    from backend.core.session_store import load_events
    events = await asyncio.to_thread(load_events, session_id) or []
    logos: dict[str, str] = {}
    brand_images: list[dict] = []
    seen: set[str] = set()

    def _add_image(b64, prompt="", style=""):
        # Skip placeholders ("[base64:N]") and truncated copies — real images are
        # ~1MB; the design agent_done result stores a truncated ~1KB copy.
        if not isinstance(b64, str) or len(b64) < 5000:
            return
        if style in ("wordmark", "icon"):
            # Keep the longest (full) image per logo slot — same PNG header would
            # otherwise let a truncated copy win on a prefix-based dedup.
            if style not in logos or len(b64) > len(logos[style]):
                logos[style] = b64
        else:
            key = b64[:200] + str(len(b64))
            if key in seen:
                return
            seen.add(key)
            brand_images.append({"base64": b64, "prompt": str(prompt or "")[:300]})

    def _scan(obj):
        if isinstance(obj, dict):
            b64 = obj.get("base64")
            if isinstance(b64, str):
                _add_image(b64, obj.get("prompt", ""), obj.get("style", ""))
            for k, v in obj.items():
                if k == "logo_wordmark" and isinstance(v, dict):
                    _add_image(v.get("base64"), v.get("prompt", ""), "wordmark")
                elif k == "logo_icon" and isinstance(v, dict):
                    _add_image(v.get("base64"), v.get("prompt", ""), "icon")
                else:
                    _scan(v)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)

    for _id, e in events:
        if e.get("type") in ("agent_action_result", "agent_done", "stack_artifact"):
            _scan(e.get("result"))
            _scan(e.get("artifact"))
    return {"logos": logos, "brand_images": brand_images[:12]}


@router.get("/sessions/{session_id}/replay")
async def replay_session(session_id: str, request: Request):
    """Stream the full event log for a session as SSE — rebuilds frontend from scratch."""
    await _require_session_access(request, session_id, min_role="viewer")
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
    await _require_session_access(request, session_id, min_role="viewer")
    from backend.core.usage import get_session_cost
    return get_session_cost(session_id)


@router.get("/cost")
async def all_cost(request: Request, founder_id: str = ""):
    """Aggregate token usage and cost. founder_id scopes to that founder (viewer+); global view requires platform admin."""
    from backend.core.usage import get_all_sessions_cost, get_session_cost
    from backend.core.session_store import list_sessions
    from backend.tenant_auth import require_platform_admin
    if founder_id:
        require_founder_access(request, founder_id, min_role="viewer")
        session_ids = [s["session_id"] for s in list_sessions(founder_id, limit=500)]
        sessions = [get_session_cost(sid) for sid in session_ids]
        grand_total = sum(s["total_cost_usd"] for s in sessions)
        return {"sessions": sessions, "grand_total_usd": round(grand_total, 6), "session_count": len(sessions)}
    require_platform_admin(request)
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


@router.get("/sessions/{session_id}/meta")
async def session_meta_public(session_id: str, request: Request):
    """Lightweight session header (goal, company, stack, parent, status, founder) for
    the clean /s/<id> link. AUTH-GATED — you must be logged in and authorized for the
    session's owner; the URL just drops the founder param, it is not public."""
    await _require_session_access(request, session_id, min_role="viewer")
    from backend.core.session_store import get_session_meta, _load_index
    meta = get_session_meta(session_id)
    if not meta:
        # Some sessions live only in the index (no per-session meta.json) — fall back
        # so the /s/<id> link still resolves.
        try:
            meta = _load_index().get(session_id)
        except Exception:
            meta = None
    if not meta:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session_id,
        "founder_id": meta.get("founder_id", ""),
        "goal": meta.get("goal", ""),
        "company_name": meta.get("company_name", ""),
        "stack_id": meta.get("stack_id", ""),
        "status": meta.get("status", ""),
        "created_at": meta.get("created_at", ""),
        "parent_session_id": meta.get("parent_session_id", ""),
        "kind": meta.get("kind", ""),
        "credits_used": int(meta.get("credits_used", 0)),
        "headroom_tokens_saved": int(meta.get("headroom_tokens_saved", 0)),
        "headroom_tokens_before": int(meta.get("headroom_tokens_before", 0)),
        "needs_review": bool(meta.get("needs_review")),
        "review_reason": meta.get("review_reason", ""),
        "deploy_url": meta.get("deploy_url", "") or meta.get("preview_url", ""),
    }


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
    from backend.core.events import publish, reopen_session
    from backend.core.session_store import update_session_status
    from backend.workflow_state import build_session_state, load_session_state
    from backend.core import cancellation
    import asyncio

    founder_id = body.get("founder_id", "")
    instruction = body.get("instruction", "")
    await _require_session_access(request, session_id, min_role="viewer")
    # Clear _completed flag so SSE clients don't get an immediate close after rerun.
    reopen_session(session_id)

    events = await _load_session_events(session_id)
    snapshot = build_session_state(session_id, events) if events else await asyncio.to_thread(load_session_state, session_id)
    session_status = str((snapshot or {}).get("status") or "").lower()
    if session_status and session_status not in {"running", "loading", "done", "error", "stalled", "killed"}:
        raise HTTPException(status_code=409, detail=f"Session cannot be rerun from status={session_status}.")

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
    attempt_id = cancellation.claim_attempt(session_id, agent_name)
    if attempt_id is None:
        raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' already has an active rerun for this session.")
    task_id = f"rerun_{agent_name}:{attempt_id}"

    try:
        update_session_status(session_id, "running")
    except Exception:
        pass
    await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": task_id, "instruction": instruction})

    async def _run():
        try:
            result = await agent.run(ctx)
            await publish(session_id, {"type": "agent_done", "agent": agent_name, "task_id": task_id, "result": result})
            await publish(session_id, {"type": "goal_done", "results": {agent_name: result}, "rerun": agent_name})
        except Exception as e:
            await publish(session_id, {"type": "agent_error", "agent": agent_name, "task_id": task_id, "error": str(e)})
            await publish(session_id, {"type": "goal_error", "error": str(e), "rerun": agent_name})
        finally:
            cancellation.release_attempt(session_id, attempt_id)

    _task = asyncio.create_task(_run())
    cancellation.register_task(session_id, _task, attempt_id=attempt_id, agent_name=agent_name)
    return {"ok": True, "session_id": session_id, "agent": agent_name, "attempt_id": attempt_id, "status": "started"}


@router.post("/sessions/{session_id}/ask")
async def ask_session(session_id: str, body: SessionAskRequest, request: Request):
    from backend.session_digest import answer_session_question

    await _require_session_access(request, session_id, min_role="viewer")
    events = await _load_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session event log not found")
    return answer_session_question(session_id, events, body.question)


@router.post("/approve")
async def approve_task(body: ApproveRequest, request: Request):
    actor_or_body(request)
    await update_task_status(body.task_id, "approved")
    return {"task_id": body.task_id, "status": "approved"}


@router.post("/reject")
async def reject_task(body: RejectRequest, request: Request):
    actor_or_body(request)
    await update_task_status(body.task_id, "rejected")
    return {"task_id": body.task_id, "status": "rejected", "reason": body.reason}


@router.post("/stack/approval")
async def decide_stack_approval(body: StackApprovalDecisionRequest, request: Request):
    actor_id = require_founder_access(request, body.founder_id, min_role="viewer") if body.founder_id else actor_or_body(request)
    actor_role = _approval_actor_role(body.founder_id, actor_id)
    decision = body.decision.lower().strip()
    if decision not in {"approved", "skipped", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be 'approved', 'skipped', or 'rejected'")
    from backend.approval_workflows import decide_approval_request
    from backend.core.events import approval_decision_push
    workflow = decide_approval_request(
        body.session_id,
        body.gate_key,
        decision,
        request_id=body.request_id or body.approval_id,
        actor_id=actor_id,
        actor_role=actor_role,
        note=body.note,
        expected_action_digest=body.expected_action_digest,
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
    resolved_request = workflow["requests"][0]
    resolved_request_id = str(resolved_request.get("id") or resolved_request.get("approval_id") or body.request_id or body.approval_id or "")
    resolved_digest = str(resolved_request.get("action_digest") or body.expected_action_digest or "")
    event["request_id"] = resolved_request_id
    event["approval_id"] = str(resolved_request.get("approval_id") or resolved_request_id)
    event["action_digest"] = resolved_digest
    approval_decision_push(body.session_id, resolved_request_id, resolved_digest, event)
    await publish(body.session_id, event)
    return {"ok": True, "session_id": body.session_id, "gate_key": body.gate_key, "decision": decision, "requests": workflow["requests"]}


def _approval_actor_role(founder_id: str | None, actor_id: str) -> str:
    """Resolve the caller's workspace role; never promote a decision to owner."""
    if founder_id and actor_id == founder_id:
        return "owner"
    if not founder_id:
        return "viewer"
    try:
        from backend.accounts import get_or_create_org
        member = (get_or_create_org(founder_id, founder_id).get("members") or {}).get(actor_id) or {}
        role = str(member.get("role") or "viewer")
        return role if role in {"viewer", "operator", "admin", "owner"} else "viewer"
    except Exception:
        return "viewer"


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


@router.post("/orgs/{org_id}/invites")
async def create_org_invite(org_id: str, body: dict, request: Request):
    actor_id = require_org_access(request, org_id, min_role="admin")
    from backend.accounts import create_org_invite
    try:
        invite = create_org_invite(
            org_id,
            actor_id=actor_id,
            email=str(body.get("email") or ""),
            role=str(body.get("role") or "viewer"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    invite_url = f"{str(request.base_url).rstrip('/')}/invite/{invite['token']}"
    return {"ok": True, "invite": invite, "invite_url": invite_url}


@router.get("/invites/{token}")
async def get_org_invite(token: str):
    from backend.accounts import get_org_invite
    invite = get_org_invite(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.get("status") != "pending":
        raise HTTPException(status_code=410, detail=f"Invite is {invite.get('status')}")
    return invite


@router.post("/invites/{token}/accept")
async def accept_org_invite(token: str, body: dict, request: Request):
    # Identity must come from auth context, never from client-supplied body.
    user_id = str(actor_or_body(request)).strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from backend.accounts import accept_org_invite
    try:
        org = accept_org_invite(token, user_id=user_id)
    except ValueError as exc:
        detail = str(exc)
        code = 410 if "expired" in detail.lower() or "not found" in detail.lower() else 400
        raise HTTPException(status_code=code, detail=detail)
    return {"ok": True, "org": org}


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
        import json as _json
        from backend.config import settings
        from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
        from backend.core.llm_client import get_or_client
        client = get_or_client(settings.openrouter_base_url, settings.openrouter_api_key or settings.agent_model_api_key)
        agents_list = ", ".join(available_agents)
        messages = [
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
                "sales/leads/outreach/crm → sales | technical/code/auth/dashboard → technical | research/market/competitor → research | ops/plan/strategy → ops.\n"
                "code/mvp/technical/build/app → technical | fundraise/investors/pitch → ops.\n\n"
                "For scope=partial, instruction must tell the agent to ONLY do that one thing and skip everything else.\n"
                "Return ONLY JSON."
            )},
            {"role": "user", "content": instruction},
        ]
        resp = client.chat.completions.create(
            model=settings.or_planner_model,
            messages=messages,
            extra_body=openrouter_extra_body(settings.or_planner_model),
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
    from backend.core.session_store import get_session_meta
    from backend.core.session_ids import new_session_id
    from backend.core import cancellation
    orch = get_orchestrator()

    prior_owner = str((await asyncio.to_thread(get_session_meta, body.prior_session_id) or {}).get("founder_id") or "")
    if not prior_owner:
        raise HTTPException(status_code=404, detail="prior session not found")
    if prior_owner != body.founder_id:
        raise HTTPException(status_code=403, detail="prior session does not belong to founder")

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
        from backend.core.events import reopen_session
        ctx = AgentContext(
            goal=instruction,
            founder_id=body.founder_id,
            session_id=session_id,
            shared={"prior_vault_notes": vault_context, "rerun": True},
        )
        agent = orch.specialists[agent_name]
        attempt_id = cancellation.claim_attempt(session_id, agent_name)
        if attempt_id is None:
            raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' already has an active rerun for this session.")
        reopen_session(session_id)
        task_id = f"rerun_{agent_name}:{attempt_id}"
        await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": task_id, "instruction": instruction})
        await publish(session_id, {"type": "chat_intent", "intent": "rerun", "agent": agent_name})

        async def _rerun():
            try:
                result = await agent.run(ctx)
                await publish(session_id, {"type": "agent_done", "agent": agent_name, "task_id": task_id, "result": result})
                await publish(session_id, {"type": "goal_done", "results": {agent_name: result}})
            except Exception as e:
                await publish(session_id, {"type": "agent_error", "agent": agent_name, "error": str(e)})
            finally:
                cancellation.release_attempt(session_id, attempt_id)

        _task = asyncio.create_task(_rerun())
        cancellation.register_task(session_id, _task, attempt_id=attempt_id, agent_name=agent_name)
        return {"session_id": session_id, "status": "running", "prior_session_id": body.prior_session_id, "rerun": agent_name, "attempt_id": attempt_id}

    session_id = new_session_id()
    _exclude_agents = _run_option_exclusions(body.technical_scope, body.marketing_channels)

    async def _run():
        try:
            await orch.continue_run(
                instruction=body.instruction,
                founder_id=body.founder_id,
                prior_session_id=body.prior_session_id,
                agents=body.agents,
                session_id=session_id,
                exclude_agents=_exclude_agents or None,
                research_depth=body.research_depth,
            )
        except Exception as e:
            await publish(session_id, {"type": "goal_error", "error": str(e)})
        finally:
            cancellation.clear(session_id)

    _task = asyncio.create_task(_run())
    cancellation.register_task(session_id, _task)
    return {"session_id": session_id, "status": "running", "prior_session_id": body.prior_session_id}


@router.post("/ask")
async def ask_agent(body: AskRequest, request: Request):
    require_founder_access(request, body.founder_id, min_role="viewer")
    company_id = body.company_id or ""
    if not company_id and body.session_id:
        from backend.core.session_store import get_session_meta
        company_id = str((get_session_meta(body.session_id) or {}).get("company_id") or "")
    company_id = _require_company_scope(request, body.founder_id, company_id)
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
        shared={"context": body.context or "", "company_id": company_id},
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
    company_id = body.company_id or ""
    if not company_id and body.session_id:
        from backend.core.session_store import get_session_meta
        company_id = str((get_session_meta(body.session_id) or {}).get("company_id") or "")
    company_id = _require_company_scope(request, body.founder_id, company_id)
    orch = get_orchestrator()
    base_key = _re.sub(r"_\d+$", "", agent_key)
    agent = orch.specialists.get(agent_key) or orch.specialists.get(base_key)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_key}' not found. Available: {list(orch.specialists.keys())}")

    # ── 1. Company brain — semantic search + canonical fallback ──────────────
    brain_context = ""
    try:
        from backend.tools.company_brain import search_company_brain, _load as _brain_load
        results = search_company_brain(
            body.founder_id,
            body.question,
            limit=6,
            company_id=company_id,
        )
        snippets = results.get("results", [])
        if snippets:
            lines = [f"- [{r.get('source','?')}] {r.get('content','')[:400]}" for r in snippets]
            brain_context = "COMPANY KNOWLEDGE (semantic search):\n" + "\n".join(lines)
        else:
            # Fallback: load ALL canonical records directly
            data = _brain_load(body.founder_id, company_id)
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
        from backend.core.llm_cache import cacheable_messages, is_openrouter_base_url, openrouter_extra_body
        from backend.core.llm_client import get_async_or_client
        client = get_async_or_client(base_url, api_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": body.question},
        ]
        is_openrouter = is_openrouter_base_url(base_url)
        resp = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            extra_body=openrouter_extra_body(model_name) if is_openrouter else None,
            temperature=0.7,
            max_tokens=4000,
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
    """Path-param variant — frontend sends POST /steer/{session_id} with {message, agent_name?} body."""
    from backend.core.events import publish, steer_push
    await _require_session_access(request, session_id, min_role="operator")
    message = body.get("message", "")
    agent_name = str(body.get("agent_name") or "").strip().lower()
    steer_push(session_id, message, agent_name=agent_name)
    event: dict = {"type": "founder_steer", "message": message}
    if agent_name:
        event["target_agent"] = agent_name
    await publish(session_id, event)
    return {"ok": True, "session_id": session_id}


@router.get("/runtime-metrics")
async def runtime_metrics(request: Request):
    """Live runtime counters (shadow match/mismatch, guardrail blocks, budget events,
    native↔JSON fallbacks, …) for monitoring the modernization rollout. Gated like the
    rest of this router — requires an authenticated actor (allowed in dev auth mode)."""
    actor_or_body(request)
    from backend.runtime.metrics import snapshot
    return {"ok": True, "metrics": snapshot()}


@router.post("/copilot/{session_id}")
async def copilot_chat(session_id: str, body: dict, request: Request):
    """Founder copilot — an agentic chat that can query the brain, read/approve goals,
    steer the running agents, run a cycle, and check status, with persistent history."""
    founder_id = await _require_session_access(request, session_id, min_role="operator")
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    from backend.copilot import run_copilot
    fid = body.get("founder_id") or founder_id or ""
    founder_email = request.headers.get("x-astra-email") or body.get("founder_email") or ""
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    mentioned_agents = body.get("mentioned_agents") if isinstance(body.get("mentioned_agents"), list) else []
    return await run_copilot(
        fid,
        session_id,
        message,
        founder_email=founder_email,
        attachments=attachments,
        mentioned_agents=mentioned_agents,
    )


@router.get("/copilot/{session_id}")
async def copilot_history(session_id: str, request: Request):
    """Return the copilot conversation history for a session."""
    await _require_session_access(request, session_id, min_role="viewer")
    from backend.copilot import get_history
    return {"ok": True, "session_id": session_id, "history": get_history(session_id)}


@router.post("/setup")
async def setup_accounts(body: SetupRequest, request: Request):
    """
    Provision GitHub, Vercel, SendGrid accounts from email+password.
    Returns status per service + OAuth URLs for Instagram/TikTok/Meta.
    """
    require_founder_access(request, body.founder_id, min_role="admin")
    from backend.provisioning.account_provisioner import build_provision_plan, provision_all
    if body.preview_only:
        return {
            "founder_id": body.founder_id,
            "email": body.email,
            "stack_id": body.stack_id or "",
            "preview_only": True,
            "provision_plan": build_provision_plan(
                stack_id=body.stack_id or "",
                include_foundation=body.include_foundation,
                required_only=body.required_only,
            ),
        }
    result = await provision_all(
        founder_id=body.founder_id,
        email=body.email,
        password=body.password,
        base_url=body.base_url,
        stack_id=body.stack_id or "",
        required_only=body.required_only,
        include_foundation=body.include_foundation,
    )
    return result


@router.post("/setup/service")
async def save_service_credential(body: SaveCredentialRequest, request: Request):
    """Save a manually entered credential (GitHub PAT, SendGrid key, Vercel token)."""
    require_founder_access(request, body.founder_id, min_role="admin")
    from backend.connectors.contracts import normalize_connector_service, prepare_connector_credentials_for_save
    from backend.provisioning.credentials_store import load_credentials
    from backend.tools.composio_tools import _reset_toolset
    existing = load_credentials(body.founder_id, normalize_connector_service(body.service)) or {}
    try:
        service, prepared = prepare_connector_credentials_for_save(body.service, body.credentials, existing=existing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store_credentials(body.founder_id, service, prepared)
    if service == "composio" and prepared.get("api_key"):
        store_credentials("__platform__", "composio", prepared)
        api_key = prepared["api_key"]
        # Persist to .env so it survives server restarts
        _write_env_key("COMPOSIO_API_KEY", api_key)
        from backend.config import settings
        from backend.tools.composio_tools import _reset_toolset
        settings.composio_api_key = api_key
        _reset_toolset()
    return {"saved": True, "service": service, "founder_id": body.founder_id}


@router.get("/brain/{founder_id}")
async def get_brain(
    founder_id: str,
    request: Request,
    viewer_id: str = "",
    company_id: str = "",
):
    """Return the founder's normalized company brain graph."""
    resolved_company_id = _require_company_scope(request, founder_id, company_id)
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import get_company_brain
    return get_company_brain(
        founder_id,
        viewer_id or actor_id,
        company_id=resolved_company_id,
    )


@router.post("/brain/{founder_id}/sync")
async def sync_brain(founder_id: str, body: BrainSyncRequest, request: Request):
    """Sync connected sources and local agent vault notes into the company brain."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import sync_company_brain
    result = await asyncio.to_thread(
        sync_company_brain,
        founder_id,
        body.sources,
        company_id,
    )
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=actor_id, connector_syncs=len(body.sources or []))
    except Exception as usage_exc:
        logger.warning("Connector sync usage accounting skipped: %s", usage_exc)
    return result


@router.post("/brain/{founder_id}/graph-sync")
async def graph_sync_brain(
    founder_id: str,
    request: Request,
    company_id: str = "",
):
    """Queue an offline GraphRAG v2 SQLite rebuild for the founder."""
    resolved_company_id = _require_company_scope(
        request,
        founder_id,
        company_id,
        min_role="operator",
    )
    if resolved_company_id != founder_id:
        from backend.tools.company_brain import rebuild_company_brain_graph
        return await asyncio.to_thread(
            rebuild_company_brain_graph,
            founder_id,
            resolved_company_id,
        )
    from backend.tools.graph_rag_ingest import run_graph_rag_sync
    return await asyncio.to_thread(run_graph_rag_sync, founder_id)


@router.get("/brain/{founder_id}/graph-rag")
async def graph_rag_visualization(
    founder_id: str,
    request: Request,
    company_id: str = "",
):
    """Return GraphRAG v2 nodes and edges for visualization."""
    resolved_company_id = _require_company_scope(request, founder_id, company_id)
    if resolved_company_id != founder_id:
        from backend.tools.company_brain import get_company_brain_graph
        return await asyncio.to_thread(
            get_company_brain_graph,
            founder_id,
            resolved_company_id,
        )
    from backend.tools.graph_rag_v2 import export_graph_visualization
    return await asyncio.to_thread(export_graph_visualization, founder_id)


@router.get("/brain/{founder_id}/search")
async def search_brain(
    founder_id: str,
    request: Request,
    q: str,
    limit: int = 8,
    viewer_id: str = "",
    company_id: str = "",
):
    """Search company brain records for human UI and agent context."""
    resolved_company_id = _require_company_scope(request, founder_id, company_id)
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import search_company_brain
    return search_company_brain(
        founder_id,
        q,
        limit,
        viewer_id or actor_id,
        resolved_company_id,
    )


@router.get("/brain/{founder_id}/agent-context")
async def brain_agent_context(
    founder_id: str,
    request: Request,
    q: str,
    limit: int = 8,
    viewer_id: str = "",
    company_id: str = "",
):
    """Compact graph context for IDE/MCP/external agents."""
    resolved_company_id = _require_company_scope(request, founder_id, company_id)
    actor_id = require_founder_access(request, founder_id, min_role="viewer")
    from backend.tools.company_brain import company_brain_agent_context
    return company_brain_agent_context(
        founder_id,
        q,
        limit,
        viewer_id or actor_id,
        resolved_company_id,
    )


@router.post("/brain/{founder_id}/ask")
async def ask_brain(founder_id: str, body: BrainAskRequest, request: Request):
    """Return a cited answer synthesized from matched company-brain records."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="viewer",
    )
    from backend.tools.company_brain import ask_company_brain
    return ask_company_brain(founder_id, body.question, body.limit, company_id)


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
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
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
        company_id=company_id,
    )


@router.post("/brain/{founder_id}/records/{record_id}/revise")
async def revise_brain_record(founder_id: str, record_id: str, body: BrainRecordRevisionRequest, request: Request):
    """Create a new version of a Company Brain record and deprecate the prior version."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
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
        company_id=company_id,
    )


@router.post("/brain/{founder_id}/access")
async def configure_brain_access(founder_id: str, body: BrainAccessRequest, request: Request):
    """Configure Company Brain team roles and permission grants."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="admin",
    )
    from backend.tools.company_brain import configure_company_brain_access
    return configure_company_brain_access(
        founder_id=founder_id,
        roles=body.roles,
        role_permissions=body.role_permissions,
        company_id=company_id,
    )


@router.post("/brain/{founder_id}/ingest")
async def ingest_brain_records(founder_id: str, body: BrainIngestRequest, request: Request):
    """Bulk-ingest normalized records from connector/webhook payloads."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import ingest_company_brain_records
    result = await asyncio.to_thread(
        ingest_company_brain_records,
        founder_id,
        body.source,
        body.records,
        company_id,
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
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain_connectors import import_company_brain_sources
    result = await asyncio.to_thread(
        import_company_brain_sources,
        founder_id,
        body.sources,
        body.limit,
        company_id,
    )
    try:
        from backend.accounts import record_usage
        record_usage(founder_id, actor_id=actor_id, connector_syncs=len(result.get("imported_sources", [])))
    except Exception as usage_exc:
        logger.warning("Connector import usage accounting skipped: %s", usage_exc)
    return result


@router.get("/brain/{founder_id}/sync/status")
async def brain_sync_status(
    founder_id: str,
    request: Request,
    company_id: str = "",
):
    """Return continuous sync settings and recent run history."""
    resolved_company_id = _require_company_scope(request, founder_id, company_id)
    from backend.tools.company_brain import get_company_brain_sync_status
    return get_company_brain_sync_status(founder_id, resolved_company_id)


@router.post("/brain/{founder_id}/sync/config")
async def configure_brain_sync(founder_id: str, body: BrainSyncConfigRequest, request: Request):
    """Configure continuous sync for connected providers."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="admin",
    )
    from backend.tools.company_brain import configure_company_brain_sync
    return configure_company_brain_sync(
        founder_id=founder_id,
        enabled=body.enabled,
        sources=body.sources,
        interval_minutes=body.interval_minutes,
        company_id=company_id,
    )


@router.post("/brain/{founder_id}/sync/run")
async def run_brain_sync(founder_id: str, body: BrainSyncRequest, request: Request):
    """Run continuous-sync import now, regardless of schedule."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
    actor_id = require_founder_access(request, founder_id, min_role="operator")
    import asyncio
    from backend.tools.company_brain import configure_company_brain_sync, run_company_brain_sync
    if body.sources:
        configure_company_brain_sync(
            founder_id,
            enabled=True,
            sources=body.sources,
            interval_minutes=60,
            company_id=company_id,
        )
    result = await asyncio.to_thread(
        run_company_brain_sync,
        founder_id,
        True,
        company_id,
    )
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
async def maintain_brain(
    founder_id: str,
    request: Request,
    company_id: str = "",
):
    """Run drift, canonical-gap, and contradiction detection."""
    resolved_company_id = _require_company_scope(
        request,
        founder_id,
        company_id,
        min_role="operator",
    )
    import asyncio
    from backend.tools.company_brain import maintain_company_brain
    return await asyncio.to_thread(
        maintain_company_brain,
        founder_id,
        resolved_company_id,
    )


@router.post("/brain/{founder_id}/proposals/{proposal_id}")
async def update_brain_proposal(founder_id: str, proposal_id: str, body: BrainProposalRequest, request: Request):
    """Update a maintenance proposal status."""
    company_id = _require_company_scope(
        request,
        founder_id,
        body.company_id,
        min_role="operator",
    )
    from backend.tools.company_brain import resolve_company_brain_proposal
    return resolve_company_brain_proposal(
        founder_id,
        proposal_id,
        body.status,
        company_id,
    )


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
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/stripe/callback"
    try:
        url = get_oauth_url_with_email(founder_id, redirect_uri, email)
        return {"url": url}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


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

    fe_base = _public_base_url(settings.frontend_url, default="http://localhost:3000")

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

@router.get("/gmail/oauth-url/{founder_id}")
async def gmail_oauth_url(founder_id: str, request: Request):
    """Return the Google OAuth authorization URL for Gmail API access."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.config import settings
    from urllib.parse import urlencode

    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")

    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/gmail/callback"
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/calendar",
        "state": _oauth_state_create(founder_id),
        "include_granted_scopes": "true",
    })
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@router.get("/google-workspace/oauth-url/{founder_id}")
async def google_workspace_oauth_url(founder_id: str, request: Request):
    """Return the Google OAuth authorization URL for direct Workspace access."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.config import settings
    from backend.tools.google_workspace_api import workspace_scope_string
    from urllib.parse import urlencode

    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")

    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/google-workspace/callback"
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": workspace_scope_string(),
        "state": _oauth_state_create(founder_id),
        "include_granted_scopes": "true",
    })
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@router.get("/gmail/callback")
async def gmail_callback(code: str = "", state: str = "", error: str = ""):
    """
    Google OAuth callback for Gmail API access. Exchanges the code for tokens,
    stores access + refresh token, then redirects to the integrations page.
    """
    import httpx
    from fastapi.responses import RedirectResponse
    from backend.config import settings
    from backend.provisioning.credentials_store import store_credentials

    fe_base = _public_base_url(settings.frontend_url, default="http://localhost:3000")

    if error:
        return RedirectResponse(url=f"{fe_base}/integrations?gmail_error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{fe_base}/integrations?gmail_error=missing_params")

    founder_id = _oauth_state_consume(state)
    if not founder_id:
        return RedirectResponse(url=f"{fe_base}/integrations?gmail_error=invalid_state")
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/gmail/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )

        data = token_resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")

        if not access_token:
            logger.error("Google OAuth exchange failed: %s", data)
            return RedirectResponse(url=f"{fe_base}/integrations?gmail_error=exchange_failed")

        account_email = ""
        try:
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            account_email = str(userinfo_resp.json().get("email") or "")
        except Exception:
            account_email = ""

    creds = {
        "access_token": access_token,
        "connected_via": "google_oauth",
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
    }
    if refresh_token:
        creds["refresh_token"] = refresh_token
    if data.get("expires_in") is not None:
        creds["expires_in"] = data.get("expires_in")
    if data.get("scope"):
        creds["scope"] = data.get("scope")
    if account_email:
        creds["email"] = account_email

    store_credentials(founder_id, "gmail", creds)
    logger.info("Gmail OAuth connected for founder %s", founder_id)

    return RedirectResponse(url=f"{fe_base}/integrations?gmail_connected=1")


@router.get("/google-workspace/callback")
async def google_workspace_callback(code: str = "", state: str = "", error: str = ""):
    """Google OAuth callback for direct Workspace access."""
    import httpx
    from fastapi.responses import RedirectResponse
    from backend.config import settings
    from backend.provisioning.credentials_store import store_credentials

    fe_base = _public_base_url(settings.frontend_url, default="http://localhost:3000")

    if error:
        return RedirectResponse(url=f"{fe_base}/integrations?google_workspace_error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{fe_base}/integrations?google_workspace_error=missing_params")

    founder_id = _oauth_state_consume(state)
    if not founder_id:
        return RedirectResponse(url=f"{fe_base}/integrations?google_workspace_error=invalid_state")
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/google-workspace/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )
        data = token_resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")

        if not access_token:
            logger.error("Google Workspace OAuth exchange failed: %s", data)
            return RedirectResponse(url=f"{fe_base}/integrations?google_workspace_error=exchange_failed")

        account_email = ""
        try:
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            account_email = str(userinfo_resp.json().get("email") or "")
        except Exception:
            account_email = ""

    creds = {
        "access_token": access_token,
        "connected_via": "google_oauth",
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
    }
    if refresh_token:
        creds["refresh_token"] = refresh_token
    if data.get("expires_in") is not None:
        creds["expires_in"] = data.get("expires_in")
    if data.get("scope"):
        creds["scope"] = data.get("scope")
    if account_email:
        creds["email"] = account_email

    store_credentials(founder_id, "google_workspace", creds)
    logger.info("Google Workspace OAuth connected for founder %s", founder_id)

    return RedirectResponse(url=f"{fe_base}/integrations?google_workspace_connected=1")

@router.get("/github/oauth-url/{founder_id}")
async def github_oauth_url(founder_id: str, request: Request):
    """Return the GitHub OAuth authorization URL."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.config import settings
    from urllib.parse import urlencode
    if not settings.github_client_id:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured")
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/github/callback"
    params = urlencode({
        "client_id": settings.github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo workflow read:org",
        "state": _oauth_state_create(founder_id),
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

    fe_base = _public_base_url(settings.frontend_url, default="http://localhost:3000")

    if error:
        return RedirectResponse(url=f"{fe_base}/integrations?github_error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{fe_base}/integrations?github_error=missing_params")

    founder_id = _oauth_state_consume(state)
    if not founder_id:
        return RedirectResponse(url=f"{fe_base}/integrations?github_error=invalid_state")
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/github/callback"

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
    logger.info("GitHub OAuth connected for founder %s", founder_id)

    return RedirectResponse(url=f"{fe_base}/integrations?github_connected=1")


@router.get("/linkedin/oauth-url/{founder_id}")
async def linkedin_oauth_url(founder_id: str, request: Request):
    """Return the LinkedIn OAuth authorization URL."""
    require_founder_access(request, founder_id, min_role="admin")
    from backend.config import settings
    from urllib.parse import urlencode
    if not settings.linkedin_client_id:
        raise HTTPException(status_code=500, detail="LINKEDIN_CLIENT_ID not configured")
    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/linkedin/callback"
    params = urlencode({
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email w_member_social",
        "state": _oauth_state_create(founder_id),
    })
    return {"url": f"https://www.linkedin.com/oauth/v2/authorization?{params}"}


@router.get("/linkedin/callback")
async def linkedin_callback(code: str = "", state: str = "", error: str = ""):
    """LinkedIn OAuth callback. Exchanges code for access token and stores it."""
    import httpx
    from fastapi.responses import RedirectResponse
    from backend.config import settings
    from backend.provisioning.credentials_store import store_credentials

    from urllib.parse import quote as _urlquote
    fe_base = _public_base_url(settings.frontend_url, default="http://localhost:3000")

    def _err_redirect(msg: str):
        return RedirectResponse(url=f"{fe_base}/integrations?linkedin_error={_urlquote(msg, safe='')}")

    if error:
        return _err_redirect(error)
    if not code or not state:
        return _err_redirect("missing_params")

    founder_id = _oauth_state_consume(state)
    if not founder_id:
        return _err_redirect("invalid_state")

    redirect_base = _public_base_url(settings.backend_url, default="http://localhost:8000")
    redirect_uri = f"{redirect_base}/api/linkedin/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )

    try:
        data = resp.json()
    except Exception:
        logger.error("LinkedIn token exchange returned non-JSON response (status %s)", resp.status_code)
        return _err_redirect("exchange_failed")
    access_token = data.get("access_token")
    if not access_token:
        logger.error("LinkedIn OAuth exchange failed: %s", data)
        return _err_redirect("exchange_failed")

    store_credentials(founder_id, "linkedin", {
        "access_token": access_token,
        "expires_in": data.get("expires_in"),
    })
    logger.info("LinkedIn OAuth connected for founder %s", founder_id)
    return RedirectResponse(url=f"{fe_base}/integrations?linkedin_connected=1")


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
    import re as _re
    require_founder_access(request, founder_id, min_role="viewer")
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent):
        raise HTTPException(status_code=400, detail="Invalid agent")
    from backend.tools.obsidian_logger import _note_path, _sessions_root
    path = _note_path(agent, session_id, founder_id)
    # Containment check — never escape founder's sessions root
    root = _sessions_root(founder_id).resolve()
    if not str(path.resolve()).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid path")
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

    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    # Verify Clerk/svix signature
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
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured")
    if not verify_stripe_signature(body, signature, settings.stripe_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Stripe signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    result = apply_platform_billing_event(payload)
    logger.info("platform stripe webhook: %s handled=%s", payload.get("type"), result.get("handled"))
    return result


@router.get("/files/{filename}")
async def serve_file(filename: str, download: bool = False):
    """Serve generated files (PDFs, TXTs) from the vault files/ directory.
    Pass ?download=1 to force attachment download; default is inline (for iframe embeds).
    Search is restricted to vault/files/ — no cross-tenant vault traversal."""
    import mimetypes
    from pathlib import Path
    from fastapi.responses import FileResponse

    import os as _os
    safe_name = Path(filename).name  # strip any directory components
    vault = _os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    # Only search the shared output directories — never recurse into per-founder subtrees.
    files_dir = Path(vault) / "files"
    tmp_dir = Path("/tmp/astra_docs")
    search_dirs = [files_dir, tmp_dir]

    path = None
    # Exact match first.
    for d in search_dirs:
        candidate = d / safe_name
        if candidate.exists() and candidate.is_file():
            path = candidate
            break

    # Stem+extension fuzzy match (agent wrote privacy_policy_35419f.pdf, caller asks
    # for privacy_policy.pdf). Single-level iterdir only — no recursion into subdirs.
    if path is None:
        stem = Path(safe_name).stem
        req_ext = Path(safe_name).suffix.lower()
        best = None
        for d in search_dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
                if not f.is_file():
                    continue
                if f.stem == stem or f.stem.startswith(stem + "_"):
                    if not req_ext or f.suffix.lower() == req_ext:
                        path = f
                        break
                    if best is None:
                        best = f
            if path:
                break
        path = path or best

    if path is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Containment check: resolved path must stay within one of the permitted dirs.
    resolved = path.resolve()
    allowed_roots = [d.resolve() for d in search_dirs if d.exists()]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied")

    safe_name = path.name
    media_type, _ = mimetypes.guess_type(safe_name)
    if not media_type and safe_name.lower().endswith(".pdf"):
        media_type = "application/pdf"
    if not media_type and safe_name.lower().endswith(".pptx"):
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    # PPTX always forces download (browsers can't preview it)
    if download or safe_name.lower().endswith(".pptx"):
        return FileResponse(path, media_type=media_type or "application/octet-stream", filename=safe_name)
    return FileResponse(path, media_type=media_type or "application/octet-stream",
                        headers={"Content-Disposition": f"inline; filename=\"{safe_name}\""})


@router.post("/founders/{founder_id}/deliverables/email")
async def email_deliverable(founder_id: str, request: Request):
    """Email a generated deliverable (PDF/TXT) to the founder, from Astra's no-reply address."""
    require_founder_access(request, founder_id, min_role="operator")
    from backend.deliverables import resolve_deliverable_path, send_deliverable

    body = await request.json()
    filename = str(body.get("filename") or "")
    label = str(body.get("label") or "") or filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    path = resolve_deliverable_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="File not found")

    result = await asyncio.to_thread(send_deliverable, founder_id, path, label)
    if result.get("skipped") == "no_email_on_file":
        raise HTTPException(status_code=400, detail="Connect Gmail in Integrations so Astra knows where to send your deliverables.")
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return {"sent": True}


@router.get("/status/{goal_id}")
async def get_status(goal_id: str, request: Request):
    db = get_supabase()
    goals = db.table("goals").select("*").eq("id", goal_id).execute().data
    if not goals:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal = goals[0]
    founder_id = str(goal.get("founder_id") or goal.get("user_id") or "")
    if not founder_id:
        raise HTTPException(status_code=404, detail="Goal owner could not be resolved")
    require_founder_access(request, founder_id, min_role="viewer")
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

    try:
        require_founder_access(websocket, founder_id, min_role="operator")
    except Exception:
        await websocket.close(code=4401)
        return

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


@router.websocket("/terminal/{session_id}")
async def terminal_takeover(websocket: WebSocket, session_id: str, founder_id: str = ""):
    """Interactive openclaude takeover for a technical/web run.

    Resumes the agent's openclaude session inside a PTY and bridges it to an
    xterm.js terminal in the browser. The founder grabs the keyboard mid-build.

    SECURITY: this exposes RCE as the `astra` user. Authenticate the founder and
    verify the run belongs to them BEFORE spawning the PTY. Fail closed.
    """
    import queue
    import threading
    from backend.core import pty_terminal, cancellation

    await websocket.accept()
    main_loop = asyncio.get_running_loop()

    # ── Auth: caller must own this run. This endpoint spawns interactive
    # openclaude (RCE as `astra`), so the ownership gate FAILS CLOSED on every
    # branch — no dev-mode escape, no empty-owner pass-through. ──
    try:
        # Resolve the authenticated principal; trust this, not the query string.
        auth_user = require_founder_access(websocket, founder_id, min_role="operator")
        from backend.core.session_store import get_session_meta as _meta
        meta = _meta(session_id) or {}
        owner = str(meta.get("founder_id") or "")
        if not auth_user:
            raise PermissionError("authentication required")
        if not owner:
            raise PermissionError("session has no recorded owner")
        if owner != auth_user:
            raise PermissionError("session does not belong to caller")
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"t": "error", "message": f"unauthorized: {e}"}))
        except Exception:
            pass
        await websocket.close(code=4403)
        return

    # Pause the autonomous agent so it stops stepping on the openclaude session
    # while the founder drives it by hand.
    try:
        cancellation.pause_session(session_id)
    except Exception:
        pass

    closed = threading.Event()

    def _on_output(data: bytes) -> None:
        if closed.is_set():
            return
        fut = asyncio.run_coroutine_threadsafe(_safe_send_bytes(websocket, data), main_loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass

    try:
        term = await asyncio.to_thread(pty_terminal.open_takeover, session_id)
    except Exception as e:
        logger.error("terminal takeover spawn failed: %s", e)
        try:
            await websocket.send_text(json.dumps({"t": "error", "message": f"spawn failed: {e}"}))
        except Exception:
            pass
        await websocket.close(code=1011)
        try:
            cancellation.resume_session(session_id)
        except Exception:
            pass
        return

    term.set_output(_on_output)

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data_b = msg.get("bytes")
            if data_b is not None:
                term.write(data_b)
                continue
            text = msg.get("text")
            if text is None:
                continue
            try:
                ctrl = json.loads(text)
            except Exception:
                # Plain text frame → treat as keystrokes.
                term.write(text.encode("utf-8", "ignore"))
                continue
            if isinstance(ctrl, dict) and ctrl.get("t") == "resize":
                try:
                    term.resize(int(ctrl.get("cols", 120)), int(ctrl.get("rows", 32)))
                except Exception:
                    pass
            elif isinstance(ctrl, dict) and ctrl.get("t") == "input":
                term.write(str(ctrl.get("data", "")).encode("utf-8", "ignore"))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("terminal ws loop error: %s", e)
    finally:
        closed.set()
        term.set_output(None)
        try:
            pty_terminal.close_takeover(session_id)
        except Exception:
            pass
        try:
            cancellation.resume_session(session_id)
        except Exception:
            pass


async def _safe_send_bytes(websocket: WebSocket, data: bytes) -> None:
    try:
        await websocket.send_bytes(data)
    except Exception:
        pass


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


async def _run_web_task_ws(
    websocket: WebSocket,
    *,
    founder_id: str,
    service: str,
    task_type: str,
    goal: str,
    success_criteria: list[str] | None = None,
) -> None:
    import uuid

    from backend.tools.web_tasks import get_web_task_session, resume_web_task_session, start_web_task_background

    try:
        require_founder_access(websocket, founder_id, min_role="viewer")
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4403)
        return

    await websocket.accept()
    task_id = str(uuid.uuid4())
    request_obj = start_web_task_background(
        task_type=task_type,
        service=service,
        goal=goal,
        success_criteria=success_criteria or [],
        founder_id=founder_id,
        session_id=task_id,
        task_id=task_id,
        agent="web_navigator",
    )
    session = get_web_task_session(request_obj.task_id)
    if not session:
        await websocket.send_text(json.dumps({"type": "error", "message": "Could not start website task."}))
        await websocket.close()
        return

    def _map_fields(fields: list[dict]) -> list[dict]:
        mapped = []
        for field in fields or []:
            mapped.append({
                "name": field.get("key") or field.get("name") or "",
                "label": field.get("label") or field.get("key") or "Field",
                "type": field.get("type") or "text",
                "required": field.get("required", True),
            })
        return mapped

    async def _recv_loop() -> None:
        try:
            async for msg_text in websocket.iter_text():
                try:
                    msg = json.loads(msg_text)
                except Exception:
                    continue
                if msg.get("type") == "founder_input":
                    ok = resume_web_task_session(task_id, msg.get("data", {}))
                    if not ok:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "This website task is not currently waiting for founder input.",
                        }))
                elif msg.get("type") == "cancel":
                    break
        except WebSocketDisconnect:
            pass

    async def _send_loop() -> None:
        queue = session["event_queue"]
        while True:
            event = await queue.get()
            if event is None:
                break
            event_type = event.get("type")
            if event_type in {"web_task_started", "web_task_state", "web_task_resumed"}:
                state = str(event.get("state") or event.get("task_type") or "working").replace("_", " ")
                note = str(event.get("note") or "")
                await websocket.send_text(json.dumps({
                    "type": "status",
                    "step": state.title(),
                    "step_num": 1,
                    "total": 3,
                    "message": note,
                }))
            elif event_type == "web_task_needs_user":
                blocker = event.get("blocker") or {}
                await websocket.send_text(json.dumps({
                    "type": "interaction_needed",
                    "step": str(event.get("service") or "Website task").title(),
                    "message": blocker.get("message") or "Astra needs your input to continue.",
                    "fields": _map_fields(blocker.get("fields") or []),
                }))
            elif event_type == "web_task_completed":
                await websocket.send_text(json.dumps({
                    "type": "done",
                    "service": event.get("service"),
                    "result": (event.get("result") or {}).get("artifacts") or {},
                }))
                break
            elif event_type == "web_task_failed":
                result = event.get("result") or {}
                blocker = result.get("blocker") or {}
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": blocker.get("message") or "Website task failed.",
                }))
                break

    recv_task = asyncio.create_task(_recv_loop())
    send_task = asyncio.create_task(_send_loop())
    done, pending = await asyncio.wait({recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        try:
            await task
        except Exception:
            pass
    try:
        await websocket.close()
    except Exception:
        pass


# ── Integration connect WebSocket endpoints ───────────────────────────────────

@router.websocket("/connect/github/stream/{founder_id}")
async def connect_github_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="github",
        task_type="retrieve_api_key",
        goal="Sign in to GitHub and retrieve a personal access token.",
        success_criteria=["github_token_extracted"],
    )


@router.websocket("/connect/vercel/stream/{founder_id}")
async def connect_vercel_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="vercel",
        task_type="retrieve_deploy_token",
        goal="Sign in to Vercel and retrieve a deploy token.",
        success_criteria=["deploy_token_extracted"],
    )


@router.websocket("/connect/sendgrid/stream/{founder_id}")
async def connect_sendgrid_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="sendgrid",
        task_type="retrieve_api_key",
        goal="Sign in to SendGrid and retrieve an API key.",
        success_criteria=["api_key_extracted"],
    )


@router.websocket("/connect/klaviyo/stream/{founder_id}")
async def connect_klaviyo_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="klaviyo",
        task_type="retrieve_api_key",
        goal="Sign in to Klaviyo and retrieve an API key.",
        success_criteria=["api_key_extracted"],
    )


@router.websocket("/connect/printful/stream/{founder_id}")
async def connect_printful_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="printful",
        task_type="retrieve_api_key",
        goal="Sign in to Printful and retrieve an API key.",
        success_criteria=["api_key_extracted"],
    )


@router.websocket("/connect/yelp/stream/{founder_id}")
async def connect_yelp_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="yelp",
        task_type="retrieve_api_key",
        goal="Sign in to Yelp Fusion and retrieve an API key.",
        success_criteria=["api_key_extracted"],
    )


@router.websocket("/connect/lemonsqueezy/stream/{founder_id}")
async def connect_lemonsqueezy_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="lemonsqueezy",
        task_type="retrieve_api_key",
        goal="Sign in to Lemon Squeezy and retrieve an API key.",
        success_criteria=["api_key_extracted"],
    )


@router.websocket("/connect/square/stream/{founder_id}")
async def connect_square_stream(websocket: WebSocket, founder_id: str):
    await _run_web_task_ws(
        websocket,
        founder_id=founder_id,
        service="square_sandbox",
        task_type="retrieve_api_key",
        goal="Sign in to Square Developer and retrieve a sandbox access token.",
        success_criteria=["sandbox_token_extracted"],
    )


@router.get("/connect/twilio/guide/{founder_id}")
async def connect_twilio_guide(founder_id: str, request: Request):
    from backend.tools.provision_integrations import provision_twilio_guide
    return provision_twilio_guide(founder_id)


@router.get("/setup/composio/connected/{founder_id}")
async def composio_connected(founder_id: str, request: Request):
    """Return per-app Composio connection status for the founder."""
    require_founder_access(request, founder_id, min_role="viewer")
    import asyncio
    from backend.provisioning.credentials_store import load_all_credentials
    from backend.tools.integration_connect import get_composio_app_status
    status = await asyncio.to_thread(get_composio_app_status, founder_id)
    try:
        creds = load_all_credentials(founder_id)
    except Exception:
        creds = {}
    for saved in creds.values():
        if not isinstance(saved, dict):
            continue
        if saved.get("connected_via") != "composio_oauth":
            continue
        app = str(saved.get("composio_app") or "").strip()
        if app and not status.get(app):
            status[app] = True
    # Direct Gmail OAuth (independent of Composio)
    gmail_creds = creds.get("gmail") or {}
    if isinstance(gmail_creds, dict) and gmail_creds.get("connected_via") == "google_oauth":
        status["gmail_direct"] = True
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
    per_page: int = 100,
):
    """
    Search contacts. Priority:
      1. Local Supabase DB (free, instant)
      2. Apollo API (if available on plan) — credit-free, returns up to 100
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

    # 1. Query local DB only when no specific filters are set.
    # With filters the user expects fresh, targeted results — local cache
    # would return stale/unrelated contacts and ignore the filters.
    has_filters = any([titles_list, industries_list, locations_list, keywords_list, seniorities_list, sizes_list])
    if not has_filters:
        from backend.tools.contact_scraper import search_local_contacts
        local = await asyncio.to_thread(
            search_local_contacts,
            founder_id=founder_id,
            titles=None,
            industries=None,
            locations=None,
            company_sizes=None,
            seniorities=None,
            page=page,
            limit=per_page,
        )
        if local["contacts"]:
            return {**local, "source": "local_db", "seeding": False}

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

    # 3. Web scraping fallback (quick single-query scrape)
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
        from backend.db.client import get_outreach_db
        db = get_outreach_db()
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


@router.post("/outreach/parse-audience")
async def parse_audience_prompt(body: dict, request: Request):
    """Use a fast LLM to convert a natural-language audience description into
    structured Apollo search filters (titles, locations, industries, etc.)."""
    import json, re as _re
    founder_id = str(body.get("founder_id") or actor_or_body(request)).strip()
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    require_founder_access(request, founder_id, min_role="viewer")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "No prompt provided"}, status_code=400)

    llm_prompt = (
        f'Convert this target audience description into Apollo.io search filters.\n\n'
        f'Description: "{prompt}"\n\n'
        'Return a JSON object with:\n'
        '- titles: comma-separated job titles (e.g. "Owner, Manager, Chef")\n'
        '- locations: comma-separated locations (e.g. "Arizona, United States")\n'
        '- industries: comma-separated Apollo industry names (e.g. "Restaurants, Food & Beverages")\n'
        '- keywords: any extra search terms not covered above\n'
        '- seniorities: JSON array from ["c_suite","vp","director","manager","senior","entry","owner"]\n'
        '- company_sizes: JSON array from ["1,10","11,50","51,200","201,500","501,1000","1001,5000"]\n\n'
        'Common Apollo industry names: Restaurants, "Food & Beverages", "Computer Software", '
        '"Information Technology & Services", "Marketing & Advertising", "Financial Services", '
        'Healthcare, "Real Estate", Retail, Construction, "Legal Services", Accounting, '
        'Manufacturing, Education, "Consumer Goods", "Health, Wellness & Fitness"\n\n'
        'Return ONLY the JSON object.'
    )

    try:
        from backend.tools._llm import generate
        raw = await asyncio.to_thread(generate, llm_prompt, 400, False, "fast", 0.1)
        from backend.core.json_extract import extract_json
        parsed = extract_json(raw, prefer_keys=("titles", "industries"))
        if not parsed:
            raise ValueError("no JSON in response")
        return {
            "titles":       str(parsed.get("titles") or ""),
            "locations":    str(parsed.get("locations") or ""),
            "industries":   str(parsed.get("industries") or ""),
            "keywords":     str(parsed.get("keywords") or ""),
            "seniorities":  parsed.get("seniorities") if isinstance(parsed.get("seniorities"), list) else [],
            "company_sizes": parsed.get("company_sizes") if isinstance(parsed.get("company_sizes"), list) else [],
        }
    except Exception as e:
        logger.warning("parse-audience failed: %s", e)
        # Fallback: put the whole prompt in keywords so search still runs
        return {"titles": "", "locations": "", "industries": "", "keywords": prompt, "seniorities": [], "company_sizes": []}


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

        from backend.config import settings as _settings

        # Free path: no Hunter key, or no curated-domain match → scrape free sources.
        def _free_discovery() -> dict:
            from backend.tools.contact_scraper import bulk_discover_and_store
            # Derive rough title/industry hints from the audience text.
            words = [w for w in audience_lower.replace(",", " ").split() if len(w) > 2]
            titles = [t for t in ("founder", "ceo", "owner", "cto", "head", "director", "vp", "manager") if t in audience_lower] or ["founder", "owner"]
            disc = bulk_discover_and_store(
                founder_id=founder_id,
                titles=titles,
                industries=[target_audience],
                domains=domains[:limit] if domains else None,
                hn_keyword=" ".join(words[:3]),
                limit_per_source=max(limit * 3, 30),
            )
            return {
                "contacts_found": disc.get("usable", 0),
                "contacts_stored": disc.get("stored", 0),
                "domains_searched": domains[:limit],
                "source": "free_discovery",
                "sources": disc.get("sources", {}),
            }

        if not _settings.hunter_api_key:
            return _free_discovery()

        if not domains:
            return _free_discovery()

        result = hunter_search_by_domains(
            founder_id=founder_id,
            domains=domains[:limit],
            seniority="",
            department="",
        )
        result["domains_searched"] = domains[:limit]
        # If Hunter produced nothing, fall back to free scraping.
        if not result.get("contacts_found") and not result.get("contacts_stored"):
            return _free_discovery()
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


@router.post("/outreach/enrich/batch")
async def outreach_enrich_batch(request: Request, body: dict):
    """
    Reveal emails for up to 15 contacts by Apollo ID.
    Costs 1 credit per contact — only call for contacts you'll actually contact.
    Body: { "founder_id": "...", "contacts": [{"apollo_id": "...", "first_name": "...", "company_name": "..."}] }
    """
    founder_id = body.get("founder_id", "")
    require_founder_access(request, founder_id, min_role="operator")
    from backend.tools.apollo_tools import apollo_enrich_batch, MAX_ENRICH_BATCH
    contacts = (body.get("contacts") or [])[:MAX_ENRICH_BATCH]
    if not contacts:
        raise HTTPException(status_code=400, detail=f"contacts list is required (max {MAX_ENRICH_BATCH})")
    results = await asyncio.to_thread(apollo_enrich_batch, contacts)
    return {"enriched": results, "count": len(results), "credits_used": len([r for r in results if r.get("enriched")])}


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

    db = get_outreach_db()
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
    return {"saved": len(result.data), "contacts": result.data, "founder_id": founder_id}


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
    db = get_outreach_db()
    query = db.table("outreach_contacts").select("*").eq("founder_id", founder_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).range((page - 1) * limit, page * limit - 1).execute()

    contacts = result.data or []

    return {
        "contacts": contacts,
        "page": page,
        "founder_id": founder_id,
        "seeding": False,
    }


@router.get("/outreach/contacts/{founder_id}/semantic")
async def semantic_search_contacts(founder_id: str, request: Request, q: str = "", limit: int = 25):
    """Natural-language ('smart') search over the founder's saved contacts.
    Free TF-IDF ranking — no paid embeddings."""
    require_founder_access(request, founder_id, min_role="viewer")
    if not q.strip():
        return {"contacts": [], "query": q}
    db = get_outreach_db()
    rows = db.table("outreach_contacts").select("*").in_(
        "founder_id", list({founder_id, "__global__"})
    ).execute().data or []
    from backend.outreach.semantic_search import rank_contacts
    ranked = rank_contacts(q, rows, limit=limit)
    return {"contacts": ranked, "query": q, "total": len(ranked)}


@router.patch("/outreach/contacts/{founder_id}/{contact_id}")
async def update_outreach_contact(founder_id: str, contact_id: str, body: dict, request: Request):
    """Update a contact's status or tags."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()
    allowed = {k: v for k, v in body.items() if k in ("status", "tags", "title", "company_name")}
    result = db.table("outreach_contacts").update(allowed).eq("id", contact_id).eq("founder_id", founder_id).execute()
    return result.data[0] if result.data else {}


@router.post("/outreach/import-csv/{founder_id}")
async def import_contacts_csv(founder_id: str, body: dict, request: Request):
    """Import contacts from raw CSV text. Header names are matched flexibly
    (email/e-mail, first/first_name, company/company_name, etc.)."""
    require_founder_access(request, founder_id, min_role="operator")
    import csv as _csv
    import io as _io

    text = (body.get("csv") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="csv text is required")

    # Flexible header → field mapping.
    field_map = {
        "email": "email", "e-mail": "email", "email address": "email",
        "first": "first_name", "first name": "first_name", "firstname": "first_name", "fname": "first_name",
        "last": "last_name", "last name": "last_name", "lastname": "last_name", "lname": "last_name",
        "name": "_full_name", "full name": "_full_name",
        "title": "title", "job title": "title", "role": "title", "position": "title",
        "company": "company_name", "company name": "company_name", "organization": "company_name", "org": "company_name",
        "domain": "company_domain", "website": "company_domain", "company domain": "company_domain",
        "linkedin": "linkedin_url", "linkedin url": "linkedin_url",
        "city": "city", "state": "state", "country": "country",
        "industry": "industry", "company size": "company_size", "size": "company_size",
        "seniority": "seniority",
    }

    reader = _csv.DictReader(_io.StringIO(text))
    rows: list[dict] = []
    skipped = 0
    for raw in reader:
        rec: dict = {"founder_id": founder_id, "source": "csv_import"}
        full_name = ""
        for k, v in raw.items():
            if k is None or v is None:
                continue
            key = k.strip().lower()
            mapped = field_map.get(key)
            if not mapped:
                # Fallback patterns — handles Google Contacts CSV export columns
                # like "E-mail 1 - Value", "Organization Name", "Organization Title".
                if "e-mail" in key and "value" in key:
                    mapped = "email"
                elif key.startswith("email") and "value" not in key:
                    mapped = "email"
                elif "organization" in key and "title" in key:
                    mapped = "title"
                elif "organization" in key and "name" in key:
                    mapped = "company_name"
                elif "organization" in key and "department" in key:
                    continue
            if not mapped:
                continue
            val = v.strip()
            if not val:
                continue
            if mapped == "_full_name":
                full_name = full_name or val
            elif mapped == "email":
                # Keep the first email found (E-mail 1 before E-mail 2).
                if not rec.get("email"):
                    rec["email"] = val
            elif not rec.get(mapped):
                rec[mapped] = val
        if not rec.get("first_name") and full_name:
            parts = full_name.split()
            rec["first_name"] = parts[0]
            if len(parts) > 1:
                rec["last_name"] = " ".join(parts[1:])
        email = (rec.get("email") or "").strip().lower()
        if not email or "@" not in email:
            skipped += 1
            continue
        rec["email"] = email
        rows.append(rec)

    if not rows:
        return {"imported": 0, "skipped": skipped, "error": "No rows with a valid email column were found."}

    db = get_outreach_db()
    for i in range(0, len(rows), 1000):
        db.table("outreach_contacts").upsert(
            rows[i:i + 1000], on_conflict="founder_id,email", ignore_duplicates=False
        ).execute()
    return {"imported": len(rows), "skipped": skipped, "founder_id": founder_id}


@router.post("/outreach/import-gmail/{founder_id}")
async def import_contacts_gmail(founder_id: str, body: dict, request: Request):
    """Import contacts from the founder's Google account via the People API.

    The frontend passes the Google OAuth access_token obtained at sign-in (with
    contacts.readonly + contacts.other.readonly scopes). Pulls both saved
    contacts ('connections') and auto-saved 'otherContacts' (people you've
    emailed), normalizes them, and stores them in the free contact DB.
    """
    require_founder_access(request, founder_id, min_role="operator")
    token = (body.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required")

    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    person_fields = "names,emailAddresses,organizations"
    collected: list[dict] = []

    def _harvest(people: list[dict]) -> None:
        for p in people:
            emails = p.get("emailAddresses") or []
            if not emails:
                continue
            email = (emails[0].get("value") or "").strip().lower()
            if not email or "@" not in email:
                continue
            name = (p.get("names") or [{}])[0]
            org = (p.get("organizations") or [{}])[0]
            collected.append({
                "founder_id": founder_id,
                "email": email,
                "first_name": name.get("givenName", ""),
                "last_name": name.get("familyName", ""),
                "title": org.get("title", ""),
                "company_name": org.get("name", ""),
                "source": "gmail",
            })

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Saved contacts (connections), paginated.
            page_token = ""
            for _ in range(10):  # cap at 10 pages (~2000 contacts)
                params = {"personFields": person_fields, "pageSize": 200}
                if page_token:
                    params["pageToken"] = page_token
                r = await client.get(
                    "https://people.googleapis.com/v1/people/me/connections",
                    headers=headers, params=params,
                )
                if r.status_code == 401:
                    raise HTTPException(status_code=401, detail="Google token expired or missing contacts scope. Sign out and sign in again.")
                if r.status_code != 200:
                    break
                data = r.json()
                _harvest(data.get("connections", []))
                page_token = data.get("nextPageToken", "")
                if not page_token:
                    break

            # 2. Other contacts (people you've emailed but not saved).
            page_token = ""
            for _ in range(10):
                params = {"readMask": "names,emailAddresses", "pageSize": 200}
                if page_token:
                    params["pageToken"] = page_token
                r = await client.get(
                    "https://people.googleapis.com/v1/otherContacts",
                    headers=headers, params=params,
                )
                if r.status_code != 200:
                    break
                data = r.json()
                _harvest(data.get("otherContacts", []))
                page_token = data.get("nextPageToken", "")
                if not page_token:
                    break
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Gmail import failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Google People API error: {e}")

    # Dedupe by email, keeping the richest record.
    by_email: dict[str, dict] = {}
    for c in collected:
        prev = by_email.get(c["email"])
        if prev is None or (not prev.get("first_name") and c.get("first_name")):
            by_email[c["email"]] = c
    rows = list(by_email.values())

    if not rows:
        return {"imported": 0, "founder_id": founder_id, "note": "No contacts with email addresses were found in this Google account."}

    db = get_outreach_db()
    for i in range(0, len(rows), 1000):
        db.table("outreach_contacts").upsert(
            rows[i:i + 1000], on_conflict="founder_id,email", ignore_duplicates=False
        ).execute()
    return {"imported": len(rows), "founder_id": founder_id}


# ── Outreach lists ────────────────────────────────────────────────────────────

@router.get("/outreach/lists/{founder_id}")
async def get_outreach_lists(founder_id: str, request: Request):
    """List all saved contact lists."""
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_outreach_db()
    result = db.table("outreach_lists").select("*").eq("founder_id", founder_id).order("created_at", desc=True).execute()
    return {"lists": result.data}


@router.post("/outreach/lists/{founder_id}")
async def create_outreach_list(founder_id: str, body: dict, request: Request):
    """Create a contact list and optionally add contacts to it."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()
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
    db = get_outreach_db()
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
    db = get_outreach_db()
    result = db.table("outreach_campaigns").select("*").eq("founder_id", founder_id).order("created_at", desc=True).execute()
    return {"campaigns": result.data}


@router.post("/outreach/campaigns/{founder_id}")
async def create_campaign(founder_id: str, body: dict, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()
    row = {
        "founder_id": founder_id,
        "name": body.get("name", "New Campaign"),
        "status": body.get("status", "draft"),
        "from_name": body.get("from_name", ""),
        "from_email": body.get("from_email", ""),
        "reply_to": body.get("reply_to", ""),
        "steps": body.get("steps", []),
        "product_name": body.get("product_name", ""),
        "value_prop": body.get("value_prop", ""),
        "daily_limit": body.get("daily_limit", 50),
        "send_provider": body.get("send_provider", "gmail"),
    }
    # target_audience: audience targeting criteria for Apollo search.
    # Requires column: ALTER TABLE outreach_campaigns ADD COLUMN IF NOT EXISTS target_audience JSONB DEFAULT '{}'::jsonb;
    if body.get("target_audience"):
        row["target_audience"] = body["target_audience"]
    try:
        result = db.table("outreach_campaigns").insert(row).execute()
    except Exception:
        row.pop("target_audience", None)
        result = db.table("outreach_campaigns").insert(row).execute()
    return result.data[0]


@router.patch("/outreach/campaigns/{founder_id}/{campaign_id}")
async def update_campaign(founder_id: str, campaign_id: str, body: dict, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()
    allowed = {k: v for k, v in body.items() if k in (
        "name", "status", "from_name", "from_email", "reply_to",
        "steps", "product_name", "value_prop", "daily_limit", "send_provider",
        "target_audience",
    )}
    result = db.table("outreach_campaigns").update(allowed).eq("id", campaign_id).eq("founder_id", founder_id).execute()
    return result.data[0] if result.data else {}


@router.delete("/outreach/campaigns/{founder_id}/{campaign_id}")
async def delete_campaign(founder_id: str, campaign_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()
    db.table("outreach_campaigns").delete().eq("id", campaign_id).eq("founder_id", founder_id).execute()
    return {"deleted": campaign_id}


@router.post("/outreach/campaigns/{founder_id}/{campaign_id}/contacts")
async def add_contacts_to_campaign(founder_id: str, campaign_id: str, body: dict, request: Request):
    """Enroll contacts from a list (or explicit IDs) into a campaign."""
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()

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
    db = get_outreach_db()
    result = db.table("outreach_campaign_contacts").select(
        "*, outreach_contacts(first_name, last_name, email, company_name, title)"
    ).eq("campaign_id", campaign_id).execute()
    return {"contacts": result.data}


@router.get("/outreach/campaigns/{founder_id}/{campaign_id}/stats")
async def get_campaign_stats(founder_id: str, campaign_id: str, request: Request):
    require_founder_access(request, founder_id, min_role="viewer")
    db = get_outreach_db()
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
    db = get_outreach_db()
    campaigns = db.table("outreach_campaigns").select("*").eq("id", campaign_id).eq("founder_id", founder_id).execute()
    if not campaigns.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = campaigns.data[0]

    from backend.tools.lead_finder import build_outreach_sequence
    result = await asyncio.to_thread(
        build_outreach_sequence,
        product_name=campaign.get("product_name", "the product"),
        value_prop=campaign.get("value_prop", ""),
        lead_name="{{first_name}}",
        lead_company="{{company_name}}",
        lead_title="{{title}}",
        sequence_length=3,
    )
    # build_outreach_sequence returns {"sequence": [...], ...} — extract the list
    steps = result.get("sequence") if isinstance(result, dict) else result

    db.table("outreach_campaigns").update({"steps": steps}).eq("id", campaign_id).execute()
    return {"steps": steps, "campaign_id": campaign_id}


@router.post("/outreach/campaigns/{founder_id}/{campaign_id}/send-batch")
async def send_campaign_batch(founder_id: str, campaign_id: str, request: Request):
    """
    Send the next due email to each active contact in the campaign via the
    founder's connected Gmail (Composio). Respects daily_limit.
    """
    require_founder_access(request, founder_id, min_role="operator")
    db = get_outreach_db()

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


@router.get("/track/open/{campaign_id}/{cc_id}/{step_index}")
async def track_open(campaign_id: str, cc_id: str, step_index: int):
    """Record email open event. Returns 1x1 transparent GIF.
    No founder_id in the path — this URL is embedded in emails sent to
    external prospects, who could otherwise read the founder's email-derived
    id straight out of the pixel's img src. Looked up from campaign_id instead."""
    from fastapi.responses import Response
    try:
        db = get_outreach_db()
        campaign = db.table("outreach_campaigns").select("founder_id").eq("id", campaign_id).execute()
        founder_id = campaign.data[0]["founder_id"] if campaign.data else None
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


@router.get("/track/click/{campaign_id}/{cc_id}/{step_index}")
async def track_click(campaign_id: str, cc_id: str, step_index: int, url: str = ""):
    """Record click event and redirect to original URL. Same founder_id-out-of-
    the-path reasoning as track_open."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import unquote
    try:
        db = get_outreach_db()
        campaign = db.table("outreach_campaigns").select("founder_id").eq("id", campaign_id).execute()
        founder_id = campaign.data[0]["founder_id"] if campaign.data else None
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


# ── Web Navigator sandbox ──────────────────────────────────────────────────────

@router.post("/web-navigator/start")
async def web_navigator_start(body: dict, request: Request):
    """Start a web navigator session. Returns session_id for streaming."""
    import uuid
    from backend.tools.web_tasks import create_web_task_session, start_web_task_background

    founder_id = str(body.get("founder_id") or "")
    if founder_id:
        require_founder_access(request, founder_id, min_role="viewer")
    goal = body.get("goal", "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")
    task_type = str(body.get("task_type") or ("generic" if body.get("url") else "")).strip() or "generic"
    service = str(body.get("service") or ("generic" if body.get("url") else "")).strip() or "generic"
    start_url = body.get("url", "").strip()
    success_criteria = body.get("success_criteria") or (["dashboard"] if start_url else [])
    task_id = str(body.get("task_id") or uuid.uuid4())
    create_web_task_session(task_id)
    request_obj = start_web_task_background(
        task_type=task_type,
        service=service,
        goal=goal,
        success_criteria=success_criteria,
        credentials=body.get("credentials") or {},
        founder_id=founder_id,
        session_id=str(body.get("session_id") or task_id),
        task_id=task_id,
        start_url=start_url,
        metadata=dict(body.get("metadata") or {}),
    )
    return {"session_id": request_obj.task_id, "task_id": request_obj.task_id}


@router.get("/web-navigator/stream/{session_id}")
async def web_navigator_stream(session_id: str, request: Request):
    """SSE stream of events for a running web navigator session."""
    from fastapi.responses import StreamingResponse
    from backend.tools.web_tasks import get_web_task_session

    session = get_web_task_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    request_obj = session.get("request")
    founder_id = str(getattr(request_obj, "founder_id", "") or "")
    if founder_id:
        require_founder_access(request, founder_id, min_role="viewer")

    async def _gen():
        queue: asyncio.Queue = session["event_queue"]
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.post("/web-navigator/respond/{session_id}")
async def web_navigator_respond(session_id: str, body: dict, request: Request):
    """Provide user input to a paused web navigator session."""
    from backend.tools.web_tasks import get_web_task_session, resume_web_task_session
    from backend.tools.web_tasks.store import load_snapshot

    task_session = get_web_task_session(session_id) or {}
    request_obj = task_session.get("request")
    founder_id_wt = str(getattr(request_obj, "founder_id", "") or "")
    if not founder_id_wt:
        # Fall back to snapshot-derived session for legacy records
        snapshot_session_id = getattr(request_obj, "session_id", "") or session_id
        snapshot = load_snapshot(snapshot_session_id, session_id)
        if snapshot and snapshot.request.session_id:
            await _require_session_access(request, snapshot.request.session_id, min_role="viewer")
        else:
            raise HTTPException(status_code=403, detail="Cannot verify session ownership")
    else:
        require_founder_access(request, founder_id_wt, min_role="viewer")
    ok = resume_web_task_session(session_id, body.get("fields", {}))
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found or not waiting for input")
    return {"ok": True}

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from backend.api.schemas import RunCreateRequest
from backend.control_plane.budget import BudgetExceededError, get_default_budget_service
from backend.control_plane.models import Run
from backend.control_plane.rollout import assign_run_features
from backend.control_plane.supabase_repositories import (
    SupabaseRunRepository,
    durable_create_run_with_event,
)
from backend.core.factory import get_orchestrator
from backend.core.session_ids import new_session_id
from backend.credits.store import get_balance
from backend.observability.tracing import run_span
from backend.safety.content_filter import screen_goal
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)
_INITIAL_RUN_RESERVATION_USD = 0.10


async def _maybe_start_shadow_run(
    *,
    founder_id: str,
    instruction: str,
    source_run_id: str,
    company_id: str,
    workspace_id: str,
    chapter_id: str,
    stack_id: str | None,
    constraints: dict[str, Any] | None,
    engine: str,
    feature_assignment: dict[str, Any],
    parent_run_id: str | None = None,
    prior_session_id: str | None = None,
    continue_run: bool = False,
) -> str:
    if engine != "legacy" or not bool((feature_assignment or {}).get("temporal_shadow")):
        return ""
    try:
        from backend.control_plane.temporal.shadow_runtime import start_shadow_run

        return await start_shadow_run(
            founder_id=founder_id,
            instruction=instruction,
            source_run_id=source_run_id,
            company_id=company_id,
            workspace_id=workspace_id,
            chapter_id=chapter_id,
            stack_id=stack_id,
            constraints=constraints,
            parent_run_id=parent_run_id,
            prior_session_id=prior_session_id,
            continue_run=continue_run,
        )
    except Exception as exc:
        logger.warning("shadow run launch failed for %s: %s", source_run_id, exc)
        return ""


@dataclass
class StartRunResult:
    run_id: str
    session_id: str
    status: str
    engine: str
    company_id: str
    workspace_id: str
    chapter_id: str
    workflow_id: str = ""
    temporal_task_queue: str = ""
    feature_assignment: dict[str, Any] | None = None

    def to_response(self) -> dict[str, Any]:
        body = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "engine": self.engine,
            "company_id": self.company_id,
            "workspace_id": self.workspace_id,
            "chapter_id": self.chapter_id,
        }
        if self.workflow_id:
            body["workflow_id"] = self.workflow_id
        if self.temporal_task_queue:
            body["task_queue"] = self.temporal_task_queue
        if self.feature_assignment:
            body["feature_assignment"] = self.feature_assignment
        return body


def _run_created_payload(
    *,
    run_id: str,
    founder_id: str,
    company_id: str,
    workspace_id: str,
    chapter_id: str,
    engine: str,
    feature_assignment: dict[str, Any],
    prior_session_id: str | None = None,
    continue_run: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "session_id": run_id,
        "founder_id": founder_id,
        "company_id": company_id,
        "workspace_id": workspace_id,
        "chapter_id": chapter_id,
        "engine": engine,
        "feature_assignment": feature_assignment,
    }
    if prior_session_id:
        payload["prior_session_id"] = prior_session_id
    if continue_run:
        payload["continue_run"] = True
    return payload


def _initial_run_reservation_usd(body: RunCreateRequest) -> float:
    ceiling = float(body.budget_limit_usd or 0.0)
    if ceiling > 0:
        return max(0.01, min(_INITIAL_RUN_RESERVATION_USD, ceiling))
    return _INITIAL_RUN_RESERVATION_USD


async def _reserve_initial_budget(run_id: str, founder_id: str, body: RunCreateRequest) -> str | None:
    try:
        reservation = await asyncio.to_thread(
            get_default_budget_service().reserve,
            run_id=run_id,
            founder_id=founder_id,
            estimated_max_usd=_initial_run_reservation_usd(body),
            ttl_seconds=900,
        )
        return reservation.id
    except BudgetExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("initial budget reservation failed for run=%s: %s", run_id, exc)
        return None


async def _update_run_fields(run_id: str, patch: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(SupabaseRunRepository().update_fields, run_id, patch)
    except Exception as exc:
        logger.warning("astra_runs update failed for %s: %s", run_id, exc)


async def _mark_run_running(run_id: str, *, engine: str, metadata: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "status": "running",
        "engine": engine,
        "metadata": metadata,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "error": None,
    }
    await _update_run_fields(run_id, payload)


async def _mark_run_dispatch_failed(run_id: str, *, error: str, metadata: dict[str, Any]) -> None:
    await _update_run_fields(
        run_id,
        {
            "status": "queued",
            "error": error,
            "metadata": dict(metadata, dispatch_error=error),
        },
    )


async def register_background_run(
    *,
    founder_id: str,
    instruction: str,
    request: Request | None = None,
    run_id: str | None = None,
    company_id: str | None = None,
    workspace_id: str | None = None,
    chapter_id: str | None = None,
    stack_id: str | None = None,
    constraints: dict[str, Any] | None = None,
    parent_run_id: str | None = None,
    kind: str = "user",
) -> StartRunResult:
    actor_id = (
        require_founder_access(request, founder_id, min_role="operator")
        if request is not None
        else founder_id
    )
    ok, reason = screen_goal(instruction)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    resolved_run_id = run_id or new_session_id()
    resolved_workspace_id = str(workspace_id or company_id or founder_id)
    resolved_company_id = str(company_id or resolved_workspace_id or founder_id)
    resolved_chapter_id = str(chapter_id or "")
    normalized_constraints = dict(constraints or {})

    try:
        from backend.accounts import get_or_create_org, record_usage

        org = get_or_create_org(founder_id)
        if org.get("entitlements", {}).get("remaining_runs", 0) <= 0:
            raise HTTPException(status_code=402, detail="Monthly run limit reached for this workspace.")
        record_usage(org["org_id"], actor_id=actor_id, runs=1)
    except HTTPException:
        raise
    except Exception as usage_exc:
        logger.warning("Usage accounting skipped: %s", usage_exc)

    from backend.accounts import get_or_create_org as _get_org

    org = _get_org(founder_id)
    plan = (org or {}).get("plan", "starter")
    unlimited = plan in ("scale", "beta")
    if not unlimited and get_balance(founder_id) < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Purchase more to continue.")

    try:
        from backend.core.session_store import register_session, merge_session_meta

        register_session(
            session_id=resolved_run_id,
            founder_id=founder_id,
            goal=instruction,
            stack_id=str(stack_id or ""),
            company_name="",
            agents=list(normalized_constraints.get("agents", [])),
            workspace_id=resolved_workspace_id,
            company_id=resolved_company_id,
            chapter_id=resolved_chapter_id,
            parent_session_id=parent_run_id or "",
            kind=kind,
        )
        merge_session_meta(
            resolved_run_id,
            constraints=normalized_constraints,
            engine="legacy",
        )
    except Exception as session_exc:
        logger.warning("background run session registration failed: %s", session_exc)

    try:
        from backend.core.events import _get_queue as _pre_queue

        _pre_queue(resolved_run_id)
    except Exception:
        pass

    feature_assignment = assign_run_features(
        resolved_company_id,
        resolved_run_id,
        founder_id=founder_id,
        plan=plan,
    )
    engine = str(feature_assignment.get("engine") or "legacy")
    run = Run(
        id=resolved_run_id,
        owner_id=founder_id,
        org_id=resolved_company_id,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id or None,
        chapter_id=resolved_chapter_id or None,
        parent_run_id=parent_run_id,
        goal=instruction,
        stack_id=stack_id or None,
        engine=engine,
        metadata={"feature_assignment": feature_assignment, "background_run": True},
    )
    initial_reservation_id = await _reserve_initial_budget(
        resolved_run_id,
        founder_id,
        RunCreateRequest(founder_id=founder_id, instruction=instruction, constraints=normalized_constraints),
    )
    if initial_reservation_id:
        run.metadata["initial_budget_reservation_id"] = initial_reservation_id

    await durable_create_run_with_event(
        run,
        payload=_run_created_payload(
            run_id=resolved_run_id,
            founder_id=founder_id,
            company_id=resolved_company_id,
            workspace_id=resolved_workspace_id,
            chapter_id=resolved_chapter_id,
            engine=engine,
            feature_assignment=feature_assignment,
        ),
    )
    await _mark_run_running(resolved_run_id, engine=engine, metadata=run.metadata)
    try:
        from backend.core.session_store import merge_session_meta as _merge_meta

        _merge_meta(
            resolved_run_id,
            feature_assignment=feature_assignment,
            engine=engine,
        )
    except Exception as merge_exc:
        logger.warning("background run feature persistence failed: %s", merge_exc)
    shadow_run_id = await _maybe_start_shadow_run(
        founder_id=founder_id,
        instruction=instruction,
        source_run_id=resolved_run_id,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id,
        chapter_id=resolved_chapter_id,
        stack_id=stack_id,
        constraints=normalized_constraints,
        engine=engine,
        feature_assignment=feature_assignment,
        parent_run_id=parent_run_id,
    )
    if shadow_run_id:
        run.metadata["shadow_run_id"] = shadow_run_id
        await _update_run_fields(resolved_run_id, {"metadata": run.metadata})

    return StartRunResult(
        run_id=resolved_run_id,
        session_id=resolved_run_id,
        status="running",
        engine=engine,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id,
        chapter_id=resolved_chapter_id,
        feature_assignment=feature_assignment,
    )


async def start_continue_run(
    *,
    founder_id: str,
    instruction: str,
    prior_session_id: str,
    request: Request | None = None,
    run_id: str | None = None,
    agents: list[str] | None = None,
    exclude_agents: list[str] | None = None,
    research_depth: str | None = None,
    company_id: str | None = None,
    kind: str = "user",
    schedule_task: bool = True,
    validate_prior: bool = True,
) -> StartRunResult:
    if request is not None:
        require_founder_access(request, founder_id, min_role="operator")

    from backend.core.session_store import get_session_meta, merge_session_meta, register_session

    prior_meta = await asyncio.to_thread(get_session_meta, prior_session_id)
    prior_owner = str((prior_meta or {}).get("founder_id") or "")
    if not prior_owner and validate_prior:
        raise HTTPException(status_code=404, detail="prior session not found")
    if prior_owner and prior_owner != founder_id and validate_prior:
        raise HTTPException(status_code=403, detail="prior session does not belong to founder")

    resolved_run_id = run_id or new_session_id()
    resolved_company_id = str(company_id or (prior_meta or {}).get("company_id") or founder_id)
    resolved_workspace_id = str((prior_meta or {}).get("workspace_id") or "")
    resolved_chapter_id = str((prior_meta or {}).get("chapter_id") or "")

    from backend.accounts import get_or_create_org as _get_org_for_continue

    continue_org = _get_org_for_continue(founder_id)
    continue_plan = str((continue_org or {}).get("plan") or "starter")
    # Missing here until this fix -- unlike the initial start_run (which sets
    # constraints["unlimited_credits"]), continuation runs always defaulted to
    # False regardless of the founder's actual plan, so scale/beta founders lost
    # their reservation bypass on every continued run.
    continue_unlimited = continue_plan in ("scale", "beta")

    try:
        register_session(
            session_id=resolved_run_id,
            founder_id=founder_id,
            goal=instruction,
            stack_id=str((prior_meta or {}).get("stack_id") or ""),
            company_name=str((prior_meta or {}).get("company_name") or ""),
            agents=list(agents or []),
            workspace_id=resolved_workspace_id,
            company_id=resolved_company_id,
            chapter_id=resolved_chapter_id,
            parent_session_id=prior_session_id,
            kind=kind,
        )
        merge_session_meta(
            resolved_run_id,
            prior_session_id=prior_session_id,
            engine="legacy",
            continue_run=True,
            constraints={
                "agents": list(agents or []),
                "exclude_agents": list(exclude_agents or []),
                "research_depth": research_depth,
                "unlimited_credits": continue_unlimited,
            },
        )
    except Exception as session_exc:
        logger.warning("continuation session registration failed: %s", session_exc)

    try:
        from backend.core.events import _get_queue as _pre_queue

        _pre_queue(resolved_run_id)
    except Exception:
        pass
    feature_assignment = assign_run_features(
        resolved_company_id,
        resolved_run_id,
        founder_id=founder_id,
        plan=continue_plan,
    )
    engine = str(feature_assignment.get("engine") or "legacy")
    durable_parent_run_id = prior_session_id
    if not validate_prior:
        try:
            from backend.control_plane.supabase_repositories import SupabaseRunRepository

            durable_parent_run_id = prior_session_id if SupabaseRunRepository().get(prior_session_id) is not None else None
        except Exception:
            durable_parent_run_id = None

    run = Run(
        id=resolved_run_id,
        owner_id=founder_id,
        org_id=resolved_company_id,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id or None,
        chapter_id=resolved_chapter_id or None,
        parent_run_id=durable_parent_run_id,
        goal=instruction,
        stack_id=str((prior_meta or {}).get("stack_id") or "") or None,
        engine=engine,
        metadata={
            "feature_assignment": feature_assignment,
            "prior_session_id": prior_session_id,
            "continue_run": True,
            "agents": list(agents or []),
            "exclude_agents": list(exclude_agents or []),
            "research_depth": research_depth,
        },
    )
    try:
        merge_session_meta(resolved_run_id, feature_assignment=feature_assignment, engine=engine)
    except Exception as feature_exc:
        logger.warning("continuation feature persistence failed: %s", feature_exc)
    shadow_run_id = ""

    async def _bootstrap_continuation_run() -> None:
        nonlocal shadow_run_id
        if getattr(_bootstrap_continuation_run, "_done", False):
            return
        await durable_create_run_with_event(
            run,
            payload=_run_created_payload(
                run_id=resolved_run_id,
                founder_id=founder_id,
                company_id=resolved_company_id,
                workspace_id=resolved_workspace_id,
                chapter_id=resolved_chapter_id,
                engine=engine,
                feature_assignment=feature_assignment,
                prior_session_id=prior_session_id,
                continue_run=True,
            ),
        )
        await _mark_run_running(resolved_run_id, engine=engine, metadata=run.metadata)
        shadow_run_id = await _maybe_start_shadow_run(
            founder_id=founder_id,
            instruction=instruction,
            source_run_id=resolved_run_id,
            company_id=resolved_company_id,
            workspace_id=resolved_workspace_id,
            chapter_id=resolved_chapter_id,
            stack_id=run.stack_id,
            constraints={
                "agents": list(agents or []),
                "exclude_agents": list(exclude_agents or []),
                "research_depth": research_depth,
            },
            engine=engine,
            feature_assignment=feature_assignment,
            parent_run_id=durable_parent_run_id,
            prior_session_id=prior_session_id,
            continue_run=True,
        )
        if shadow_run_id:
            run.metadata["shadow_run_id"] = shadow_run_id
            await _update_run_fields(resolved_run_id, {"metadata": run.metadata})
        setattr(_bootstrap_continuation_run, "_done", True)

    async def _run() -> None:
        from backend.core import cancellation
        from backend.core.factory import get_orchestrator

        orch = get_orchestrator()
        final_status = "done"
        bootstrap_task: asyncio.Task[Any] | None = None
        try:
            if schedule_task:
                bootstrap_task = asyncio.create_task(_bootstrap_continuation_run())
            else:
                await _bootstrap_continuation_run()
            continue_kwargs: dict[str, Any] = {
                "instruction": instruction,
                "founder_id": founder_id,
                "prior_session_id": prior_session_id,
                "agents": agents,
                "session_id": resolved_run_id,
            }
            if exclude_agents:
                continue_kwargs["exclude_agents"] = exclude_agents
            if research_depth:
                continue_kwargs["research_depth"] = research_depth
            _continue_result = await orch.continue_run(**continue_kwargs)
            # Same fix as the fresh-run path below: continue_run() never raises
            # for an incomplete run, it just publishes goal_error internally.
            if isinstance(_continue_result, dict) and _continue_result.get("ok") is False:
                final_status = "error"
        except asyncio.CancelledError:
            final_status = "killed"
            try:
                from backend.core.events import publish
                from backend.core.session_store import update_session_status

                update_session_status(resolved_run_id, "killed")
                await publish(resolved_run_id, {"type": "goal_error", "error": "Run stopped by user.", "killed": True})
            except Exception:
                pass
        except Exception as exc:
            final_status = "error"
            try:
                from backend.core.events import publish
                await publish(resolved_run_id, {"type": "goal_error", "error": str(exc)})
            except Exception:
                pass
        finally:
            if bootstrap_task is not None:
                try:
                    await bootstrap_task
                except Exception:
                    pass
            cancellation.clear(resolved_run_id)
            try:
                from backend.db.client import get_supabase
                durable_status = {
                    "done": "succeeded",
                    "error": "failed",
                    "killed": "cancelled",
                }.get(final_status, "failed")
                payload: dict[str, Any] = {"status": durable_status}
                if durable_status in {"succeeded", "failed", "cancelled"}:
                    payload["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                get_supabase().table("astra_runs").update(payload).eq("id", resolved_run_id).execute()
            except Exception as run_update_exc:
                logger.warning("final continuation astra_runs update failed for %s: %s", resolved_run_id, run_update_exc)
            if shadow_run_id:
                try:
                    from backend.control_plane.temporal.shadow_runtime import maybe_compare_shadow_run

                    await asyncio.to_thread(maybe_compare_shadow_run, resolved_run_id, shadow_run_id)
                except Exception as shadow_exc:
                    logger.warning("continuation shadow comparison trigger failed for %s: %s", resolved_run_id, shadow_exc)

    from backend.core import cancellation
    if schedule_task:
        task = asyncio.create_task(_run())
        cancellation.register_task(resolved_run_id, task)
    else:
        await _bootstrap_continuation_run()
        current_task = asyncio.current_task()
        if current_task is not None:
            cancellation.register_task(resolved_run_id, current_task)
        await _run()
    return StartRunResult(
        run_id=resolved_run_id,
        session_id=resolved_run_id,
        status="running",
        engine=engine,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id,
        chapter_id=resolved_chapter_id,
        feature_assignment=feature_assignment,
    )


def _run_option_exclusions(technical_scope: str | None, marketing_channels: str | None) -> list[str]:
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


async def _reconcile_orphaned_agents(session_id: str, reason: str) -> None:
    try:
        from backend.core.session_store import load_events
        from backend.workflow_state import build_session_state

        events = await asyncio.to_thread(load_events, session_id) or []
        state = build_session_state(session_id, events)
        from backend.core.events import publish
        for name, ag in (state.get("agents") or {}).items():
            if (ag or {}).get("status") in ("running", "waiting"):
                await publish(
                    session_id,
                    {
                        "type": "agent_error",
                        "agent": name,
                        "task_id": (ag or {}).get("task_id") or "",
                        "error": reason,
                    },
                )
    except Exception:
        pass


def _analyze_goal(instruction: str) -> tuple[str | None, str | None]:
    try:
        import json as _json
        from backend.tools._llm import generate

        prompt = (
            "Analyze this startup/business goal and return JSON with:\n"
            "1. stack_id: 'ecomm', 'local_service', or null (for saas/default)\n"
            "2. business_profile: 2-3 sentence summary including company type, customer, offering, pricing/business model if stated, and core problem solved.\n\n"
            f"Goal: {instruction}\n\n"
            'Return ONLY JSON: {"stack_id": null, "business_profile": "..."}'
        )
        raw = generate(
            prompt,
            model="google/gemini-2.5-flash-lite",
            provider="openrouter",
            max_tokens=200,
            temperature=0.1,
            require_json=True,
        )
        data = _json.loads(raw)
        return data.get("stack_id"), data.get("business_profile")
    except Exception:
        return None, None


async def start_run(
    body: RunCreateRequest,
    request: Request | None,
    *,
    run_id: str | None = None,
) -> StartRunResult:
    actor_id = (
        require_founder_access(request, body.founder_id, min_role="operator")
        if request is not None
        else body.founder_id
    )
    ok, reason = screen_goal(body.instruction)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    resolved_run_id = run_id or new_session_id()
    with run_span(resolved_run_id, body.founder_id, body.founder_id) as _run_span:
        orch = get_orchestrator()

        try:
            from backend.accounts import RunLimitExceeded, check_and_consume_run

            # check_and_consume_run() performs the remaining_runs check and the
            # usage.recorded write atomically under one lock acquisition, so two
            # concurrent start_run() calls for a founder with exactly 1 remaining
            # run cannot both pass the check before either has consumed it (see
            # backend/accounts.py for details).
            check_and_consume_run(body.founder_id, actor_id=actor_id)
        except RunLimitExceeded as limit_exc:
            raise HTTPException(status_code=402, detail=str(limit_exc)) from limit_exc
        except HTTPException:
            raise
        except Exception as usage_exc:
            logger.warning("Usage accounting skipped: %s", usage_exc)

        from backend.accounts import get_or_create_org as _get_org

        org = _get_org(body.founder_id)
        plan = (org or {}).get("plan", "starter")
        unlimited = plan in ("scale", "beta")
        if not unlimited and get_balance(body.founder_id) < 1:
            raise HTTPException(status_code=402, detail="Insufficient credits. Purchase more to continue.")

        constraints = dict(body.constraints or {})
        inferred_stack, business_profile = _analyze_goal(body.instruction)
        effective_stack = body.stack_id or inferred_stack or ""
        if effective_stack:
            constraints["stack_id"] = effective_stack
        constraints["unlimited_credits"] = unlimited
        exclude_agents = _run_option_exclusions(body.technical_scope, body.marketing_channels)
        if exclude_agents:
            constraints["exclude_agents"] = exclude_agents
        if body.research_depth:
            constraints["research_depth"] = body.research_depth

        goal_instruction = body.instruction
        if business_profile and "---" not in body.instruction[:80]:
            goal_instruction = f"Business profile:\n{business_profile}\n\n---\n{body.instruction}"

        workspace_id = ""
        chapter_id = ""
        try:
            from backend.core import workspace_store as _wss

            ws_name = (body.workspace_name or "").strip() or body.instruction[:60]
            requested_company_id = body.company_id or body.workspace_id
            if requested_company_id:
                company = _wss.get_workspace(requested_company_id)
                if not company:
                    raise HTTPException(status_code=404, detail="Company not found")
                if request is not None:
                    require_founder_access(request, str(company.get("founder_id") or ""), min_role="operator")
                workspace_id = requested_company_id
            elif body.workspace_name:
                # find_or_create_workspace() serializes the find-then-create
                # sequence behind a per (founder_id, name) lock so two concurrent
                # requests with the same workspace_name can't both observe "no
                # existing workspace" and each create a duplicate (see
                # backend/core/workspace_store.py for details).
                ws = _wss.find_or_create_workspace(
                    body.founder_id,
                    body.workspace_name,
                    create_name=ws_name,
                    goal=goal_instruction,
                    stack_id=effective_stack or "idea_to_revenue",
                )
                workspace_id = ws["workspace_id"]
            else:
                ws = _wss.create_workspace(
                    founder_id=body.founder_id,
                    name=ws_name,
                    goal=goal_instruction,
                    stack_id=effective_stack or "idea_to_revenue",
                )
                workspace_id = ws["workspace_id"]
            chapter = _wss.create_chapter(workspace_id=workspace_id, session_id=resolved_run_id)
            chapter_id = chapter["chapter_id"]
            constraints["company_id"] = workspace_id
            constraints["workspace_id"] = workspace_id
        except HTTPException:
            raise
        except Exception as workspace_exc:
            logger.warning("workspace creation failed (non-fatal): %s", workspace_exc)
        _run_span.set_attribute("org.id", workspace_id or body.founder_id)

        try:
            from backend.core.session_store import merge_session_meta, register_session

            register_session(
                session_id=resolved_run_id,
                founder_id=body.founder_id,
                goal=goal_instruction,
                stack_id=effective_stack,
                company_name=str(constraints.get("company_name", "")),
                agents=list(constraints.get("agents", [])),
                workspace_id=workspace_id,
                company_id=workspace_id or body.founder_id,
                chapter_id=chapter_id,
                parent_session_id=body.parent_run_id or "",
                kind="user",
            )
            merge_session_meta(
                resolved_run_id,
                constraints=constraints,
                engine="legacy",
                budget_limit_usd=body.budget_limit_usd,
            )
        except Exception as session_exc:
            logger.warning("session_store.register_session failed: %s", session_exc)

        from backend.core.events import _get_queue as _pre_queue

        _pre_queue(resolved_run_id)

        feature_assignment = assign_run_features(
            workspace_id or body.founder_id,
            resolved_run_id,
            founder_id=body.founder_id,
            plan=plan,
        )
        engine = str(feature_assignment.get("engine") or "legacy")
        run = Run(
            id=resolved_run_id,
            owner_id=body.founder_id,
            org_id=workspace_id or body.founder_id,
            company_id=workspace_id or body.founder_id,
            workspace_id=workspace_id or None,
            chapter_id=chapter_id or None,
            parent_run_id=body.parent_run_id,
            goal=goal_instruction,
            stack_id=effective_stack or None,
            engine=engine,
            budget_limit_usd=body.budget_limit_usd,
            metadata={"feature_assignment": feature_assignment},
        )
        initial_reservation_id = await _reserve_initial_budget(resolved_run_id, body.founder_id, body)
        if initial_reservation_id:
            run.metadata["initial_budget_reservation_id"] = initial_reservation_id

        await durable_create_run_with_event(
            run,
            payload=_run_created_payload(
                run_id=resolved_run_id,
                founder_id=body.founder_id,
                company_id=workspace_id or body.founder_id,
                workspace_id=workspace_id,
                chapter_id=chapter_id,
                engine=engine,
                feature_assignment=feature_assignment,
            ),
        )

        try:
            from backend.core.session_store import merge_session_meta as _merge_features

            _merge_features(
                resolved_run_id,
                feature_assignment=feature_assignment,
                engine=engine,
            )
        except Exception as feature_exc:
            logger.warning("session_store.merge_session_meta (feature_assignment) failed: %s", feature_exc)

        if engine == "temporal":
            try:
                from backend.control_plane.temporal.dispatch import start_run as dispatch_temporal_run

                dispatch = await dispatch_temporal_run(
                    run_id=resolved_run_id,
                    founder_id=body.founder_id,
                    company_id=workspace_id or body.founder_id,
                    workspace_id=workspace_id or None,
                    chapter_id=chapter_id or None,
                )
                await _mark_run_running(
                    resolved_run_id,
                    engine="temporal",
                    metadata={"feature_assignment": feature_assignment, "initial_budget_reservation_id": initial_reservation_id},
                )
                try:
                    from backend.core.session_store import merge_session_meta as _merge_meta

                    _merge_meta(
                        resolved_run_id,
                        engine="temporal",
                        constraints=constraints,
                        workflow_id=dispatch.get("workflow_id", ""),
                        temporal_task_queue=dispatch.get("task_queue", ""),
                    )
                except Exception as merge_exc:
                    logger.warning("session_store.merge_session_meta failed: %s", merge_exc)
                return StartRunResult(
                    run_id=resolved_run_id,
                    session_id=resolved_run_id,
                    status="running",
                    engine="temporal",
                    company_id=workspace_id or body.founder_id,
                    workspace_id=workspace_id,
                    chapter_id=chapter_id,
                    workflow_id=str(dispatch.get("workflow_id") or ""),
                    temporal_task_queue=str(dispatch.get("task_queue") or ""),
                    feature_assignment=feature_assignment,
                )
            except Exception as temporal_exc:
                logger.warning("Temporal dispatch failed, falling back to legacy: %s", temporal_exc)
                engine = "legacy"
                feature_assignment = dict(feature_assignment, engine="legacy")
                try:
                    from backend.core.session_store import merge_session_meta as _merge_features

                    await _mark_run_dispatch_failed(
                        resolved_run_id,
                        error=str(temporal_exc),
                        metadata={"feature_assignment": feature_assignment, "initial_budget_reservation_id": initial_reservation_id},
                    )
                    _merge_features(resolved_run_id, feature_assignment=feature_assignment, engine="legacy")
                except Exception as merge_exc:
                    logger.warning("session_store.merge_session_meta (engine correction) failed: %s", merge_exc)

        shadow_run_id = ""

        async def _run() -> None:
            from backend.core import cancellation

            final_status = "done"
            try:
                _run_result = await orch.run(
                    goal=goal_instruction,
                    founder_id=body.founder_id,
                    constraints=constraints,
                    session_id=resolved_run_id,
                )
                # orch.run() never raises for an incomplete run -- failures are
                # handled internally via a goal_error event, not an exception --
                # so "no exception" alone is not "succeeded". Confirmed
                # production bug: a run where every non-research agent got
                # orphaned still wrote astra_runs.status=succeeded.
                if isinstance(_run_result, dict) and _run_result.get("ok") is False:
                    final_status = "error"
            except asyncio.CancelledError:
                final_status = "killed"
                logger.info("goal run killed session=%s", resolved_run_id)
                try:
                    from backend.core.session_store import update_session_status
                    from backend.core.events import publish

                    update_session_status(resolved_run_id, "killed")
                    await _reconcile_orphaned_agents(resolved_run_id, "Run stopped by user.")
                    await publish(resolved_run_id, {"type": "goal_error", "error": "Run stopped by user.", "killed": True})
                except Exception:
                    pass
            except Exception as exc:
                final_status = "error"
                logger.error("goal run error session=%s: %s", resolved_run_id, exc, exc_info=True)
                try:
                    from backend.core.events import publish

                    await _reconcile_orphaned_agents(resolved_run_id, "Run failed before this agent completed.")
                    await publish(resolved_run_id, {"type": "goal_error", "error": str(exc)})
                except Exception:
                    pass
            finally:
                cancellation.clear(resolved_run_id)
                try:
                    from backend.db.client import get_supabase

                    durable_status = {
                        "done": "succeeded",
                        "error": "failed",
                        "killed": "cancelled",
                    }.get(final_status, "failed")
                    payload: dict[str, Any] = {"status": durable_status}
                    if durable_status in {"succeeded", "failed", "cancelled"}:
                        payload["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    get_supabase().table("astra_runs").update(payload).eq("id", resolved_run_id).execute()
                except Exception as run_update_exc:
                    logger.warning("final astra_runs update failed for %s: %s", resolved_run_id, run_update_exc)
                if workspace_id and chapter_id:
                    try:
                        from backend.core import workspace_store as _wss2

                        _wss2.update_chapter(workspace_id, chapter_id, status=final_status)
                    except Exception as chapter_exc:
                        logger.warning("chapter status update failed: %s", chapter_exc)
                if shadow_run_id:
                    try:
                        from backend.control_plane.temporal.shadow_runtime import maybe_compare_shadow_run

                        await asyncio.to_thread(maybe_compare_shadow_run, resolved_run_id, shadow_run_id)
                    except Exception as shadow_exc:
                        logger.warning("shadow comparison trigger failed for %s: %s", resolved_run_id, shadow_exc)

        run_coro = _run()
        try:
            task = asyncio.create_task(run_coro)
        except Exception as exc:
            run_coro.close()
            await _mark_run_dispatch_failed(
                resolved_run_id,
                error=str(exc),
                metadata={"feature_assignment": feature_assignment, "initial_budget_reservation_id": initial_reservation_id},
            )
            return StartRunResult(
                run_id=resolved_run_id,
                session_id=resolved_run_id,
                status="queued",
                engine="legacy",
                company_id=workspace_id or body.founder_id,
                workspace_id=workspace_id,
                chapter_id=chapter_id,
                feature_assignment=feature_assignment,
            )
        from backend.core import cancellation

        cancellation.register_task(resolved_run_id, task)
        await _mark_run_running(
            resolved_run_id,
            engine="legacy",
            metadata={"feature_assignment": feature_assignment, "initial_budget_reservation_id": initial_reservation_id},
        )
        shadow_run_id = await _maybe_start_shadow_run(
            founder_id=body.founder_id,
            instruction=goal_instruction,
            source_run_id=resolved_run_id,
            company_id=workspace_id or body.founder_id,
            workspace_id=workspace_id,
            chapter_id=chapter_id,
            stack_id=effective_stack,
            constraints=constraints,
            engine="legacy",
            feature_assignment=feature_assignment,
            parent_run_id=body.parent_run_id,
        )
        if shadow_run_id:
            await _update_run_fields(
                resolved_run_id,
                {
                    "metadata": {
                        "feature_assignment": feature_assignment,
                        "initial_budget_reservation_id": initial_reservation_id,
                        "shadow_run_id": shadow_run_id,
                    }
                },
            )
            try:
                from backend.core.session_store import merge_session_meta as _merge_meta_shadow

                _merge_meta_shadow(resolved_run_id, shadow_run_id=shadow_run_id, shadow_comparison_status="pending")
            except Exception:
                pass
        return StartRunResult(
            run_id=resolved_run_id,
            session_id=resolved_run_id,
            status="running",
            engine="legacy",
            company_id=workspace_id or body.founder_id,
            workspace_id=workspace_id,
            chapter_id=chapter_id,
            feature_assignment=feature_assignment,
        )

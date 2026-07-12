from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from backend.api.schemas import RunCreateRequest
from backend.control_plane.models import Run
from backend.control_plane.rollout import assign_run_features
from backend.control_plane.supabase_repositories import durable_create_run
from backend.core.factory import get_orchestrator
from backend.core.session_ids import new_session_id
from backend.credits.store import get_balance
from backend.safety.content_filter import screen_goal
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)


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
) -> StartRunResult:
    if request is not None:
        require_founder_access(request, founder_id, min_role="operator")

    from backend.core.session_store import get_session_meta, merge_session_meta, register_session

    prior_meta = await asyncio.to_thread(get_session_meta, prior_session_id)
    prior_owner = str((prior_meta or {}).get("founder_id") or "")
    if not prior_owner:
        raise HTTPException(status_code=404, detail="prior session not found")
    if prior_owner != founder_id:
        raise HTTPException(status_code=403, detail="prior session does not belong to founder")

    resolved_run_id = run_id or new_session_id()
    resolved_company_id = str(company_id or (prior_meta or {}).get("company_id") or founder_id)
    resolved_workspace_id = str((prior_meta or {}).get("workspace_id") or "")
    resolved_chapter_id = str((prior_meta or {}).get("chapter_id") or "")

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
            },
        )
    except Exception as session_exc:
        logger.warning("continuation session registration failed: %s", session_exc)

    from backend.core.events import _get_queue as _pre_queue

    _pre_queue(resolved_run_id)

    feature_assignment = assign_run_features(resolved_company_id, resolved_run_id)
    engine = str(feature_assignment.get("engine") or "legacy")
    run = Run(
        id=resolved_run_id,
        owner_id=founder_id,
        org_id=resolved_company_id,
        company_id=resolved_company_id,
        workspace_id=resolved_workspace_id or None,
        chapter_id=resolved_chapter_id or None,
        parent_run_id=prior_session_id,
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
    await durable_create_run(run)
    try:
        from backend.db.client import get_supabase

        get_supabase().table("astra_runs").update({
            "status": "running",
            "engine": engine,
            "metadata": run.metadata,
        }).eq("id", resolved_run_id).execute()
    except Exception as update_exc:
        logger.warning("initial continuation astra_runs update failed for %s: %s", resolved_run_id, update_exc)

    try:
        from backend.control_plane.supabase_repositories import SupabaseRunEventRepository

        await asyncio.to_thread(
            SupabaseRunEventRepository().append,
            resolved_run_id,
            "run.created",
            {
                "run_id": resolved_run_id,
                "session_id": resolved_run_id,
                "founder_id": founder_id,
                "company_id": resolved_company_id,
                "workspace_id": resolved_workspace_id,
                "chapter_id": resolved_chapter_id,
                "engine": engine,
                "feature_assignment": feature_assignment,
                "prior_session_id": prior_session_id,
                "continue_run": True,
            },
        )
    except Exception as event_exc:
        logger.warning("continuation run.created append failed for %s: %s", resolved_run_id, event_exc)

    try:
        merge_session_meta(resolved_run_id, feature_assignment=feature_assignment, engine=engine)
    except Exception as feature_exc:
        logger.warning("continuation feature persistence failed: %s", feature_exc)

    orch = get_orchestrator()
    async def _run() -> None:
        from backend.core import cancellation
        final_status = "done"
        try:
            await orch.continue_run(
                instruction=instruction,
                founder_id=founder_id,
                prior_session_id=prior_session_id,
                agents=agents,
                session_id=resolved_run_id,
                exclude_agents=exclude_agents or None,
                research_depth=research_depth,
            )
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

    from backend.core import cancellation
    if schedule_task:
        task = asyncio.create_task(_run())
        cancellation.register_task(resolved_run_id, task)
    else:
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
        else:
            existing = None
            if body.workspace_name:
                from backend.core.workspace_store import find_workspace_by_name as _find_workspace_by_name

                existing = _find_workspace_by_name(body.founder_id, body.workspace_name)
            if existing:
                workspace_id = existing["workspace_id"]
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

    feature_assignment = assign_run_features(workspace_id or body.founder_id, resolved_run_id)
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
    await durable_create_run(run)
    try:
        from backend.db.client import get_supabase

        get_supabase().table("astra_runs").update({
            "status": "running",
            "engine": engine,
            "metadata": {"feature_assignment": feature_assignment},
        }).eq("id", resolved_run_id).execute()
    except Exception as update_exc:
        logger.warning("initial astra_runs update failed for %s: %s", resolved_run_id, update_exc)

    try:
        from backend.control_plane.supabase_repositories import SupabaseRunEventRepository

        await asyncio.to_thread(
            SupabaseRunEventRepository().append,
            resolved_run_id,
            "run.created",
            {
                "run_id": resolved_run_id,
                "session_id": resolved_run_id,
                "founder_id": body.founder_id,
                "company_id": workspace_id or body.founder_id,
                "workspace_id": workspace_id,
                "chapter_id": chapter_id,
                "engine": engine,
                "feature_assignment": feature_assignment,
            },
        )
    except Exception as event_exc:
        logger.warning("run.created append failed for %s: %s", resolved_run_id, event_exc)

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
                from backend.db.client import get_supabase
                from backend.core.session_store import merge_session_meta as _merge_features

                get_supabase().table("astra_runs").update({
                    "engine": "legacy",
                    "metadata": {"feature_assignment": feature_assignment},
                }).eq("id", resolved_run_id).execute()
                _merge_features(resolved_run_id, feature_assignment=feature_assignment, engine="legacy")
            except Exception as merge_exc:
                logger.warning("session_store.merge_session_meta (engine correction) failed: %s", merge_exc)

    async def _run() -> None:
        from backend.core import cancellation

        final_status = "done"
        try:
            await orch.run(
                goal=goal_instruction,
                founder_id=body.founder_id,
                constraints=constraints,
                session_id=resolved_run_id,
            )
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

    task = asyncio.create_task(_run())
    from backend.core import cancellation

    cancellation.register_task(resolved_run_id, task)
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

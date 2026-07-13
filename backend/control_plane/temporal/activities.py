"""Wave 2/4 control plane: Temporal activities for Astra runs."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from temporalio import activity
from temporalio.exceptions import ApplicationError

from backend.control_plane.temporal.execution import (
    build_multi_phase_run_input,
    build_temporal_run_plan,
    execute_deep_research,
    execute_lane_attempt,
    execute_orchestrator_run,
    execute_verification,
)

logger = logging.getLogger(__name__)


class ExecuteOrchestratorActivity:
    """Activity that runs the existing Astra orchestrator.

    This is the bridge between Temporal's durable execution and the legacy
    in-process orchestrator. The orchestrator runs inside the activity, which
    means Temporal can:
    - Track its progress via heartbeats
    - Cancel it via the activity cancellation scope
    - Retry it if it fails
    """

    @staticmethod
    @activity.defn(name="execute_orchestrator")
    async def execute(input: Any) -> dict[str, Any]:
        """Execute the orchestrator for a run."""
        try:
            return await execute_orchestrator_run(
                input,
                heartbeat=activity.heartbeat,
                observe_state_fn=lambda state: activity.heartbeat({"observed_state": state}),
            )
        except Exception as exc:
            run_id = getattr(input, "run_id", None)
            if run_id is None and isinstance(input, dict):
                run_id = input.get("run_id")
            activity.logger.error(
                "Orchestrator failed for run=%s: %s",
                run_id or "<unknown>",
                exc,
                exc_info=True,
            )
            raise


class ExecuteLaneAttemptActivity:
    """Activity that runs a single specialist lane attempt with durable step state."""

    @staticmethod
    @activity.defn(name="execute_lane_attempt")
    async def execute(input: Any) -> dict[str, Any]:
        try:
            return await execute_lane_attempt(
                input,
                heartbeat_fn=lambda details: activity.heartbeat(details),
                is_cancelled_fn=lambda: activity.is_cancelled() or activity.is_worker_shutdown(),
            )
        except Exception as exc:
            run_id = getattr(input, "run_id", None)
            step_key = getattr(input, "step_key", None)
            if isinstance(input, dict):
                run_id = run_id or input.get("run_id")
                step_key = step_key or input.get("step_key")
            activity.logger.error(
                "Lane attempt failed for run=%s step=%s: %s",
                run_id or "<unknown>",
                step_key or "<unknown>",
                exc,
                exc_info=True,
            )
            raise


class ExecuteDeepResearchActivity:
    """Wave 5.3: activity that runs one deep-research escalation as a
    bounded, cancellable unit (see DeepResearchWorkflow)."""

    @staticmethod
    @activity.defn(name="execute_deep_research")
    async def execute(input: Any) -> dict[str, Any]:
        try:
            return await execute_deep_research(input, heartbeat=lambda details: activity.heartbeat(details))
        except Exception as exc:
            run_id = getattr(input, "run_id", None)
            query_id = getattr(input, "query_id", None)
            if isinstance(input, dict):
                run_id = run_id or input.get("run_id")
                query_id = query_id or input.get("query_id")
            activity.logger.error(
                "Deep research failed for run=%s query=%s: %s",
                run_id or "<unknown>", query_id or "<unknown>", exc, exc_info=True,
            )
            raise


class ExecuteVerificationActivity:
    """Activity that runs artifact verification independently from lane execution."""

    @staticmethod
    @activity.defn(name="execute_verification")
    async def execute(input: Any) -> dict[str, Any]:
        try:
            return await execute_verification(input)
        except Exception as exc:
            run_id = getattr(input, "run_id", None)
            step_key = getattr(input, "step_key", None)
            if isinstance(input, dict):
                run_id = run_id or input.get("run_id")
                step_key = step_key or input.get("step_key")
            activity.logger.error(
                "Verification failed for run=%s step=%s: %s",
                run_id or "<unknown>",
                step_key or "<unknown>",
                exc,
                exc_info=True,
            )
            raise


class ExecuteMonitoringTickActivity:
    """Activity that runs one monitoring/auto-heal sweep."""

    @staticmethod
    @activity.defn(name="execute_monitoring_tick")
    async def execute() -> dict[str, int]:
        from backend.monitoring.scheduler import _tick

        checks, heals = await _tick()
        return {"checks": int(checks), "heals": int(heals)}


class ExecuteMissionSchedulerTickActivity:
    """Activity that runs one mission safety-net tick."""

    @staticmethod
    @activity.defn(name="execute_mission_scheduler_tick")
    async def execute() -> dict[str, int]:
        from backend.missions.scheduler import _scheduler_tick

        missions_run = await _scheduler_tick()
        return {"missions_run": int(missions_run)}


class ExecuteCompanyBrainTickActivity:
    """Activity that runs one Company Brain sync sweep."""

    @staticmethod
    @activity.defn(name="execute_company_brain_tick")
    async def execute() -> dict[str, int]:
        from backend.tools.company_brain import run_due_company_brain_syncs

        result = await asyncio.to_thread(run_due_company_brain_syncs)
        syncs = int((result or {}).get("syncs_run") or (result or {}).get("runs") or 0)
        return {"syncs_run": syncs}


class ExecuteCustomAgentsTickActivity:
    """Activity that runs one recurring custom-agents sweep."""

    @staticmethod
    @activity.defn(name="execute_custom_agents_tick")
    async def execute() -> dict[str, int]:
        from backend.custom_agents.scheduler import _tick

        launched = await _tick()
        return {"runs_launched": int(launched)}


class LoadRunPlanActivity:
    """Read run-local metadata and derive a Temporal phase plan."""

    @staticmethod
    @activity.defn(name="load_run_plan")
    async def load(run_id: str) -> dict[str, Any]:
        from backend.core.events import publish
        from backend.core.session_store import get_session_meta, merge_session_meta
        from backend.control_plane.temporal.execution import (
            TemporalPlanNonRetryableError,
            TemporalPlanRetryableError,
        )

        session_meta = get_session_meta(run_id) or {}
        try:
            plan_payload = await build_temporal_run_plan(run_id, session_meta)
        except TemporalPlanNonRetryableError as exc:
            raise ApplicationError(str(exc), type="TemporalPlanNonRetryableError", non_retryable=True) from exc
        except TemporalPlanRetryableError as exc:
            raise ApplicationError(str(exc), type="TemporalPlanRetryableError", non_retryable=False) from exc
        step_specs = dict(plan_payload.get("step_specs") or {})
        phase_order = list(plan_payload.get("phase_order") or [])
        merge_session_meta(
            run_id,
            temporal_step_specs=step_specs,
            temporal_phase_order=phase_order,
            temporal_phase_timeout_seconds=int((session_meta or {}).get("temporal_phase_timeout_seconds") or 7200),
        )
        if step_specs:
            await publish(
                run_id,
                {
                    "type": "plan_done",
                    "tasks": [
                        {
                            "id": str(spec.get("task_id") or step_key),
                            "agent": str(spec.get("agent") or step_key),
                            "instruction": str(spec.get("instruction") or ""),
                            "phase": str(spec.get("phase") or ""),
                            "depends_on": list(spec.get("depends_on") or []),
                        }
                        for step_key, spec in step_specs.items()
                    ],
                    "planner_model": "temporal_activity",
                },
                persist_durable=True,
            )
        return {
            "run_id": str(plan_payload.get("run_id") or run_id),
            "phases": list(plan_payload.get("phases") or []),
        }


class PublishEventActivity:
    """Legacy bridge that keeps current event surfaces fed best-effort."""

    @staticmethod
    @activity.defn(name="publish_run_event")
    async def publish(run_id: str, event_type: str, payload: dict) -> bool:
        """Publish an event for a run."""
        from backend.core.events import publish
        from backend.control_plane.supabase_repositories import SupabaseRunEventRepository

        activity.logger.info("Publishing event run=%s type=%s", run_id, event_type)

        try:
            event_repo = SupabaseRunEventRepository()
            sequence = event_repo.append(run_id, event_type, payload)
            await publish(run_id, {
                "type": event_type,
                "run_id": run_id,
                "sequence": sequence,
                **payload,
            }, persist_durable=False)
            return True
        except Exception as exc:
            activity.logger.warning(
                "Best-effort event bridge failed for run=%s type=%s: %s",
                run_id,
                event_type,
                exc,
            )
            return False


class ObserveRunActivity:
    """Canonical durable observation updates for Wave 3 shell state."""

    @staticmethod
    @activity.defn(name="observe_run")
    async def record(run_id: str, state: dict[str, Any]) -> bool:
        from backend.control_plane.supabase_repositories import SupabaseRunEventRepository, SupabaseRunRepository

        try:
            state = dict(state or {})
            workflow_status = str(state.get("workflow_status") or "running")
            payload = {
                "run_id": run_id,
                "workflow_status": workflow_status,
                "active_step": state.get("active_step"),
                "waiting_approval": state.get("waiting_approval"),
                "cancellation_requested": bool(state.get("cancellation_requested")),
                "shadow_mode": bool(state.get("shadow_mode")),
                "metadata": dict(state.get("metadata") or {}),
            }
            sequence = SupabaseRunEventRepository().append(run_id, "run.observed", payload)
            from backend.core.events import publish

            await publish(run_id, {
                "type": "run.observed",
                "run_id": run_id,
                "sequence": sequence,
                **payload,
            }, persist_durable=False)
            run_status = {
                "queued": "queued",
                "running": "running",
                "awaiting_approval": "awaiting_approval",
                "cancelling": "cancelling",
                "cancelled": "cancelled",
                "succeeded": "succeeded",
                "failed": "failed",
            }.get(workflow_status, "running")
            run_repo = SupabaseRunRepository()
            current_run = run_repo.get(run_id)
            metadata = dict((current_run.metadata if current_run else {}) or {})
            metadata["workflow_observed_state"] = payload
            run_repo.update_fields(run_id, {"status": run_status, "metadata": metadata})
            return True
        except Exception as exc:
            activity.logger.warning("Failed to record durable observation for run=%s: %s", run_id, exc)
            return False


class UpdateRunStatusActivity:
    """Legacy bridge that mirrors workflow status into session meta."""

    @staticmethod
    @activity.defn(name="update_run_status")
    async def update(run_id: str, status: str, error: Optional[str] = None) -> bool:
        """Update the status of a run.

        Args:
            run_id: The run identifier (also used as session_id in legacy)
            status: New status (running, succeeded, failed, cancelled)
            error: Optional error message for failed status

        Returns:
            True if update succeeded
        """
        from backend.core.session_store import update_session_status

        legacy_status = {
            "succeeded": "done",
            "failed": "error",
            "cancelled": "killed",
            "canceled": "killed",
        }.get(status, status)

        activity.logger.info("Updating run=%s status=%s (legacy=%s)", run_id, status, legacy_status)

        try:
            update_session_status(run_id, legacy_status)
            try:
                from backend.core.session_store import get_session_meta
                from backend.control_plane.temporal.shadow_runtime import maybe_compare_shadow_run

                meta = get_session_meta(run_id) or {}
                shadow_parent = str(meta.get("shadow_parent_run_id") or "")
                if shadow_parent:
                    maybe_compare_shadow_run(shadow_parent, run_id)
            except Exception as compare_exc:
                activity.logger.debug("Shadow compare trigger skipped for run=%s: %s", run_id, compare_exc)
            return True
        except Exception as exc:
            activity.logger.warning(
                "Failed to update run status run=%s status=%s: %s",
                run_id, legacy_status, exc,
            )
            return False


class CreatePhaseApprovalActivity:
    """Create and publish a durable phase-gate approval request."""

    @staticmethod
    @activity.defn(name="create_phase_approval")
    async def create(run_id: str, gate_key: str, phase_name: str, next_phase: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        from backend.approval_workflows import create_approval_request
        from backend.control_plane.action_executor import get_default_repo_bundle
        from backend.control_plane.models import ApprovalRequest
        from backend.core.events import publish

        request = create_approval_request(
            session_id=run_id,
            gate_key=gate_key,
            title=f"{phase_name.title()} Phase Complete",
            reason=f"Review deliverables before {next_phase} begins.",
            agent="temporal_phase_gate",
            metadata={
                "is_phase_gate": True,
                "phase": phase_name,
                "next_phase": next_phase,
                "artifacts": list(artifacts or []),
            },
        )
        durable_request = ApprovalRequest(
            id=str(request["id"]),
            run_id=run_id,
            gate_key=gate_key,
            action_digest=str(request["action_digest"]),
            required_role="owner",
            policy_version="v1",
            status="pending",
            expires_at=request.get("expires_at"),
            revision=int(request.get("revision") or 1),
        )
        try:
            get_default_repo_bundle().approval_repo.create(durable_request)
        except Exception as exc:
            activity.logger.warning("durable phase approval mirror failed run=%s gate=%s: %s", run_id, gate_key, exc)
        await publish(run_id, {"type": "approval_request", "request": request}, persist_durable=True)
        return request


class ExpireApprovalActivity:
    """Expire a durable approval request after a workflow timeout."""

    @staticmethod
    @activity.defn(name="expire_approval")
    async def expire(run_id: str, approval_id: str, action_digest: str, note: str = "") -> bool:
        from backend.control_plane.action_executor import get_default_repo_bundle
        from backend.core.events import approval_decision_push, publish

        try:
            updated = get_default_repo_bundle().approval_repo.decide(
                approval_id,
                "expired",
                decided_by="astra:timeout",
                note=note or "approval timed out",
            )
        except Exception as exc:
            activity.logger.warning("durable approval expiry failed run=%s approval=%s: %s", run_id, approval_id, exc)
            return False
        event = {
            "type": "stack_approval_decision",
            "gate_key": updated.gate_key,
            "request_id": approval_id,
            "approval_id": approval_id,
            "action_digest": action_digest,
            "decision": "expired",
            "note": note or "approval timed out",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        approval_decision_push(run_id, approval_id, action_digest, event)
        await publish(run_id, event, persist_durable=True)
        return True

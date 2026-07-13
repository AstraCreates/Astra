"""Wave 2/3 control plane: Temporal workflow for Astra runs.

Accepts an IDs-only run contract, dispatches to the existing orchestrator via
activities, supports cancellation via signals, and publishes events.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import (
    ApprovalDecisionInput,
    MultiPhaseRunInput,
    MultiPhaseRunResult,
    PhaseRunInput,
    RetryStepInput,
    RunInput,
    RunResult,
    WorkflowObservedState,
)

logger = logging.getLogger(__name__)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import (
        ExecuteOrchestratorActivity,
        LoadRunPlanActivity,
        ObserveRunActivity,
        PublishEventActivity,
        UpdateRunStatusActivity,
    )
    from backend.control_plane.temporal.multi_phase_workflow import MultiPhaseRunWorkflow
    from backend.observability.tracing import workflow_span


@workflow.defn(name="AstraRun")
class AstraRunWorkflow:
    """Durable workflow for executing an Astra run.

    Signals:
        - cancel: Request cancellation of the run
        - steer: Redirect the run with new instructions (future)

    Activities:
        - execute_orchestrator: Run the existing orchestrator
        - publish_event: Emit events to the event log
        - update_run_status: Update run status in the store
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._steer_instructions: Optional[str] = None
        self._approval_decision: Optional[dict[str, str | None]] = None
        self._retry_request: Optional[dict[str, str | None]] = None
        self._state = WorkflowObservedState(run_id="")

    @staticmethod
    def _log_workflow_id() -> str:
        try:
            return str(workflow.info().workflow_id)
        except Exception:
            return "<workflow-outside-runtime>"

    @staticmethod
    def _task_queue() -> str:
        try:
            return str(workflow.info().task_queue)
        except Exception:
            return "astra-runs-v1"

    @workflow.signal
    async def cancel(self) -> None:
        """Signal to cancel the run."""
        self._cancelled = True
        self._state.cancellation_requested = True
        self._state.workflow_status = "cancelling"
        logger.info("Workflow %s received cancel signal", self._log_workflow_id())

    @workflow.signal
    async def steer(self, instructions: str) -> None:
        """Signal to redirect the run with new instructions."""
        self._steer_instructions = instructions
        logger.info("Workflow %s received steer signal", self._log_workflow_id())

    @workflow.signal(name="approval_decision")
    async def approval_decision(self, decision: ApprovalDecisionInput) -> None:
        self._approval_decision = {
            "approval_id": decision.approval_id,
            "action_digest": decision.action_digest,
            "decision": decision.decision,
            "policy_version": decision.policy_version,
            "decided_by": decision.decided_by,
            "note": decision.note,
        }
        self._state.waiting_approval = None
        self._state.metadata["approval_decision"] = dict(self._approval_decision)

    @workflow.signal(name="retry_step")
    async def retry_step(self, retry: RetryStepInput) -> None:
        self._retry_request = {
            "step_key": retry.step_key,
            "requested_by": retry.requested_by,
            "note": retry.note,
        }
        self._state.metadata["retry_request"] = dict(self._retry_request)

    @workflow.query(name="workflow_status")
    def workflow_status(self) -> str:
        return self._state.workflow_status

    @workflow.query(name="active_step")
    def active_step(self) -> Optional[str]:
        return self._state.active_step

    @workflow.query(name="waiting_approval")
    def waiting_approval(self) -> Optional[dict]:
        return self._state.waiting_approval

    @workflow.query(name="cancellation_state")
    def cancellation_state(self) -> dict[str, bool]:
        return {"requested": self._state.cancellation_requested}

    async def _observe(
        self,
        run_id: str,
        *,
        workflow_status: str,
        active_step: Optional[str],
        waiting_approval: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self._state.run_id = run_id
        self._state.workflow_status = workflow_status
        self._state.active_step = active_step
        self._state.waiting_approval = waiting_approval
        self._state.sequence += 1
        self._state.last_event_type = "run.observed"
        if metadata:
            self._state.metadata.update(metadata)
        await workflow.execute_activity(
            ObserveRunActivity.record,
            args=[run_id, {
                "workflow_status": self._state.workflow_status,
                "active_step": self._state.active_step,
                "waiting_approval": self._state.waiting_approval,
                "cancellation_requested": self._state.cancellation_requested,
                "shadow_mode": self._state.shadow_mode,
                "metadata": dict(self._state.metadata),
            }],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    @workflow.run
    async def run(self, input: RunInput) -> RunResult:
        """Execute the run workflow."""
        run_id = input.run_id
        self._state.run_id = run_id
        with workflow_span(run_id, "temporal") as _workflow_span:

            # Publish start event (no goal text in Temporal history)
            await workflow.execute_activity(
                PublishEventActivity.publish,
                args=[run_id, "run_started", {}],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            # Update status to running
            await workflow.execute_activity(
                UpdateRunStatusActivity.update,
                args=[run_id, "running"],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            plan_payload = await workflow.execute_activity(
                LoadRunPlanActivity.load,
                args=[run_id],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if not isinstance(plan_payload, dict):
                plan_payload = {}
            phases_payload = list((plan_payload or {}).get("phases") or [])
            if phases_payload:
                await self._observe(run_id, workflow_status="running", active_step="phase_planner", metadata={"stage": "started", "execution_mode": "multi_phase"})
            else:
                await self._observe(run_id, workflow_status="running", active_step="legacy_orchestrator", metadata={"stage": "started", "execution_mode": "legacy_activity"})

            try:
                if phases_payload:
                    multi_phase_input = MultiPhaseRunInput(
                        run_id=run_id,
                        phases=[
                            PhaseRunInput(
                                run_id=str(phase.get("run_id") or run_id),
                                phase_name=str(phase.get("phase_name") or ""),
                                next_phase=str(phase.get("next_phase") or "complete"),
                                step_keys=list(phase.get("step_keys") or []),
                                step_dependencies={
                                    str(step_key): list(deps or [])
                                    for step_key, deps in dict(phase.get("step_dependencies") or {}).items()
                                },
                                timeout_seconds=int(phase.get("timeout_seconds") or 7200),
                            )
                            for phase in phases_payload
                        ],
                    )
                    child_handle = await workflow.start_child_workflow(
                        MultiPhaseRunWorkflow.run,
                        multi_phase_input,
                        id=f"top-level/{run_id}/multi-phase",
                        task_queue=self._task_queue(),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                    while not child_handle.done():
                        active_phase = None
                        waiting_gate = None
                        try:
                            active_phase = await child_handle.query("active_phase")
                        except Exception:
                            active_phase = None
                        try:
                            waiting_gate = await child_handle.query("waiting_gate")
                        except Exception:
                            waiting_gate = None

                        workflow_status = "awaiting_approval" if waiting_gate else ("cancelling" if self._cancelled else "running")
                        waiting_approval = None
                        if waiting_gate:
                            waiting_approval = {
                                "gate_key": f"phase_gate_{waiting_gate}",
                                "phase_name": waiting_gate,
                            }
                        await self._observe(
                            run_id,
                            workflow_status=workflow_status,
                            active_step=f"phase:{active_phase}" if active_phase else "multi_phase",
                            waiting_approval=waiting_approval,
                            metadata={"stage": "phase_execution", "active_phase": active_phase, "waiting_gate": waiting_gate},
                        )

                        if self._cancelled:
                            child_handle.cancel()
                            try:
                                await child_handle
                            except asyncio.CancelledError:
                                pass
                            except Exception as cancel_exc:
                                logger.info("run=%s multi-phase child exited during cancellation: %s", run_id, cancel_exc)
                            await workflow.execute_activity(
                                PublishEventActivity.publish,
                                args=[run_id, "run_cancelled", {"reason": "cancelled by user"}],
                                start_to_close_timeout=timedelta(seconds=10),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                            )
                            await workflow.execute_activity(
                                UpdateRunStatusActivity.update,
                                args=[run_id, "cancelled"],
                                start_to_close_timeout=timedelta(seconds=10),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                            )
                            await self._observe(run_id, workflow_status="cancelled", active_step=None, metadata={"stage": "cancelled"})
                            return RunResult(run_id=run_id, status="cancelled", session_id=run_id)

                        if self._approval_decision:
                            await child_handle.signal(
                                "approval_decision",
                                ApprovalDecisionInput(**self._approval_decision),
                            )
                            self._state.metadata["approval_decision"] = dict(self._approval_decision)
                            self._approval_decision = None

                        if self._retry_request:
                            self._state.metadata["retry_request"] = dict(self._retry_request)
                            self._retry_request = None

                        await asyncio.sleep(1)

                    child_result = await child_handle
                    if isinstance(child_result, MultiPhaseRunResult):
                        child_result_dict = child_result.__dict__
                    else:
                        child_result_dict = child_result.model_dump() if hasattr(child_result, "model_dump") else child_result.__dict__

                    final_status = str(child_result_dict.get("status") or "failed")
                    if final_status == "approved":
                        await workflow.execute_activity(
                            PublishEventActivity.publish,
                            args=[run_id, "run_completed", {"session_id": run_id}],
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                        await workflow.execute_activity(
                            UpdateRunStatusActivity.update,
                            args=[run_id, "succeeded"],
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                        await self._observe(run_id, workflow_status="succeeded", active_step=None, metadata={"stage": "completed", "completed_phases": child_result_dict.get("completed_phases", [])})
                        return RunResult(run_id=run_id, status="succeeded", session_id=run_id)

                    error_msg = str(child_result_dict.get("decision") or child_result_dict.get("status") or "phase execution blocked")
                    await workflow.execute_activity(
                        PublishEventActivity.publish,
                        args=[run_id, "run_failed", {"error": error_msg, "stopped_phase": child_result_dict.get("stopped_phase")}],
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    await workflow.execute_activity(
                        UpdateRunStatusActivity.update,
                        args=[run_id, "failed", error_msg],
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    await self._observe(
                        run_id,
                        workflow_status="failed",
                        active_step=None,
                        metadata={
                            "stage": "failed",
                            "error": error_msg,
                            "stopped_phase": child_result_dict.get("stopped_phase"),
                            "completed_phases": child_result_dict.get("completed_phases", []),
                        },
                    )
                    return RunResult(run_id=run_id, status="failed", error=error_msg, session_id=run_id)

                activity_handle = workflow.start_activity(
                    ExecuteOrchestratorActivity.execute,
                    input,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                while not activity_handle.done():
                    if self._cancelled:
                        await self._observe(run_id, workflow_status="cancelling", active_step="legacy_orchestrator", metadata={"stage": "cancel_requested"})
                        activity_handle.cancel()
                        try:
                            await activity_handle
                        except asyncio.CancelledError:
                            pass
                        except Exception as cancel_exc:
                            logger.info("run=%s activity exited during cancellation: %s", run_id, cancel_exc)

                        await workflow.execute_activity(
                            PublishEventActivity.publish,
                            args=[run_id, "run_cancelled", {"reason": "cancelled by user"}],
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                        await workflow.execute_activity(
                            UpdateRunStatusActivity.update,
                            args=[run_id, "cancelled"],
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                        await self._observe(run_id, workflow_status="cancelled", active_step=None, metadata={"stage": "cancelled"})
                        return RunResult(run_id=run_id, status="cancelled", session_id=run_id)

                    if self._approval_decision:
                        await self._observe(
                            run_id,
                            workflow_status="running",
                            active_step="legacy_orchestrator",
                            metadata={"approval_decision": dict(self._approval_decision)},
                        )
                        self._approval_decision = None

                    if self._retry_request:
                        await self._observe(
                            run_id,
                            workflow_status="running",
                            active_step="legacy_orchestrator",
                            metadata={"retry_request": dict(self._retry_request)},
                        )
                        self._retry_request = None

                    await asyncio.sleep(1)

                result = await activity_handle

                # Publish completion event
                await workflow.execute_activity(
                    PublishEventActivity.publish,
                    args=[run_id, "run_completed", {"session_id": result.get("session_id")}],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Update status to succeeded
                await workflow.execute_activity(
                    UpdateRunStatusActivity.update,
                    args=[run_id, "succeeded"],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._observe(run_id, workflow_status="succeeded", active_step=None, metadata={"stage": "completed"})

                return RunResult(
                    run_id=run_id,
                    status="succeeded",
                    session_id=result.get("session_id"),
                )

            except Exception as exc:
                error_msg = str(exc)[:500]

                # Publish error event
                await workflow.execute_activity(
                    PublishEventActivity.publish,
                    args=[run_id, "run_failed", {"error": error_msg}],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Update status to failed
                await workflow.execute_activity(
                    UpdateRunStatusActivity.update,
                    args=[run_id, "failed", error_msg],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._observe(run_id, workflow_status="failed", active_step=None, metadata={"stage": "failed", "error": error_msg})

                return RunResult(run_id=run_id, status="failed", error=error_msg)

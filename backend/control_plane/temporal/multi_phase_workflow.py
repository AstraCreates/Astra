"""Wave 4.1 Temporal parent workflow for multi-phase progression."""
from __future__ import annotations

import asyncio
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import (
    ApprovalDecisionInput,
    MultiPhaseRunInput,
    MultiPhaseRunResult,
    RetryStepInput,
)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.phase_workflow import PhaseRunWorkflow
    from backend.observability.tracing import phase_span


_CONTINUE_AS_NEW_PHASE_THRESHOLD = 3


@workflow.defn(name="AstraMultiPhaseRun")
class MultiPhaseRunWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._pending_decision: Optional[dict] = None
        self._active_phase: Optional[str] = None
        self._waiting_gate: Optional[str] = None
        self._pending_retry: Optional[dict] = None

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True

    @workflow.signal(name="approval_decision")
    async def approval_decision(self, decision: ApprovalDecisionInput) -> None:
        self._pending_decision = {
            "approval_id": decision.approval_id,
            "action_digest": decision.action_digest,
            "decision": decision.decision,
            "policy_version": decision.policy_version,
            "decided_by": decision.decided_by,
            "note": decision.note,
        }

    @workflow.signal(name="retry_step")
    async def retry_step(self, retry: RetryStepInput) -> None:
        self._pending_retry = {
            "step_key": retry.step_key,
            "requested_by": retry.requested_by,
            "note": retry.note,
        }

    @workflow.query(name="active_phase")
    def active_phase(self) -> Optional[str]:
        return self._active_phase

    @workflow.query(name="waiting_gate")
    def waiting_gate(self) -> Optional[str]:
        return self._waiting_gate

    @staticmethod
    def _task_queue() -> str:
        try:
            return str(workflow.info().task_queue)
        except Exception:
            return "astra-runs-v1"

    @workflow.run
    async def run(self, input: MultiPhaseRunInput) -> MultiPhaseRunResult:
        completed_phases: list[dict] = list(input.completed_phases_seed or [])
        phases = list(input.phases or [])
        for index, phase in enumerate(phases):
            if self._cancelled:
                return MultiPhaseRunResult(
                    run_id=input.run_id,
                    status="cancelled",
                    completed_phases=completed_phases,
                    stopped_phase=self._active_phase,
                    decision="cancelled",
                )
            with phase_span(input.run_id, phase.phase_name):
                self._active_phase = phase.phase_name
                handle = await workflow.start_child_workflow(
                    PhaseRunWorkflow.run,
                    phase,
                    id=f"multi-phase/{input.run_id}/{phase.phase_name}",
                    task_queue=self._task_queue(),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                while not handle.done():
                    if self._cancelled:
                        handle.cancel()
                        try:
                            await handle
                        except asyncio.CancelledError:
                            pass
                        return MultiPhaseRunResult(
                            run_id=input.run_id,
                            status="cancelled",
                            completed_phases=completed_phases,
                            stopped_phase=self._active_phase,
                            decision="cancelled",
                        )
                    if self._pending_decision:
                        await handle.signal(
                            "approval_decision",
                            ApprovalDecisionInput(**self._pending_decision),
                        )
                        self._pending_decision = None
                    if self._pending_retry:
                        await handle.signal(
                            "retry_step",
                            RetryStepInput(**self._pending_retry),
                        )
                        self._pending_retry = None
                    try:
                        self._waiting_gate = await handle.query("waiting_gate")
                    except Exception:
                        self._waiting_gate = None
                    await asyncio.sleep(1)
                phase_result = await handle
                if isinstance(phase_result, dict):
                    phase_result_dict = phase_result
                else:
                    phase_result_dict = phase_result.model_dump() if hasattr(phase_result, "model_dump") else phase_result.__dict__
                completed_phases.append(phase_result_dict)
                self._pending_decision = None
                self._waiting_gate = None
                if phase_result_dict.get("decision") != "approved":
                    return MultiPhaseRunResult(
                        run_id=input.run_id,
                        status="blocked",
                        completed_phases=completed_phases,
                        stopped_phase=phase.phase_name,
                        decision=str(phase_result_dict.get("decision") or "blocked"),
                    )
                remaining_phases = phases[index + 1 :]
                if remaining_phases and len(completed_phases) % _CONTINUE_AS_NEW_PHASE_THRESHOLD == 0:
                    workflow.continue_as_new(
                        MultiPhaseRunInput(
                            run_id=input.run_id,
                            phases=remaining_phases,
                            completed_phases_seed=completed_phases,
                        )
                    )
        self._active_phase = None
        self._waiting_gate = None
        return MultiPhaseRunResult(
            run_id=input.run_id,
            status="approved",
            completed_phases=completed_phases,
            decision="approved",
        )

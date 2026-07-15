"""Wave 4.1/4.2 bounded Temporal phase workflow.

Coordinates one phase worth of lane-attempt child workflows, then runs the
phase approval gate before allowing the next phase to proceed.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import (
    ApprovalDecisionInput,
    LaneAttemptInput,
    PhaseGateInput,
    PhaseGateResult,
    PhaseRunInput,
    PhaseRunResult,
)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.lane_attempt_workflow import LaneAttemptWorkflow
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow


@workflow.defn(name="AstraPhaseRun")
class PhaseRunWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._waiting_gate: Optional[str] = None
        self._latest_gate_request: Optional[dict] = None
        self._current_gate_approval: Optional[dict] = None

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True

    @workflow.signal(name="approval_decision")
    async def approval_decision(self, decision: ApprovalDecisionInput) -> None:
        self._latest_gate_request = {
            "approval_id": decision.approval_id,
            "action_digest": decision.action_digest,
            "decision": decision.decision,
            "policy_version": decision.policy_version,
            "decided_by": decision.decided_by,
            "note": decision.note,
        }

    @workflow.query(name="waiting_gate")
    def waiting_gate(self) -> Optional[str]:
        return self._waiting_gate

    @workflow.query(name="waiting_approval")
    def waiting_approval(self) -> Optional[dict]:
        return dict(self._current_gate_approval or {}) if self._current_gate_approval else None

    @staticmethod
    def _task_queue() -> str:
        try:
            return str(workflow.info().task_queue)
        except Exception:
            return "astra-runs-v1"

    @workflow.run
    async def run(self, input: PhaseRunInput) -> PhaseRunResult:
        lane_results: list[dict] = []
        pending = list(input.step_keys or [])
        completed_step_keys: set[str] = set()
        step_dependencies = {
            str(step_key): [str(dep) for dep in list(deps or []) if str(dep)]
            for step_key, deps in dict(input.step_dependencies or {}).items()
        }

        while pending:
            if self._cancelled:
                return PhaseRunResult(
                    run_id=input.run_id,
                    phase_name=input.phase_name,
                    next_phase=input.next_phase,
                    status="cancelled",
                    decision="cancelled",
                    lane_results=lane_results,
                )

            ready = [
                step_key
                for step_key in pending
                if all(dep in completed_step_keys for dep in step_dependencies.get(step_key, []))
            ]
            if not ready:
                raise RuntimeError(
                    f"no runnable steps remain in phase={input.phase_name} run_id={input.run_id}; "
                    f"pending={pending!r} deps={step_dependencies!r}"
                )

            lane_handles = []
            for step_key in ready:
                lane_handles.append((
                    step_key,
                    await workflow.start_child_workflow(
                        LaneAttemptWorkflow.run,
                        LaneAttemptInput(run_id=input.run_id, step_key=step_key),
                        id=f"phase/{input.run_id}/{input.phase_name}/{step_key}",
                        task_queue=self._task_queue(),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    ),
                ))

            for lane_index, (step_key, handle) in enumerate(lane_handles):
                if self._cancelled:
                    remaining_handles = [h for _, h in lane_handles[lane_index:]]
                    for remaining_handle in remaining_handles:
                        remaining_handle.cancel()
                    for remaining_handle in remaining_handles:
                        try:
                            await remaining_handle
                        except asyncio.CancelledError:
                            pass
                    return PhaseRunResult(
                        run_id=input.run_id,
                        phase_name=input.phase_name,
                        next_phase=input.next_phase,
                        status="cancelled",
                        decision="cancelled",
                        lane_results=lane_results,
                    )
                result = await handle
                if isinstance(result, dict):
                    lane_results.append(result)
                else:
                    lane_results.append(result.model_dump() if hasattr(result, "model_dump") else result.__dict__)
                completed_step_keys.add(step_key)
                if step_key in pending:
                    pending.remove(step_key)

        gate_artifacts = []
        for result in lane_results:
            verification = dict(result.get("verification") or {})
            gate_artifacts.append({
                "key": result.get("step_key") or "",
                "title": result.get("agent") or result.get("step_key") or "",
                "agent": result.get("agent") or "",
                "status": verification.get("status") or result.get("status") or "passed",
                "preview": (verification.get("summary") or "")[:600],
            })

        self._waiting_gate = input.phase_name
        gate_handle = await workflow.start_child_workflow(
            PhaseGateWorkflow.run,
            PhaseGateInput(
                run_id=input.run_id,
                gate_key=f"phase_gate_{input.phase_name}",
                phase_name=input.phase_name,
                next_phase=input.next_phase,
                artifacts=gate_artifacts,
                timeout_seconds=input.timeout_seconds,
            ),
            id=f"phase-gate/{input.run_id}/{input.phase_name}",
            task_queue=self._task_queue(),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        while not gate_handle.done():
            if self._cancelled:
                gate_handle.cancel()
                try:
                    await gate_handle
                except asyncio.CancelledError:
                    pass
                return PhaseRunResult(
                    run_id=input.run_id,
                    phase_name=input.phase_name,
                    next_phase=input.next_phase,
                    status="cancelled",
                    decision="cancelled",
                    lane_results=lane_results,
                )
            try:
                self._current_gate_approval = await gate_handle.query("waiting_approval")
            except Exception:
                pass
            if self._latest_gate_request:
                await gate_handle.signal(
                    "approval_decision",
                    ApprovalDecisionInput(**self._latest_gate_request),
                )
            await asyncio.sleep(1)

        gate_result = await gate_handle
        self._waiting_gate = None
        self._latest_gate_request = None
        self._current_gate_approval = None
        if isinstance(gate_result, dict):
            gate_result_dict = gate_result
        else:
            gate_result_dict = gate_result.model_dump() if hasattr(gate_result, "model_dump") else gate_result.__dict__
        decision = str(gate_result_dict.get("decision") or "expired")
        return PhaseRunResult(
            run_id=input.run_id,
            phase_name=input.phase_name,
            next_phase=input.next_phase,
            status="approved" if decision == "approved" else "blocked",
            decision=decision,
            lane_results=lane_results,
            approval=gate_result_dict,
        )

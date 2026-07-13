"""Wave 4.1/4.4 Temporal child workflow for phase approval gates."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import (
    ApprovalDecisionInput,
    PhaseGateInput,
    PhaseGateResult,
)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import (
        CreatePhaseApprovalActivity,
        ExpireApprovalActivity,
    )


@workflow.defn(name="AstraPhaseGate")
class PhaseGateWorkflow:
    def __init__(self) -> None:
        self._request: Optional[dict] = None
        self._decision: Optional[ApprovalDecisionInput] = None

    @workflow.signal(name="approval_decision")
    async def approval_decision(self, decision: ApprovalDecisionInput) -> None:
        if self._request is None:
            return
        request_id = str(self._request.get("id") or self._request.get("approval_id") or "")
        request_digest = str(self._request.get("action_digest") or "")
        request_policy_version = str(self._request.get("policy_version") or "")
        decision_policy_version = str(decision.policy_version or "")
        if decision.approval_id != request_id or decision.action_digest != request_digest:
            return
        if request_policy_version and decision_policy_version and decision_policy_version != request_policy_version:
            return
        if self._decision is not None:
            current = {
                "approval_id": self._decision.approval_id,
                "action_digest": self._decision.action_digest,
                "decision": self._decision.decision,
                "policy_version": str(self._decision.policy_version or ""),
                "decided_by": self._decision.decided_by,
                "note": self._decision.note,
            }
            candidate = {
                "approval_id": decision.approval_id,
                "action_digest": decision.action_digest,
                "decision": decision.decision,
                "policy_version": decision_policy_version,
                "decided_by": decision.decided_by,
                "note": decision.note,
            }
            if candidate != current:
                return
        self._decision = decision

    @workflow.query(name="waiting_approval")
    def waiting_approval(self) -> Optional[dict]:
        return dict(self._request or {}) if self._request else None

    @workflow.run
    async def run(self, input: PhaseGateInput) -> PhaseGateResult:
        self._request = await workflow.execute_activity(
            CreatePhaseApprovalActivity.create,
            args=[input.run_id, input.gate_key, input.phase_name, input.next_phase, list(input.artifacts or [])],
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        timed_out = False
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(seconds=max(1, int(input.timeout_seconds or 7200))),
            )
        except TimeoutError:
            timed_out = True
        request_id = str(self._request.get("id") or self._request.get("approval_id") or "")
        action_digest = str(self._request.get("action_digest") or "")
        if timed_out or self._decision is None:
            await workflow.execute_activity(
                ExpireApprovalActivity.expire,
                args=[input.run_id, request_id, action_digest, ""],
                start_to_close_timeout=timedelta(seconds=20),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            return PhaseGateResult(
                run_id=input.run_id,
                gate_key=input.gate_key,
                approval_id=request_id,
                action_digest=action_digest,
                decision="expired",
                note="approval timed out",
            )

        return PhaseGateResult(
            run_id=input.run_id,
            gate_key=input.gate_key,
            approval_id=request_id,
            action_digest=action_digest,
            decision=self._decision.decision,
            note=self._decision.note,
        )

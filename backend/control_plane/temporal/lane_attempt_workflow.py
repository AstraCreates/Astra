"""Wave 4.2 Temporal child workflow for one bounded lane attempt."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import (
    LaneAttemptInput,
    LaneAttemptResult,
    VerificationInput,
    VerificationResult,
)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import (
        ExecuteLaneAttemptActivity,
        ExecuteVerificationActivity,
    )


@workflow.defn(name="AstraLaneAttempt")
class LaneAttemptWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._active_step: Optional[str] = None

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True

    @workflow.query(name="active_step")
    def active_step(self) -> Optional[str]:
        return self._active_step

    @workflow.run
    async def run(self, input: LaneAttemptInput) -> LaneAttemptResult:
        self._active_step = input.step_key
        activity_handle = workflow.start_activity(
            ExecuteLaneAttemptActivity.execute,
            input,
            start_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        while not activity_handle.done():
            if self._cancelled:
                activity_handle.cancel()
                try:
                    await activity_handle
                except asyncio.CancelledError:
                    pass
                return LaneAttemptResult(
                    run_id=input.run_id,
                    step_key=input.step_key,
                    step_id="",
                    agent="",
                    status="cancelled",
                    attempt_number=0,
                    error="cancelled",
                )
            await asyncio.sleep(1)
        result = await activity_handle
        lane_result = result if isinstance(result, LaneAttemptResult) else LaneAttemptResult(**dict(result or {}))
        try:
            verification = await workflow.execute_activity(
                ExecuteVerificationActivity.execute,
                VerificationInput(
                    run_id=input.run_id,
                    step_key=input.step_key,
                    attempt_number=lane_result.attempt_number,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            verification_result = verification if isinstance(verification, VerificationResult) else VerificationResult(**dict(verification or {}))
            lane_result.verification = dict(verification_result.verification or {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Verification is a review signal, not permission to tear down
            # unrelated lanes. Preserve the lane result and let the phase gate
            # surface it as needs_review with an actionable error.
            lane_result.verification = {
                "status": "needs_review",
                "summary": f"Verification unavailable: {str(exc)[:300]}",
                "recoverable": True,
            }
        return lane_result

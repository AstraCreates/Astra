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

from backend.control_plane.temporal.contracts import RunInput, RunResult

logger = logging.getLogger(__name__)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import (
        ExecuteOrchestratorActivity,
        PublishEventActivity,
        UpdateRunStatusActivity,
    )


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

    @workflow.signal
    async def cancel(self) -> None:
        """Signal to cancel the run."""
        self._cancelled = True
        logger.info("Workflow %s received cancel signal", workflow.info().workflow_id)

    @workflow.signal
    async def steer(self, instructions: str) -> None:
        """Signal to redirect the run with new instructions."""
        self._steer_instructions = instructions
        logger.info("Workflow %s received steer signal", workflow.info().workflow_id)

    @workflow.run
    async def run(self, input: RunInput) -> RunResult:
        """Execute the run workflow."""
        run_id = input.run_id

        # Publish start event (no goal text in Temporal history)
        await workflow.execute_activity(
            PublishEventActivity.publish,
            args=[run_id, "run_started", {"founder_id": input.founder_id}],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Update status to running
        await workflow.execute_activity(
            UpdateRunStatusActivity.update,
            args=[run_id, "running"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        try:
            activity_handle = workflow.start_activity(
                ExecuteOrchestratorActivity.execute,
                input,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=1),
            )

            while not activity_handle.done():
                if self._cancelled:
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
                    )
                    await workflow.execute_activity(
                        UpdateRunStatusActivity.update,
                        args=[run_id, "cancelled"],
                        start_to_close_timeout=timedelta(seconds=10),
                    )
                    return RunResult(run_id=run_id, status="cancelled", session_id=run_id)

                await asyncio.sleep(1)

            result = await activity_handle

            # Publish completion event
            await workflow.execute_activity(
                PublishEventActivity.publish,
                args=[run_id, "run_completed", {"session_id": result.get("session_id")}],
                start_to_close_timeout=timedelta(seconds=10),
            )

            # Update status to succeeded
            await workflow.execute_activity(
                UpdateRunStatusActivity.update,
                args=[run_id, "succeeded"],
                start_to_close_timeout=timedelta(seconds=10),
            )

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
            )

            # Update status to failed
            await workflow.execute_activity(
                UpdateRunStatusActivity.update,
                args=[run_id, "failed", error_msg],
                start_to_close_timeout=timedelta(seconds=10),
            )

            return RunResult(run_id=run_id, status="failed", error=error_msg)

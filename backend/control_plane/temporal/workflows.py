"""Wave 2/3 control plane: Temporal workflow for Astra runs.

Accepts a run_id and goal, dispatches to the existing orchestrator via
activities, supports cancellation via signals, and publishes events.

This is the real workflow that replaces the AstraPingWorkflow placeholder.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from temporalio import workflow

logger = logging.getLogger(__name__)

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import (
        ExecuteOrchestratorActivity,
        PublishEventActivity,
        UpdateRunStatusActivity,
    )


@dataclass
class RunInput:
    """Input to AstraRunWorkflow. Contains IDs only — no goals, vault text,
    or credentials per PLAN.md system invariant #5.

    The orchestrator fetches goal, constraints, and vault text from the
    session store using these IDs at execution time.
    """
    run_id: str
    founder_id: str
    company_id: str = ""
    workspace_id: str = ""
    chapter_id: str = ""


@dataclass
class RunResult:
    """Output from a completed workflow."""
    run_id: str
    status: str  # "succeeded" or "failed"
    error: Optional[str] = None
    session_id: Optional[str] = None


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
            start_to_close_timeout=workflow.timedelta.seconds(10),
        )

        # Update status to running
        await workflow.execute_activity(
            UpdateRunStatusActivity.update,
            args=[run_id, "running"],
            start_to_close_timeout=workflow.timedelta.seconds(10),
        )

        try:
            # Execute the orchestrator
            result = await workflow.execute_activity(
                ExecuteOrchestratorActivity.execute,
                args=[input],
                start_to_close_timeout=workflow.timedelta.hours(2),
                heartbeat_timeout=workflow.timedelta.minutes(5),
            )

            if self._cancelled:
                # Publish cancellation event
                await workflow.execute_activity(
                    PublishEventActivity.publish,
                    args=[run_id, "run_cancelled", {"reason": "cancelled during execution"}],
                    start_to_close_timeout=workflow.timedelta.seconds(10),
                )
                await workflow.execute_activity(
                    UpdateRunStatusActivity.update,
                    args=[run_id, "cancelled"],
                    start_to_close_timeout=workflow.timedelta.seconds(10),
                )
                return RunResult(run_id=run_id, status="cancelled")

            # Publish completion event
            await workflow.execute_activity(
                PublishEventActivity.publish,
                args=[run_id, "run_completed", {"session_id": result.get("session_id")}],
                start_to_close_timeout=workflow.timedelta.seconds(10),
            )

            # Update status to succeeded
            await workflow.execute_activity(
                UpdateRunStatusActivity.update,
                args=[run_id, "succeeded"],
                start_to_close_timeout=workflow.timedelta.seconds(10),
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
                start_to_close_timeout=workflow.timedelta.seconds(10),
            )

            # Update status to failed
            await workflow.execute_activity(
                UpdateRunStatusActivity.update,
                args=[run_id, "failed", error_msg],
                start_to_close_timeout=workflow.timedelta.seconds(10),
            )

            return RunResult(run_id=run_id, status="failed", error=error_msg)

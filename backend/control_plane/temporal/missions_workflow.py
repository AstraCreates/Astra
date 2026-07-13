"""Wave 4.5 Temporal workflow for scheduled mission safety-net ticks."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import ExecuteMissionSchedulerTickActivity


@workflow.defn(name="AstraMissionSchedulerTick")
class MissionSchedulerTickWorkflow:
    @workflow.run
    async def run(self) -> dict[str, int]:
        return await workflow.execute_activity(
            ExecuteMissionSchedulerTickActivity.execute,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

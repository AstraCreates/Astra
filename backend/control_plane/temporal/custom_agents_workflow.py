"""Wave 4.5 Temporal workflow for scheduled custom-agent ticks."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import ExecuteCustomAgentsTickActivity


@workflow.defn(name="AstraCustomAgentsTick")
class CustomAgentsTickWorkflow:
    @workflow.run
    async def run(self) -> dict[str, int]:
        return await workflow.execute_activity(
            ExecuteCustomAgentsTickActivity.execute,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

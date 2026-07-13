"""Wave 4.5 Temporal workflow for scheduled monitoring ticks."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import ExecuteMonitoringTickActivity


@workflow.defn(name="AstraMonitoringTick")
class MonitoringTickWorkflow:
    @workflow.run
    async def run(self) -> dict[str, int]:
        return await workflow.execute_activity(
            ExecuteMonitoringTickActivity.execute,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

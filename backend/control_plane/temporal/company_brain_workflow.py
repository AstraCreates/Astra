"""Wave 4.5 Temporal workflow for scheduled Company Brain sync ticks."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import ExecuteCompanyBrainTickActivity


@workflow.defn(name="AstraCompanyBrainTick")
class CompanyBrainTickWorkflow:
    @workflow.run
    async def run(self) -> dict[str, int]:
        return await workflow.execute_activity(
            ExecuteCompanyBrainTickActivity.execute,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

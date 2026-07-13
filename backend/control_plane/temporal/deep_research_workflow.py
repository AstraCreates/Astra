"""Wave 5.3 Temporal child workflow: one cancellable deep-research escalation.

Mirrors LaneAttemptWorkflow's shape exactly (see lane_attempt_workflow.py) --
a single bounded activity, a cancel signal, an active-query query, and
cooperative cancellation via activity_handle.cancel() rather than a hard
kill, so the underlying deep_research() call gets a real chance to observe
cancellation at its own checkpoints (per-model attempt, per-angle search)
instead of being torn down mid-request.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.control_plane.temporal.contracts import DeepResearchInput, DeepResearchResult

with workflow.unsafe.imports_passed_through():
    from backend.control_plane.temporal.activities import ExecuteDeepResearchActivity


@workflow.defn(name="AstraDeepResearch")
class DeepResearchWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._active_query: Optional[str] = None

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True

    @workflow.query(name="active_query")
    def active_query(self) -> Optional[str]:
        return self._active_query

    @workflow.run
    async def run(self, input: DeepResearchInput) -> DeepResearchResult:
        self._active_query = input.query_id
        activity_handle = workflow.start_activity(
            ExecuteDeepResearchActivity.execute,
            input,
            # Deep research legitimately runs multiple model attempts and
            # search rounds (see web_search.py's escalation chain) -- give it
            # real headroom rather than the 1hr lane-attempt ceiling times a
            # much shorter budget; heartbeat_timeout catches a truly stuck
            # attempt well before that.
            start_to_close_timeout=timedelta(minutes=20),
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
                return DeepResearchResult(run_id=input.run_id, query_id=input.query_id, status="cancelled")
            await asyncio.sleep(1)
        result = await activity_handle
        return result if isinstance(result, DeepResearchResult) else DeepResearchResult(**dict(result or {}))

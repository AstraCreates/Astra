"""Wave 2/3 control plane: Temporal activities for Astra runs."""
from __future__ import annotations

import logging
from typing import Any, Optional

from temporalio import activity

from backend.control_plane.temporal.execution import execute_orchestrator_run

logger = logging.getLogger(__name__)


class ExecuteOrchestratorActivity:
    """Activity that runs the existing Astra orchestrator.

    This is the bridge between Temporal's durable execution and the legacy
    in-process orchestrator. The orchestrator runs inside the activity, which
    means Temporal can:
    - Track its progress via heartbeats
    - Cancel it via the activity cancellation scope
    - Retry it if it fails
    """

    @staticmethod
    @activity.defn
    async def execute(input: Any) -> dict[str, Any]:
        """Execute the orchestrator for a run."""
        try:
            return await execute_orchestrator_run(input, heartbeat=activity.heartbeat)
        except Exception as exc:
            run_id = getattr(input, "run_id", None)
            if run_id is None and isinstance(input, dict):
                run_id = input.get("run_id")
            activity.logger.error(
                "Orchestrator failed for run=%s: %s",
                run_id or "<unknown>",
                exc,
                exc_info=True,
            )
            raise


class PublishEventActivity:
    """Legacy bridge that keeps current event surfaces fed best-effort."""

    @staticmethod
    @activity.defn
    async def publish(run_id: str, event_type: str, payload: dict) -> bool:
        """Publish an event for a run."""
        from backend.core.events import publish

        activity.logger.info("Publishing event run=%s type=%s", run_id, event_type)

        try:
            await publish(run_id, {
                "type": event_type,
                "run_id": run_id,
                **payload,
            })
            return True
        except Exception as exc:
            activity.logger.warning(
                "Best-effort event bridge failed for run=%s type=%s: %s",
                run_id,
                event_type,
                exc,
            )
            return False


class UpdateRunStatusActivity:
    """Legacy bridge that mirrors workflow status into session meta."""

    @staticmethod
    @activity.defn
    async def update(run_id: str, status: str, error: Optional[str] = None) -> bool:
        """Update the status of a run.

        Args:
            run_id: The run identifier (also used as session_id in legacy)
            status: New status (running, succeeded, failed, cancelled)
            error: Optional error message for failed status

        Returns:
            True if update succeeded
        """
        from backend.core.session_store import update_session_status

        legacy_status = {
            "succeeded": "done",
            "failed": "error",
            "cancelled": "killed",
            "canceled": "killed",
        }.get(status, status)

        activity.logger.info("Updating run=%s status=%s (legacy=%s)", run_id, status, legacy_status)

        try:
            update_session_status(run_id, legacy_status)
            return True
        except Exception as exc:
            activity.logger.warning(
                "Failed to update run status run=%s status=%s: %s",
                run_id, legacy_status, exc,
            )
            return False

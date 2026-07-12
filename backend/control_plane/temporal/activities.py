"""Wave 2/3 control plane: Temporal activities for Astra runs.

Activities are the side-effect boundary — they wrap the existing orchestrator
and event publishing in a way that Temporal can track, retry, and cancel.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Optional

from temporalio import activity

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
        """Execute the orchestrator for a run.

        Args:
            input: RunInput dataclass with run_id, founder_id, etc.
                   Goal is fetched from session store, NOT passed in.

        Returns:
            Dict with session_id, results, etc.
        """
        from backend.core.factory import get_orchestrator
        from backend.core.session_ids import new_session_id
        from backend.core.session_store import get_session_meta
        from backend.control_plane.temporal.workflows import RunInput

        # Convert to RunInput if needed
        if hasattr(input, 'run_id'):
            run_input = input
        else:
            run_input = RunInput(**input)

        run_id = run_input.run_id
        session_id = new_session_id()

        # Fetch goal from session store — goal text never enters Temporal history
        session_meta = get_session_meta(run_id) or {}
        goal = session_meta.get("goal", "")
        if not goal:
            raise ValueError(f"no goal found in session store for run_id={run_id}")

        activity.logger.info(
            "Executing orchestrator for run=%s session=%s goal=%.100s",
            run_id, session_id, run_input.goal,
        )

        # Heartbeat periodically so Temporal knows we're alive
        activity.heartbeat("starting orchestrator")

        try:
            orch = get_orchestrator()

            # Build constraints from input
            constraints = dict(run_input.constraints or {})
            if run_input.company_id:
                constraints["company_id"] = run_input.company_id
            if run_input.workspace_id:
                constraints["workspace_id"] = run_input.workspace_id
            if run_input.chapter_id:
                constraints["chapter_id"] = run_input.chapter_id

            # Run the orchestrator (goal fetched from store, not from workflow input)
            result = await orch.run(
                goal=goal,
                founder_id=run_input.founder_id,
                constraints=constraints,
                session_id=session_id,
            )

            activity.heartbeat("orchestrator completed")

            return {
                "session_id": session_id,
                "run_id": run_id,
                "status": "completed",
                "result": result if isinstance(result, dict) else {"output": str(result)[:1000]},
            }

        except asyncio.CancelledError:
            activity.logger.info("Orchestrator cancelled for run=%s", run_id)
            # Propagate cancellation to the orchestrator
            from backend.core import cancellation
            cancellation.request_kill(session_id)
            raise

        except Exception as exc:
            activity.logger.error(
                "Orchestrator failed for run=%s: %s", run_id, exc, exc_info=True,
            )
            raise


class PublishEventActivity:
    """Activity that publishes events to the event log.

    In Wave 2 this writes to the in-process event log and Redis.
    Later waves add Supabase persistence and Redis Streams.
    """

    @staticmethod
    @activity.defn
    async def publish(run_id: str, event_type: str, payload: dict) -> int:
        """Publish an event for a run.

        Args:
            run_id: The run identifier
            event_type: Type of event (e.g., "run_started", "run_completed")
            payload: Event payload data

        Returns:
            Sequence number of the published event
        """
        from backend.core.events import publish

        activity.logger.info("Publishing event run=%s type=%s", run_id, event_type)

        await publish(run_id, {
            "type": event_type,
            "run_id": run_id,
            **payload,
        })

        return 0  # Sequence number managed by the event system


class UpdateRunStatusActivity:
    """Activity that updates run status in the session store.

    This bridges to the existing session store for now. Later waves
    will use the canonical astra_runs table.
    """

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

        activity.logger.info("Updating run=%s status=%s", run_id, status)

        try:
            update_session_status(run_id, status)
            return True
        except Exception as exc:
            activity.logger.warning(
                "Failed to update run status run=%s status=%s: %s",
                run_id, status, exc,
            )
            return False

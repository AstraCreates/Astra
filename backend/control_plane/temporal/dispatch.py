"""Wave 2 control plane: Temporal dispatch for starting runs.

Provides start_run() which starts an AstraRunWorkflow on the Temporal server.
This is the bridge between the backend's goal submission endpoint and
Temporal's durable execution.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

import asyncio

from backend.control_plane.temporal.contracts import (
    ApprovalDecisionInput,
    RetryStepInput,
    TASK_QUEUE,
    RunInput,
    shadow_workflow_id_for_run,
    workflow_id_for_run,
)

# Lazy-initialized client with async lock to avoid import-time connection
_client = None
_client_lock = asyncio.Lock()


def reset_client_cache() -> None:
    """Drop the cached Temporal client.

    Used by recovery tests and by operator flows that need to force a reconnect
    after a server restart or network partition.
    """
    global _client
    _client = None


async def _get_client():
    """Get or create a Temporal client (thread-safe)."""
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        # Double-check after acquiring lock
        if _client is not None:
            return _client

        from temporalio.client import Client

        address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
        namespace = os.environ.get("TEMPORAL_NAMESPACE", "astra")

        _client = await Client.connect(address, namespace=namespace)
        logger.info("connected to Temporal at %s (namespace=%s)", address, namespace)
        return _client


async def start_run(
    *,
    run_id: str,
    founder_id: str,
    company_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    shadow: bool = False,
) -> dict[str, Any]:
    """Start an AstraRunWorkflow on the Temporal server.

    This is the entry point for dispatching runs through Temporal instead
    of the legacy asyncio task path.

    Args:
        run_id: The run identifier (becomes the workflow ID)
        founder_id: The founder who owns this run
        company_id: Optional company/workspace ID
        workspace_id: Optional workspace ID
        chapter_id: Optional chapter ID

    Returns:
        Dict with workflow_id, run_id, status
    """
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    client = await _get_client()

    workflow_input = RunInput(run_id=run_id)

    # Start the workflow
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)
    await client.start_workflow(
        AstraRunWorkflow.run,
        workflow_input,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    logger.info(
        "started Temporal workflow %s for run=%s founder=%s",
        workflow_id, run_id, founder_id,
    )

    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": "started",
        "task_queue": TASK_QUEUE,
    }


async def cancel_run(run_id: str, *, shadow: bool = False) -> bool:
    """Request cooperative cancellation for a running workflow.

    Args:
        run_id: The run identifier

    Returns:
        True if cancellation was requested
    """
    client = await _get_client()
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)

    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("cancel")
        logger.info("sent cancel signal to workflow %s", workflow_id)
        return True
    except Exception as exc:
        logger.warning("failed to cancel workflow %s: %s", workflow_id, exc)
        return False


async def get_workflow_status(run_id: str, *, shadow: bool = False) -> Optional[dict]:
    """Get the status of a workflow.

    Args:
        run_id: The run identifier

    Returns:
        Dict with workflow info or None if not found
    """
    client = await _get_client()
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)

    try:
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        return {
            "workflow_id": workflow_id,
            "status": desc.status.name,
            "run_id": run_id,
        }
    except Exception:
        return None


async def send_approval_decision(
    run_id: str,
    *,
    approval_id: str,
    action_digest: str,
    decision: str,
    policy_version: Optional[str] = None,
    decided_by: Optional[str] = None,
    note: Optional[str] = None,
    shadow: bool = False,
) -> bool:
    client = await _get_client()
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)
    try:
        handle = client.get_workflow_handle(workflow_id)
        try:
            waiting_approval = await handle.query("waiting_approval")
        except Exception:
            waiting_approval = None
        if isinstance(waiting_approval, dict) and waiting_approval:
            active_approval_id = str(waiting_approval.get("approval_id") or "").strip()
            active_action_digest = str(waiting_approval.get("action_digest") or "").strip()
            if active_approval_id and active_approval_id != approval_id:
                logger.warning(
                    "refusing approval decision for workflow %s: waiting approval_id=%s, got=%s",
                    workflow_id,
                    active_approval_id,
                    approval_id,
                )
                return False
            if active_action_digest and active_action_digest != action_digest:
                logger.warning(
                    "refusing approval decision for workflow %s: waiting action_digest=%s, got=%s",
                    workflow_id,
                    active_action_digest,
                    action_digest,
                )
                return False
        await handle.signal(
            "approval_decision",
            ApprovalDecisionInput(
                approval_id=approval_id,
                action_digest=action_digest,
                decision=decision,
                policy_version=policy_version,
                decided_by=decided_by,
                note=note,
            ),
        )
        return True
    except Exception as exc:
        logger.warning("failed to send approval decision to workflow %s: %s", workflow_id, exc)
        return False


async def retry_step(
    run_id: str,
    *,
    step_key: str,
    requested_by: Optional[str] = None,
    note: Optional[str] = None,
    shadow: bool = False,
) -> bool:
    client = await _get_client()
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(
            "retry_step",
            RetryStepInput(step_key=step_key, requested_by=requested_by, note=note),
        )
        return True
    except Exception as exc:
        logger.warning("failed to signal retry_step to workflow %s: %s", workflow_id, exc)
        return False


async def query_workflow_state(run_id: str, *, shadow: bool = False) -> Optional[dict[str, Any]]:
    client = await _get_client()
    workflow_id = shadow_workflow_id_for_run(run_id) if shadow else workflow_id_for_run(run_id)
    try:
        handle = client.get_workflow_handle(workflow_id)
        workflow_status = await handle.query("workflow_status")
        active_step = await handle.query("active_step")
        waiting_approval = await handle.query("waiting_approval")
        cancellation_state = await handle.query("cancellation_state")
        return {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "workflow_status": workflow_status,
            "active_step": active_step,
            "waiting_approval": waiting_approval,
            "cancellation_state": cancellation_state,
            "shadow": shadow,
        }
    except Exception as exc:
        logger.warning("failed to query workflow state %s: %s", workflow_id, exc)
        return None

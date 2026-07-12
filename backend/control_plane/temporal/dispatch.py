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

# Lazy-initialized client with async lock to avoid import-time connection
_client = None
_client_lock = asyncio.Lock()


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
    goal: str,
    founder_id: str,
    company_id: str = "",
    constraints: Optional[dict] = None,
    workspace_id: str = "",
    chapter_id: str = "",
) -> dict[str, Any]:
    """Start an AstraRunWorkflow on the Temporal server.

    This is the entry point for dispatching runs through Temporal instead
    of the legacy asyncio task path.

    Args:
        run_id: The run identifier (becomes the workflow ID)
        goal: The goal/instruction for the run
        founder_id: The founder who owns this run
        company_id: Optional company/workspace ID
        constraints: Optional constraints dict
        workspace_id: Optional workspace ID
        chapter_id: Optional chapter ID

    Returns:
        Dict with workflow_id, run_id, status
    """
    from backend.control_plane.temporal.workflows import AstraRunWorkflow, RunInput

    client = await _get_client()

    # Build workflow input — IDs and versions only per system invariant #5
    workflow_input = RunInput(
        run_id=run_id,
        goal=goal,
        founder_id=founder_id,
        company_id=company_id,
        constraints=constraints or {},
        workspace_id=workspace_id,
        chapter_id=chapter_id,
    )

    # Start the workflow
    workflow_id = f"astra-run/{run_id}"
    handle = await client.start_workflow(
        AstraRunWorkflow.run,
        workflow_input,
        id=workflow_id,
        task_queue="astra-runs-v1",
    )

    logger.info(
        "started Temporal workflow %s for run=%s founder=%s",
        workflow_id, run_id, founder_id,
    )

    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": "started",
        "task_queue": "astra-runs-v1",
    }


async def cancel_run(run_id: str) -> bool:
    """Cancel a running workflow.

    Args:
        run_id: The run identifier

    Returns:
        True if cancellation was requested
    """
    client = await _get_client()
    workflow_id = f"astra-run/{run_id}"

    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(AstraRunWorkflow.cancel)
        logger.info("sent cancel signal to workflow %s", workflow_id)
        return True
    except Exception as exc:
        logger.warning("failed to cancel workflow %s: %s", workflow_id, exc)
        return False


async def get_workflow_status(run_id: str) -> Optional[dict]:
    """Get the status of a workflow.

    Args:
        run_id: The run identifier

    Returns:
        Dict with workflow info or None if not found
    """
    client = await _get_client()
    workflow_id = f"astra-run/{run_id}"

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

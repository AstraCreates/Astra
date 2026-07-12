"""Wave 1 control plane: Temporal worker entrypoint.

Registers AstraRunWorkflow and its activities on the astra-runs-v1 task queue.
Replaces the AstraPingWorkflow placeholder with real workflow execution.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

NAMESPACE = "astra"
TASK_QUEUE = "astra-runs-v1"


async def run_worker() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from backend.control_plane.temporal.activities import (
        ExecuteOrchestratorActivity,
        PublishEventActivity,
        UpdateRunStatusActivity,
    )
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
    logger.info("connecting to Temporal at %s (namespace=%s)", address, NAMESPACE)
    client = await Client.connect(address, namespace=NAMESPACE)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AstraRunWorkflow],
        activities=[
            ExecuteOrchestratorActivity.execute,
            PublishEventActivity.publish,
            UpdateRunStatusActivity.update,
        ],
    )
    logger.info(
        "worker registered on task queue %s with AstraRunWorkflow + 3 activities, running",
        TASK_QUEUE,
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

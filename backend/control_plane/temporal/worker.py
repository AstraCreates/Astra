"""Wave 1 control plane: minimal Temporal worker entrypoint.

Registers zero workflows/activities on purpose -- Wave 3 (the "Temporal
Observation Shell") is what adds AstraRunWorkflow. This module only proves
a worker process can start, connect to the Temporal server, and hold the
astra-runs-v1 task queue in the astra namespace without crashing. Nothing
in the running app dispatches work through this queue yet.

Run: python -m backend.control_plane.temporal.worker
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

    address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
    logger.info("connecting to Temporal at %s (namespace=%s)", address, NAMESPACE)
    client = await Client.connect(address, namespace=NAMESPACE)

    # workflows=[] / activities=[] on purpose -- see module docstring.
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[], activities=[])
    logger.info("worker registered on task queue %s, running", TASK_QUEUE)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

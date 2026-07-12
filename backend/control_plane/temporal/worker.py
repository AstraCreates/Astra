"""Wave 1 control plane: minimal Temporal worker entrypoint.

Registers a single placeholder workflow so the worker process can start,
connect to the Temporal server, and hold the astra-runs-v1 task queue in
the astra namespace. Real workflows (AstraRunWorkflow, phase activities)
are added in Wave 3/4.

Run: python -m backend.control_plane.temporal.worker
"""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio import workflow

logger = logging.getLogger(__name__)

NAMESPACE = "astra"
TASK_QUEUE = "astra-runs-v1"


@workflow.defn(name="AstraPing")
class AstraPingWorkflow:
    """Minimal placeholder workflow that proves the worker can receive and
    complete work. Replaced by AstraRunWorkflow in Wave 3."""

    @workflow.run
    async def run(self) -> str:
        return "pong"


async def run_worker() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
    logger.info("connecting to Temporal at %s (namespace=%s)", address, NAMESPACE)
    client = await Client.connect(address, namespace=NAMESPACE)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AstraPingWorkflow],
        activities=[],
    )
    logger.info("worker registered on task queue %s with 1 placeholder workflow, running", TASK_QUEUE)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

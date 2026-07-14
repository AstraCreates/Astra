"""Wave 1 control plane: Temporal worker entrypoint.

Registers AstraRunWorkflow and its activities on the astra-runs-v1 task queue.
Replaces the AstraPingWorkflow placeholder with real workflow execution.
"""
from __future__ import annotations

import asyncio
import logging
import os

from backend.control_plane.temporal.contracts import TASK_QUEUE

logger = logging.getLogger(__name__)

NAMESPACE = "astra"


async def run_worker() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from backend.control_plane.temporal.activities import (
        CreatePhaseApprovalActivity,
        ExecuteCompanyBrainTickActivity,
        ExecuteCustomAgentsTickActivity,
        ExecuteDeepResearchActivity,
        ExecuteLaneAttemptActivity,
        ExecuteMissionSchedulerTickActivity,
        ExecuteMonitoringTickActivity,
        ExecuteOrchestratorActivity,
        ExecuteVerificationActivity,
        ExpireApprovalActivity,
        LoadRunPlanActivity,
        ObserveRunActivity,
        PublishEventActivity,
        UpdateRunStatusActivity,
    )
    from backend.control_plane.temporal.company_brain_workflow import CompanyBrainTickWorkflow
    from backend.control_plane.temporal.custom_agents_workflow import CustomAgentsTickWorkflow
    from backend.control_plane.temporal.deep_research_workflow import DeepResearchWorkflow
    from backend.control_plane.temporal.lane_attempt_workflow import LaneAttemptWorkflow
    from backend.control_plane.temporal.missions_workflow import MissionSchedulerTickWorkflow
    from backend.control_plane.temporal.monitoring_workflow import MonitoringTickWorkflow
    from backend.control_plane.temporal.multi_phase_workflow import MultiPhaseRunWorkflow
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.phase_workflow import PhaseRunWorkflow
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    address = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
    logger.info("connecting to Temporal at %s (namespace=%s)", address, NAMESPACE)
    client = await Client.connect(address, namespace=NAMESPACE)

    workflows = [AstraRunWorkflow, PhaseGateWorkflow, LaneAttemptWorkflow, PhaseRunWorkflow, MultiPhaseRunWorkflow, MonitoringTickWorkflow, MissionSchedulerTickWorkflow, CompanyBrainTickWorkflow, CustomAgentsTickWorkflow, DeepResearchWorkflow]
    activities = [
        CreatePhaseApprovalActivity.create,
        ExecuteCompanyBrainTickActivity.execute,
        ExecuteCustomAgentsTickActivity.execute,
        ExecuteDeepResearchActivity.execute,
        ExecuteLaneAttemptActivity.execute,
        ExecuteMissionSchedulerTickActivity.execute,
        ExecuteMonitoringTickActivity.execute,
        ExecuteOrchestratorActivity.execute,
        ExecuteVerificationActivity.execute,
        ExpireApprovalActivity.expire,
        LoadRunPlanActivity.load,
        ObserveRunActivity.record,
        PublishEventActivity.publish,
        UpdateRunStatusActivity.update,
    ]
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities)
    logger.info(
        "worker registered on task queue %s with %d workflows + %d activities, running",
        TASK_QUEUE, len(workflows), len(activities),
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

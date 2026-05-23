import asyncio
import logging
import time
import uuid
from typing import Any

from backend.agents.base import AgentTask, AgentResult
from backend.agents.legal import LEGAL_AGENT
from backend.agents.research import RESEARCH_AGENT
from backend.agents.web import WEB_AGENT
from backend.agents.marketing import MARKETING_AGENT
from backend.agents.technical import TECHNICAL_AGENT
from backend.agents.ops import OPS_AGENT
from backend.db.client import (
    get_ready_tasks,
    has_in_progress_tasks,
    persist_goal,
    persist_task_graph,
    update_goal_status,
    update_task_status,
)
from backend.memory.vector_store import vector_store
from backend.orchestrator.context_builder import build_context
from backend.orchestrator.dag_builder import build_task_dag
from backend.orchestrator.goal_parser import parse_goal
from backend.db.models import Task

logger = logging.getLogger(__name__)

AGENTS = {
    "legal": LEGAL_AGENT,
    "research": RESEARCH_AGENT,
    "web": WEB_AGENT,
    "marketing": MARKETING_AGENT,
    "technical": TECHNICAL_AGENT,
    "ops": OPS_AGENT,
}


class OrchestratorLoop:
    async def run_goal(
        self,
        goal_id: str,
        founder_id: str,
        raw_instruction: str,
        constraints: dict,
    ) -> dict[str, Any]:
        start = time.time()

        parsed = await parse_goal(goal_id, founder_id, raw_instruction)
        dag = await build_task_dag(goal_id, parsed)

        await persist_goal(goal_id, founder_id, parsed["instruction"], constraints)
        await persist_task_graph(goal_id, founder_id, dag)
        await update_goal_status(goal_id, "in_progress")

        results: list[AgentResult] = []
        approvals: list[dict] = []

        while True:
            ready = await get_ready_tasks(goal_id)
            in_progress = await has_in_progress_tasks(goal_id)

            if not ready and not in_progress:
                break

            # Dispatch all ready tasks concurrently
            if ready:
                task_coroutines = []
                for row in ready:
                    await update_task_status(row["id"], "in_progress")
                    task_coroutines.append(self._run_task(row, founder_id, parsed))

                task_results = await asyncio.gather(*task_coroutines, return_exceptions=True)

                for result in task_results:
                    if isinstance(result, Exception):
                        logger.error("Task failed with exception: %s", result)
                        continue

                    if result.status == "done":
                        await update_task_status(result.task_id, "done", result.output)
                        await vector_store.write(
                            doc_id=str(uuid.uuid4()),
                            founder_id=founder_id,
                            namespace=result.agent,
                            agent=result.agent,
                            doc_type="result",
                            content=str(result.output),
                            summary=result.reasoning[:500] if result.reasoning else "Task completed",
                            task_id=result.task_id,
                        )
                        results.append(result)

                    elif result.status == "approval_required":
                        await update_task_status(result.task_id, "awaiting_approval")
                        approvals.append({
                            "task_id": result.task_id,
                            "agent": result.agent,
                            "action": result.approval_action,
                            "consequence": result.approval_consequence,
                        })

                    elif result.status == "blocked":
                        logger.warning("Task %s blocked: %s", result.task_id, result.blocked_reason)
                        await update_task_status(result.task_id, "blocked")

            else:
                await asyncio.sleep(0.5)

        elapsed = time.time() - start
        await update_goal_status(goal_id, "done", elapsed_seconds=elapsed)

        return {
            "goal_id": goal_id,
            "status": "done",
            "results": [
                {"task_id": r.task_id, "agent": r.agent, "output": r.output}
                for r in results
            ],
            "pending_approvals": approvals,
            "elapsed_seconds": elapsed,
        }

    async def _run_task(self, row: dict, founder_id: str, parsed_goal: dict) -> AgentResult:
        agent_id = row["agent"]
        agent = AGENTS.get(agent_id)

        if agent is None:
            return AgentResult(
                task_id=row["id"], agent=agent_id, status="blocked",
                output={}, confidence=0.0, reasoning="",
                blocked_reason=f"No agent registered for '{agent_id}'",
                blocked_needs="Register agent in AGENTS dict",
            )

        task = Task(
            id=row["id"],
            goal_id=row["goal_id"],
            founder_id=founder_id,
            agent=agent_id,
            instruction=row["instruction"],
            context_bundle={**row.get("context_bundle", {}), **parsed_goal.get("entities", {})},
            constraints=row.get("constraints", {}),
            tools_available=row.get("tools_available", []),
        )

        context = await build_context(task, agent.memory_namespaces)
        task.context_bundle = context

        agent_task = AgentTask(
            task_id=task.id,
            goal_id=task.goal_id,
            founder_id=task.founder_id,
            agent=task.agent,
            instruction=task.instruction,
            context_bundle=task.context_bundle,
            constraints=task.constraints,
            tools_available=task.tools_available,
        )

        return await agent.run(agent_task)


orchestrator = OrchestratorLoop()

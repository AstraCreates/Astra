import asyncio
import json
import logging

import google.generativeai as genai

from backend.config import settings

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        genai.configure(api_key=settings.gemini_api_key)
        _model = genai.GenerativeModel("gemini-2.0-flash")
    return _model


_DAG_PROMPT = """\
You are an AI task planner for a startup automation system.

Given this founder goal, build a dependency graph of tasks to complete it.
Available agents: legal, research, web, marketing, technical, ops

Goal: INSTRUCTION_PLACEHOLDER
Entities: ENTITIES_PLACEHOLDER
Priority agents: PRIORITY_AGENTS_PLACEHOLDER

Rules:
- research and legal can run in parallel (no dependencies)
- web and marketing depend on research
- technical depends on web
- ops depends on all others
- Only include agents relevant to the goal
- Each task must have a specific instruction for the agent

Respond ONLY with valid JSON:
{
  "tasks": [
    {
      "task_id": "t_001",
      "agent": "legal",
      "depends_on": [],
      "instruction": "specific instruction for this agent",
      "tools_available": ["doc_generator"],
      "constraints": {}
    }
  ]
}
"""

_FALLBACK_TASK = {
    "task_id": "t_001",
    "agent": "legal",
    "depends_on": [],
    "instruction": "",
    "tools_available": ["doc_generator"],
    "constraints": {},
}


async def build_task_dag(goal_id: str, parsed_goal: dict) -> list[dict]:
    instruction = parsed_goal.get("instruction", "")
    entities_str = json.dumps(parsed_goal.get("entities", {}))
    priority_agents_str = str(parsed_goal.get("priority_agents", []))

    def _call():
        model = _get_model()
        prompt = (
            _DAG_PROMPT
            .replace("INSTRUCTION_PLACEHOLDER", instruction)
            .replace("ENTITIES_PLACEHOLDER", entities_str)
            .replace("PRIORITY_AGENTS_PLACEHOLDER", priority_agents_str)
        )
        return model.generate_content(prompt).text

    raw = await asyncio.to_thread(_call)

    try:
        data = json.loads(raw)
        tasks = data.get("tasks", [])
        if not tasks:
            raise ValueError("empty task list")
        # prefix task_ids with goal_id and deduplicate
        seen_ids = set()
        for i, task in enumerate(tasks):
            tid = task.get("task_id")
            if not tid or tid in seen_ids:
                task["task_id"] = f"{goal_id}_t_{i+1:03d}"
            seen_ids.add(task["task_id"])
            task.setdefault("agent", "legal")
            task.setdefault("instruction", "")
            task.setdefault("depends_on", [])
            task.setdefault("tools_available", [])
            task.setdefault("constraints", {})
        return tasks
    except (json.JSONDecodeError, ValueError):
        logger.warning("DAG builder fallback for goal %s", goal_id)
        fallback = {
            **_FALLBACK_TASK,
            "task_id": f"{goal_id}_t_001",
            "instruction": parsed_goal.get("instruction", ""),
        }
        return [fallback]

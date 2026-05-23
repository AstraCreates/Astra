import asyncio
import json
import logging

import openai

from backend.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=settings.agent_model_base_url,
            api_key=settings.agent_model_api_key,
        )
    return _client


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

Respond ONLY with valid JSON, no markdown, no explanation:
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
        client = _get_client()
        prompt = (
            _DAG_PROMPT
            .replace("INSTRUCTION_PLACEHOLDER", instruction)
            .replace("ENTITIES_PLACEHOLDER", entities_str)
            .replace("PRIORITY_AGENTS_PLACEHOLDER", priority_agents_str)
        )
        response = client.chat.completions.create(
            model=settings.agent_model_name,
            messages=[
                {"role": "system", "content": "You are a JSON-only task planner. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        msg = response.choices[0].message
        content = msg.content or ""
        if not content.strip():
            content = getattr(msg, "reasoning_content", "") or ""
        return content

    raw = await asyncio.to_thread(_call)

    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]

    try:
        data = json.loads(raw)
        tasks = data.get("tasks", [])
        if not tasks:
            raise ValueError("empty task list")
        # Always normalize task IDs to goal-prefixed format and remap depends_on
        old_to_new: dict[str, str] = {}
        for i, task in enumerate(tasks):
            old_id = task.get("task_id") or f"t_{i+1:03d}"
            new_id = f"{goal_id}_t_{i+1:03d}"
            old_to_new[old_id] = new_id
            task["task_id"] = new_id

        for task in tasks:
            task["depends_on"] = [old_to_new.get(dep, dep) for dep in task.get("depends_on", [])]
            task.setdefault("agent", "legal")
            task.setdefault("instruction", "")
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

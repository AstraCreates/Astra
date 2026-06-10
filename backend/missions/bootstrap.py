"""Bootstrap durable company goals and department missions from a completed run."""
from __future__ import annotations

import re
from typing import Any

from backend.missions.company_goal import upsert_company_goal
from backend.missions.store import bulk_upsert_tasks, create_mission, find_mission, list_missions

_DEPARTMENTS = {"research", "marketing", "sales", "technical", "legal", "ops", "finance"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80] or "task"


def bootstrap_company_operating_system(
    session_id: str,
    founder_id: str,
    *,
    goal: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    contract = state.get("execution_contract") or {}
    north_star = str(contract.get("north_star") or goal)
    company_goal = str((state.get("operating_plan") or {}).get("outcome") or goal)
    kpis = list(contract.get("kpis") or [])
    goal_record = upsert_company_goal(
        founder_id,
        north_star=north_star,
        company_goal=company_goal,
        source_session_id=session_id,
        kpis=kpis,
    )

    for index, item in enumerate((state.get("workboard") or {}).get("items") or []):
        department = str(item.get("agent") or "ops")
        if department not in _DEPARTMENTS:
            department = "ops"
        name = str(item.get("title") or f"{department.title()} operating mission")
        mission = find_mission(founder_id, department, name)
        if mission is None:
            mission = create_mission(
                founder_id=founder_id,
                department=department,
                name=name,
                goal=str(item.get("mission") or item.get("summary") or goal),
                primary_metric=str((kpis[0] if kpis else {}).get("label") or north_star),
                objectives=list(item.get("steps") or []),
                budget={"max_runs_per_day": 2, "max_cost_usd_per_run": 1.0},
                approval_policy="require_approval",
            )
        tasks = []
        for task_index, step in enumerate(item.get("steps") or []):
            tasks.append({
                "id": f"{session_id}:{department}:{_slug(str(step))}:{task_index}",
                "title": str(step),
                "status": "pending",
                "notes": str(item.get("summary") or ""),
                "owner_agent": department,
            })
        for artifact_index, artifact in enumerate(item.get("ready_artifacts") or []):
            title = str(artifact.get("title") if isinstance(artifact, dict) else artifact)
            tasks.append({
                "id": f"{session_id}:{department}:artifact:{_slug(title)}:{artifact_index}",
                "title": f"Review artifact: {title}",
                "status": "awaiting_approval",
                "notes": str(item.get("summary") or ""),
                "owner_agent": department,
            })
        if tasks:
            bulk_upsert_tasks(mission["id"], tasks)

    try:
        from backend.tools.notion_sync import sync_founder_operating_system
        notion = sync_founder_operating_system(founder_id)
    except Exception as exc:
        notion = {"ok": False, "error": str(exc)}
    missions = list_missions(founder_id)
    return {
        "founder_id": founder_id,
        "session_id": session_id,
        "company_goal": goal_record,
        "mission_count": len(missions),
        "missions": missions,
        "notion_sync": notion,
    }

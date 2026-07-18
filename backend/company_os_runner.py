"""Durable background execution for policy-approved Company OS missions."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from backend.company_os import (
    append_message,
    create_artifact,
    get_company_os,
    list_company_os,
    update_mission,
    update_squad,
)
from backend.company_os_dispatch import execute_task
from backend.tools.web_search import deep_research

logger = logging.getLogger(__name__)
_ACTIVE_MISSIONS: dict[str, asyncio.Task[None]] = {}
_MAX_ARTIFACT_CONTENT = 80_000


def launch_mission(company_id: str, mission_id: str) -> bool:
    """Schedule one mission once per process; durable attempts prevent replay duplicates."""
    key = f"{company_id}:{mission_id}"
    active = _ACTIVE_MISSIONS.get(key)
    if active and not active.done():
        return False
    task = asyncio.create_task(run_mission(company_id, mission_id), name=f"company-os:{key}")
    _ACTIVE_MISSIONS[key] = task
    task.add_done_callback(lambda _: _ACTIVE_MISSIONS.pop(key, None))
    return True


async def run_mission(company_id: str, mission_id: str) -> None:
    """Execute eligible mission tasks in order and leave a complete local audit trail."""
    company = get_company_os(company_id)
    if not company:
        return
    mission = _find(company.get("missions", []), "mission_id", mission_id)
    if not mission:
        return
    squad = _find(company.get("squads", []), "squad_id", mission["squad_id"])
    if squad:
        update_squad(company_id, squad["squad_id"], state="working", lifecycle="working")
    update_mission(company_id, mission_id, state="working")
    append_message(company_id, f"{mission['name']}: the {mission.get('department', 'operations').replace('_', ' ').title()} Lead started the squad work.", author="copilot", scope="initiative", scope_id=mission["initiative_id"])

    for task in _mission_tasks(company_id, mission_id):
        if task.get("state") not in {"pending", "scheduled"}:
            continue
        append_message(company_id, f"Working on: {task['name']}.", author="copilot", scope="task", scope_id=task["task_id"])
        try:
            result = await asyncio.to_thread(
                execute_task, company_id, task, lambda current: _execute_internal_work(company_id, mission, current)
            )
        except Exception as exc:
            logger.exception("Company OS task failed: company=%s task=%s", company_id, task.get("task_id"))
            update_mission(company_id, mission_id, state="review", blocked_reason=str(exc))
            if squad:
                update_squad(company_id, squad["squad_id"], state="review", lifecycle="review")
            append_message(company_id, f"{mission['name']} needs review before continuing: {exc}", author="copilot", scope="initiative", scope_id=mission["initiative_id"])
            return
        if result.get("status") == "awaiting_approval":
            update_mission(company_id, mission_id, state="waiting")
            if squad:
                update_squad(company_id, squad["squad_id"], state="waiting", lifecycle="review")
            append_message(company_id, f"{mission['name']} is waiting for approval before the next action.", author="copilot", scope="initiative", scope_id=mission["initiative_id"])
            return

    remaining = _mission_tasks(company_id, mission_id)
    if all(task.get("state") in {"done", "awaiting_approval"} for task in remaining):
        final_state = "done" if all(task.get("state") == "done" for task in remaining) else "waiting"
        update_mission(company_id, mission_id, state=final_state)
        if squad:
            update_squad(company_id, squad["squad_id"], state=final_state, lifecycle="done" if final_state == "done" else "review")
        append_message(company_id, f"{mission['name']} is {final_state}. Review the squad artifacts for the evidence and decision brief.", author="copilot", scope="initiative", scope_id=mission["initiative_id"])


async def recover_pending_missions() -> int:
    """Resume policy-approved work after a process restart from local Company OS state."""
    recovered = 0
    for company in await asyncio.to_thread(list_company_os):
        for mission in company.get("missions", []):
            if mission.get("state") not in {"active", "working", "review"}:
                continue
            if any(task.get("state") in {"pending", "scheduled"} for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")):
                recovered += int(launch_mission(company["company_id"], mission["mission_id"]))
    return recovered


def _mission_tasks(company_id: str, mission_id: str) -> list[dict[str, Any]]:
    company = get_company_os(company_id) or {}
    return [task for task in company.get("tasks", []) if task.get("mission_id") == mission_id]


def _execute_internal_work(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Perform only internal work; policy gating happens before this executor is called."""
    if mission.get("department") == "research" and task.get("operation") == "internal_analysis":
        evidence = deep_research(str(mission["name"]), focus="market viability, demand, competition, pricing, and risks")
        if evidence.get("error") or not (evidence.get("report") or evidence.get("sources")):
            raise RuntimeError(evidence.get("error") or "Research returned no usable evidence")
        return _store_artifact(company_id, task, "Research evidence", evidence, source="web research")

    evidence = _latest_research_artifact(company_id, mission.get("mission_id"))
    if task.get("name", "").lower().startswith("synthesize"):
        content = _synthesis(evidence)
        return _store_artifact(company_id, task, "Research synthesis", {"content": content}, source="internal analysis")
    content = _decision_brief(evidence)
    return _store_artifact(company_id, task, "Decision brief", {"content": content}, source="internal analysis")


def _store_artifact(company_id: str, task: Mapping[str, Any], label: str, result: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    content = str(result.get("content") or result.get("report") or result.get("formatted") or result)
    artifact = create_artifact(company_id, f"{label}: {task['name']}", task_id=task["task_id"], source=source,
                               content=content[:_MAX_ARTIFACT_CONTENT], source_references=result.get("sources", []))
    return {"artifact_id": artifact["artifact_id"], "source_count": len(result.get("sources", []))}


def _latest_research_artifact(company_id: str, mission_id: object) -> Mapping[str, Any]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission_id}
    artifacts = [artifact for artifact in company.get("artifacts", []) if artifact.get("task_id") in task_ids]
    return artifacts[0] if artifacts else {}


def _synthesis(evidence: Mapping[str, Any]) -> str:
    source_refs = evidence.get("source_references") or []
    source_lines = []
    for source in source_refs[:12]:
        if isinstance(source, Mapping):
            source_lines.append(f"- {source.get('title') or 'Source'}: {source.get('url') or ''}")
    return "## Evidence synthesis\n\n" + (evidence.get("content") or "No evidence artifact was available.")[:20_000] + "\n\n## Sources\n" + ("\n".join(source_lines) or "No source URLs were returned.")


def _decision_brief(evidence: Mapping[str, Any]) -> str:
    return "## Decision brief\n\n" + (evidence.get("content") or "Evidence is still being collected.")[:16_000] + "\n\nRecommendation: treat this as an internal, review-ready research brief. Validate the cited evidence and unit economics before committing spend, publishing claims, or contacting prospects."


def _find(items: list[Mapping[str, Any]], key: str, value: object) -> Mapping[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)

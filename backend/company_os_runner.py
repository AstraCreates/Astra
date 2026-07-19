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
from backend.company_os_mcp import invoke as invoke_mcp

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
    append_message(company_id, f"{mission['name']}: the {mission.get('department', 'operations').replace('_', ' ').title()} Lead started the squad work.", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")

    for task in _mission_tasks(company_id, mission_id):
        if task.get("state") not in {"pending", "scheduled"}:
            continue
        append_message(company_id, f"Working on: {task['name']}.", author="copilot", scope="task", scope_id=task["task_id"], kind="status")
        try:
            result = await asyncio.to_thread(
                execute_task, company_id, task, lambda current: _execute_internal_work(company_id, mission, current)
            )
        except Exception as exc:
            logger.exception("Company OS task failed: company=%s task=%s", company_id, task.get("task_id"))
            update_mission(company_id, mission_id, state="review", blocked_reason=str(exc))
            if squad:
                update_squad(company_id, squad["squad_id"], state="review", lifecycle="review")
            append_message(company_id, f"{mission['name']} needs review before continuing: {exc}", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
            return
        if result.get("status") == "awaiting_approval":
            update_mission(company_id, mission_id, state="waiting")
            if squad:
                update_squad(company_id, squad["squad_id"], state="waiting", lifecycle="review")
            append_message(company_id, f"{mission['name']} is waiting for approval before the next action.", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
            return

    remaining = _mission_tasks(company_id, mission_id)
    if all(task.get("state") in {"done", "awaiting_approval"} for task in remaining):
        final_state = "done" if all(task.get("state") == "done" for task in remaining) else "waiting"
        update_mission(company_id, mission_id, state=final_state)
        if squad:
            update_squad(company_id, squad["squad_id"], state=final_state, lifecycle="done" if final_state == "done" else "review")
        if final_state == "done":
            reply = _completion_reply(company_id, mission)
        else:
            reply = f"{mission['name']} is waiting on your approval before the last step. Check Approvals in the sidebar."
        append_message(company_id, reply, author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="chat")


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
        evidence = invoke_mcp(
            company_id,
            "astra_company_research",
            {"subject": _research_subject(str(mission["name"])), "focus": "market"},
        )
        sources = [source for source in evidence.get("sources", []) if isinstance(source, Mapping) and source.get("url")]
        domains = {str(source["url"]).split("/", 3)[2].lower() for source in sources if str(source["url"]).startswith(("http://", "https://"))}
        content = str(evidence.get("combined_formatted") or "").strip()
        if evidence.get("error") or len(sources) < 3 or len(domains) < 2 or not content:
            raise RuntimeError("Research evidence did not meet the source-quality gate: three cited sources across two domains and usable evidence are required.")
        evidence["sources"] = sources
        return _store_artifact(company_id, task, "Research evidence", evidence, source="web research")

    evidence = _latest_research_artifact(company_id, mission.get("mission_id"))
    if task.get("name", "").lower().startswith("synthesize"):
        content = _synthesis(evidence)
        return _store_artifact(company_id, task, "Research synthesis", {"content": content}, source="internal analysis")
    content = _decision_brief(evidence)
    return _store_artifact(company_id, task, "Decision brief", {"content": content}, source="internal analysis")


def _store_artifact(company_id: str, task: Mapping[str, Any], label: str, result: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    # Research pipelines expose the human-readable evidence under
    # combined_formatted. Falling through to str(result) leaked raw tool JSON.
    content = str(result.get("content") or result.get("report") or result.get("combined_formatted") or result.get("formatted") or result)
    artifact = create_artifact(company_id, f"{label}: {task['name']}", task_id=task["task_id"], source=source,
                               content=content[:_MAX_ARTIFACT_CONTENT], source_references=result.get("sources", []))
    return {"artifact_id": artifact["artifact_id"], "source_count": len(result.get("sources", []))}


def _latest_research_artifact(company_id: str, mission_id: object) -> Mapping[str, Any]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission_id}
    artifacts = [artifact for artifact in company.get("artifacts", []) if artifact.get("task_id") in task_ids]
    return artifacts[0] if artifacts else {}


def _completion_reply(company_id: str, mission: Mapping[str, Any]) -> str:
    """Answer in the founder's terms instead of pointing at a log line -- the
    chat thread is a conversation, not a task tracker (the sidebar already
    covers per-task status)."""
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")}
    brief = next((a for a in company.get("artifacts", []) if a.get("task_id") in task_ids and str(a.get("name", "")).startswith("Decision brief")), None)
    if not brief or not brief.get("content"):
        return f"{mission['name']} is done. I didn't produce a decision brief for it -- check the squad's artifacts for what was gathered."
    excerpt = str(brief["content"]).split("## Recommendation", 1)
    findings = excerpt[0].replace("## Decision brief", "").strip()[:600]
    recommendation = ("## Recommendation" + excerpt[1]).strip() if len(excerpt) > 1 else ""
    reply = f"Here's what I found on {mission['name'].lower()}:\n\n{findings}"
    if recommendation:
        reply += f"\n\n{recommendation}"
    reply += "\n\nFull evidence and sources are in the artifact if you want to dig in."
    return reply


def _synthesis(evidence: Mapping[str, Any]) -> str:
    source_refs = evidence.get("source_references") or []
    source_lines = []
    for source in source_refs[:12]:
        if isinstance(source, Mapping):
            source_lines.append(f"- {source.get('title') or 'Source'}: {source.get('url') or ''}")
    if not source_lines:
        raise RuntimeError("Cannot synthesize uncited research evidence.")
    return "## Evidence synthesis\n\n" + (evidence.get("content") or "No evidence artifact was available.")[:20_000] + "\n\n## Verified sources\n" + "\n".join(source_lines)


def _decision_brief(evidence: Mapping[str, Any]) -> str:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot produce a decision brief without cited evidence.")
    return "## Decision brief\n\n" + (evidence.get("content") or "Evidence is still being collected.")[:16_000] + "\n\n## Recommendation\nTreat this as a hypothesis, not a launch decision. Choose one target player segment, one platform, and one monetization model; then validate retention, conversion, and acquisition economics with a small instrumented prototype before scaling spend."


def _research_subject(intent: str) -> str:
    """Resolve high-risk product-language ambiguity before web queries are generated."""
    if "cookie clicker" in intent.lower():
        return f"{intent} as an idle/incremental video game, including game monetization, retention, platform fees, player acquisition, and comparable games"
    return intent


def _find(items: list[Mapping[str, Any]], key: str, value: object) -> Mapping[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)

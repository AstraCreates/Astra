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
    mission_name = str(mission.get("name") or "this research")
    if mission.get("department") == "research" and task.get("operation") == "internal_analysis":
        evidence = invoke_mcp(
            company_id,
            "astra_company_research",
            {"subject": _research_subject(mission_name), "focus": "market"},
        )
        sources = [source for source in evidence.get("sources", []) if isinstance(source, Mapping) and source.get("url")]
        domains = {str(source["url"]).split("/", 3)[2].lower() for source in sources if str(source["url"]).startswith(("http://", "https://"))}
        content = str(evidence.get("combined_formatted") or "").strip()
        if evidence.get("error") or len(sources) < 3 or len(domains) < 2 or not content:
            raise RuntimeError("Research evidence did not meet the source-quality gate: three cited sources across two domains and usable evidence are required.")
        evidence["sources"] = sources
        return _store_artifact(company_id, task, f"Research evidence — {_short_title(mission_name)}", evidence, source="web research")

    evidence = _latest_research_artifact(company_id, mission.get("mission_id"))
    if task.get("name", "").lower().startswith("synthesize"):
        title, content = _synthesis(mission_name, evidence)
        return _store_artifact(company_id, task, title, {"content": content}, source="internal analysis")
    title, content = _decision_brief(mission_name, evidence)
    return _store_artifact(company_id, task, title, {"content": content}, source="internal analysis")


def _store_artifact(company_id: str, task: Mapping[str, Any], title: str, result: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    # Research pipelines expose the human-readable evidence under
    # combined_formatted. Falling through to str(result) leaked raw tool JSON.
    content = str(result.get("content") or result.get("report") or result.get("combined_formatted") or result.get("formatted") or result)
    artifact = create_artifact(company_id, title, task_id=task["task_id"], source=source,
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
    covers per-task status). The mission's LAST artifact is always its final
    output regardless of department (each department's 3-step plan ends on
    its "produce the output" step), so pick by recency rather than matching
    an artifact-name prefix that a synthesized title might not contain."""
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")}
    mission_artifacts = [a for a in company.get("artifacts", []) if a.get("task_id") in task_ids]
    brief = mission_artifacts[-1] if mission_artifacts else None
    if not brief or not brief.get("content"):
        return f"{mission['name']} is done. I didn't produce anything usable for it -- check the squad's artifacts for what was gathered."
    return _synthesize_chat_reply(str(mission.get("name") or ""), brief)


def _synthesize_chat_reply(mission_name: str, brief: Mapping[str, Any]) -> str:
    """Answer like an assistant that actually read the document, not a
    regex-excerpt of it. Founders were seeing raw web-search sub-query
    headers pasted verbatim into chat, plus the exact same generic
    disclaimer paragraph on every single research reply regardless of what
    was actually asked."""
    content = str(brief.get("content") or "")
    doc_name = str(brief.get("name") or "the document")
    try:
        from backend.tools._llm import generate
        prompt = f"""You are Astra Copilot telling a founder you finished researching something for them.

Their question: "{mission_name}"

The document you produced ("{doc_name}"):
{content[:6000]}

Write a short, natural, first-person chat reply (3-5 sentences) that actually answers their question using the real findings above -- specific facts and numbers, not a restatement of the document's structure or headings. End by pointing them to "{doc_name}" if they want the full write-up. No headers, no bullet lists, no generic disclaimers about hypotheses or validating before scaling unless the evidence genuinely warrants that specific caveat.

Respond with ONLY the reply text, nothing else, no quotes around it."""
        reply = generate(prompt, model="fast", max_tokens=400, temperature=0.5).strip().strip('"')
        if reply:
            return reply
    except Exception:
        logger.warning("Chat-reply synthesis failed for mission=%r", mission_name, exc_info=True)
    excerpt = content[:500].strip()
    return f"I finished looking into {mission_name.lower()}. Here's a start:\n\n{excerpt}\n\nFull write-up is in \"{doc_name}\" if you want more detail."


def _synthesis(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot synthesize uncited research evidence.")
    return _synthesize_document(mission_name, evidence, purpose="synthesizing raw research into a clear internal note",
                                fallback_title=f"Research notes — {_short_title(mission_name)}")


def _decision_brief(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot produce a decision brief without cited evidence.")
    return _synthesize_document(mission_name, evidence, purpose="writing a decision-ready brief",
                                fallback_title=f"Findings — {_short_title(mission_name)}")


def _synthesize_document(mission_name: str, evidence: Mapping[str, Any], *, purpose: str, fallback_title: str) -> tuple[str, str]:
    """LLM-synthesize a real document from raw research evidence instead of
    truncate-and-glue with a fixed generic ending. The old version appended
    the identical "Treat this as a hypothesis..." paragraph to every single
    research task's output verbatim, and forced a market-sizing structure
    onto every question including plain "what is X" lookups. Falls back to a
    plain excerpt (uglier, but honest and still usable) if the LLM call
    fails, so a model hiccup never blocks the mission."""
    raw = str(evidence.get("content") or evidence.get("combined_formatted") or "").strip() or "No evidence content was captured."
    source_refs = evidence.get("source_references") or evidence.get("sources") or []
    source_lines = [f"- {source.get('title') or 'Source'}: {source.get('url') or ''}" for source in source_refs[:12] if isinstance(source, Mapping)]
    prompt = f"""You are a sharp research analyst {purpose} for a founder inside Astra.

The founder's actual question: "{mission_name}"

Raw research evidence (pulled from several web sub-queries; some may be generic or tangential -- use only what actually answers the founder's question and ignore the rest):
{raw[:12000]}

Cited sources:
{chr(10).join(source_lines) or "(none captured)"}

Write a genuinely useful markdown document that answers the founder's actual question. Requirements:
- Open with a direct, specific answer to the question -- no throat-clearing, no "based on the research provided".
- Organize with ## headings that fit what was ACTUALLY asked. A "what is X" question needs a clear overview, not a forced TAM/SAM/CAGR breakdown; a viability or market question does warrant that structure.
- Pull real facts, numbers, and names from the evidence above. Skip anything the evidence doesn't actually support -- don't invent specifics.
- Aim for 400-900 words of real substance -- long enough to be genuinely useful, never padded with filler.
- End with a "## Bottom line" section: one specific, actionable takeaway grounded in what was actually found here. Never a generic template like "validate before scaling spend" unless the evidence specifically points there.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"title": "<a specific, concrete 4-9 word document title -- never generic labels like \\"Decision brief\\" or \\"Research synthesis\\">", "content": "<the full markdown document>"}}"""
    try:
        import json
        from backend.tools._llm import generate
        raw_response = generate(prompt, model="large", json_mode=True, max_tokens=2200, temperature=0.5)
        parsed = json.loads(_strip_json_fence(raw_response))
        title, content = str(parsed.get("title") or "").strip(), str(parsed.get("content") or "").strip()
        if title and content:
            return title, content
    except Exception:
        logger.warning("Document synthesis failed for mission=%r, falling back to raw excerpt", mission_name, exc_info=True)
    return fallback_title, f"## {fallback_title}\n\n{raw[:8000]}"


def _short_title(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def _research_subject(intent: str) -> str:
    """Resolve high-risk product-language ambiguity before web queries are generated."""
    if "cookie clicker" in intent.lower():
        return f"{intent} as an idle/incremental video game, including game monetization, retention, platform fees, player acquisition, and comparable games"
    return intent


def _find(items: list[Mapping[str, Any]], key: str, value: object) -> Mapping[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)

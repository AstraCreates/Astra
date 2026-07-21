"""Durable background execution for policy-approved Company OS missions."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.company_os import (
    append_message,
    company_recovery_lock,
    create_artifact,
    get_company_os,
    list_company_os,
    reconcile_initiatives,
    update_mission,
    update_task,
    update_artifact,
    update_squad,
)
from backend.company_os_dispatch import execute_task
from backend.company_os_mcp import invoke as invoke_mcp
from backend.tools.research_evidence import validate_deep_research

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
    dependencies = set(mission.get("depends_on_mission_ids") or [])
    completed = {item.get("mission_id") for item in company.get("missions", []) if item.get("state") == "done"}
    if not dependencies.issubset(completed):
        # This is a dependency wait, not a failure or an approval. The
        # prerequisite's completion resumes the mission automatically.
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
            reconcile_initiatives(company_id)
            return
        if result.get("status") == "awaiting_approval":
            update_mission(company_id, mission_id, state="waiting")
            if squad:
                update_squad(company_id, squad["squad_id"], state="waiting", lifecycle="review")
            append_message(company_id, f"{mission['name']} is waiting for approval before the next action.", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
            reconcile_initiatives(company_id)
            return

    final_state: str | None = None
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
    reconcile_initiatives(company_id)
    if final_state == "done":
        _resume_ready_dependents(company_id, mission_id)


async def recover_pending_missions() -> int:
    """Resume policy-approved work after a process restart from local Company OS state.

    A process can die after persisting ``working`` but before its in-memory
    asyncio task finishes. Those records used to remain working forever,
    because recovery only considered pending tasks. Reset only records older
    than the bounded stale threshold so a genuinely active deep-research pass
    is not duplicated.
    """
    from backend.config import settings

    def is_stale(task: Mapping[str, Any]) -> bool:
        if task.get("state") != "working":
            return False
        timestamp = str(task.get("updated_at") or task.get("started_at") or "")
        try:
            updated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - updated).total_seconds() >= max(60, int(settings.company_os_stale_task_seconds))

    recovered = 0
    for company in await asyncio.to_thread(list_company_os):
        for mission in company.get("missions", []):
            if mission.get("state") not in {"active", "working", "review"}:
                continue
            mission_tasks = [task for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")]
            stale_tasks = [task for task in mission_tasks if is_stale(task)]
            pending_tasks = [task for task in mission_tasks if task.get("state") in {"pending", "scheduled"}]
            if stale_tasks or pending_tasks:
                # Startup runs once per web worker. Re-read under a shared
                # company lock so only one worker can claim and execute an
                # orphaned or previously re-queued task; the other workers
                # observe the fresh state.
                with company_recovery_lock(company["company_id"]):
                    current = get_company_os(company["company_id"]) or {}
                    current_mission = _find(current.get("missions", []), "mission_id", mission["mission_id"])
                    current_tasks = [task for task in current.get("tasks", []) if task.get("mission_id") == mission["mission_id"]]
                    current_stale = [task for task in current_tasks if is_stale(task)]
                    current_pending = [task for task in current_tasks if task.get("state") in {"pending", "scheduled"}]
                    if not current_mission or not current_stale and not current_pending:
                        continue
                    for task in current_stale:
                        update_task(company["company_id"], task["task_id"], state="pending", blocked_reason=None,
                                    recovery_reason="stale_working_task_after_process_restart")
                        append_message(company["company_id"], f"Recovered stalled work: {task.get('name', 'task')} is being retried.",
                                       author="copilot", scope="task", scope_id=task["task_id"], kind="status")
                    # Await instead of using fire-and-forget startup work so
                    # the claim and first attempt cannot be lost.
                    await run_mission(company["company_id"], mission["mission_id"])
                    recovered += 1
    return recovered


def _mission_tasks(company_id: str, mission_id: str) -> list[dict[str, Any]]:
    company = get_company_os(company_id) or {}
    return [task for task in company.get("tasks", []) if task.get("mission_id") == mission_id]


def _execute_internal_work(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Perform only internal work; policy gating happens before this executor is called."""
    if str(task.get("mcp_tool") or "") == "astra_company_research" and str(mission.get("department") or "") == "operations":
        raise RuntimeError("Research task is attached to Company Operations; retry after routing repair.")
    mission_name = str(mission.get("name") or "this research")
    if task.get("operation") == "external_deploy":
        company = get_company_os(company_id) or {}
        artifact = next((item for item in reversed(company.get("artifacts", []))
                         if item.get("task_id") and item.get("initiative_id") == mission.get("initiative_id")
                         and str(item.get("name") or "").lower().startswith("website preview")
                         and item.get("state") != "archived"), None)
        if not artifact or not str(artifact.get("content") or "").strip():
            raise RuntimeError("The website preview artifact is missing; nothing was published.")
        domain, _brand = _website_identity(mission_name)
        project_slug = re.sub(r"[^a-z0-9-]+", "-", domain.split(".", 1)[0].lower()).strip("-") or "astra-site"
        result = invoke_mcp(
            company_id,
            str(task.get("mcp_tool") or "vercel_deploy"),
            {"project_slug": project_slug, "html": str(artifact["content"])},
            task_id=str(task.get("task_id") or ""), mission_id=str(mission.get("mission_id") or ""), approved=True,
        )
        if not result.get("deployed") or not result.get("url"):
            raise RuntimeError(str(result.get("error") or result.get("note") or "Vercel deployment did not return a public URL."))
        update_artifact(company_id, str(artifact["artifact_id"]), url=result["url"], hosting="vercel", hosting_project=project_slug, hosting_status="deployed")
        return {"deployed": True, "url": result["url"], "artifact_id": artifact["artifact_id"]}
    if mission.get("department") == "research" and task.get("operation") == "internal_analysis":
        evidence = invoke_mcp(
            company_id,
            str(task.get("mcp_tool") or "astra_company_research"),
            {"subject": _research_subject(mission_name), "focus": "market"},
            task_id=str(task.get("task_id") or ""), mission_id=str(mission.get("mission_id") or ""),
            squad_id=str(mission.get("squad_id") or ""), initiative_id=str(mission.get("initiative_id") or ""),
        )
        sources = [source for source in evidence.get("sources", []) if isinstance(source, Mapping) and source.get("url")]
        validation = evidence.get("evidence_validation") or validate_deep_research(evidence)
        if evidence.get("error") or evidence.get("research_status") != "validated" or not validation.get("ok"):
            reason = "; ".join(([str(evidence.get("error"))] if evidence.get("error") else [])
                                + (validation.get("gaps") or ["deep research evidence gate failed"]))
            raise RuntimeError(f"Deep research blocked by evidence gate: {reason}")
        evidence["sources"] = sources
        evidence["evidence_validation"] = validation
        # Raw evidence and the mid-pipeline synthesis note are working
        # material, not something a founder asked for -- every research
        # mission was dropping 3 separate documents into the Library for
        # what reads as "one request, one answer". Kept (archived, not
        # deleted) so the later steps and citations still have them, just
        # not surfaced as top-level artifacts.
        return _store_artifact(company_id, task, f"Research evidence — {_short_title(mission_name)}", evidence, source="web research", internal=True)

    if mission.get("department") == "product_technical" and _is_website_request(mission_name):
        title = str(task.get("name") or "")
        if "local website preview" in title.lower():
            sources = _initiative_evidence(company_id, mission.get("initiative_id"))
            return _store_artifact(company_id, task, f"Website preview — {_short_title(mission_name)}",
                                   {"content": _website_preview(mission_name, sources), "sources": sources}, source="local website", internal=False)
        if "publication decision" in title.lower() or "publish approval" in title.lower():
            return _store_artifact(company_id, task, f"Website review — {_short_title(mission_name)}", {"content": "## Local preview ready\n\nThe local website preview is available in the Library. No publication or deployment has been requested. If you later choose to publish it, that separate external action will require approval."}, source="internal analysis")
        return _store_artifact(company_id, task, f"Website brief — {_short_title(mission_name)}", {"content": _website_brief(mission_name)}, source="internal analysis", internal=True)

    evidence = _latest_research_artifact(company_id, mission.get("mission_id"))
    if task.get("name", "").lower().startswith("synthesize"):
        title, content = _synthesis(mission_name, evidence)
        return _store_artifact(company_id, task, title, {"content": content, "sources": evidence.get("source_references") or evidence.get("sources", []), "evidence_ledger": evidence.get("evidence_ledger")}, source="internal analysis", internal=True)
    title, content = _decision_brief(mission_name, evidence)
    return _store_artifact(company_id, task, title, {"content": content, "sources": evidence.get("source_references") or evidence.get("sources", []), "evidence_ledger": evidence.get("evidence_ledger")}, source="internal analysis")


def _store_artifact(company_id: str, task: Mapping[str, Any], title: str, result: Mapping[str, Any], *, source: str, internal: bool = False) -> dict[str, Any]:
    # Research pipelines expose the human-readable evidence under
    # combined_formatted. Falling through to str(result) leaked raw tool JSON.
    content = str(result.get("content") or result.get("report") or result.get("combined_formatted") or result.get("formatted") or result)
    artifact = create_artifact(company_id, title, task_id=task["task_id"], source=source,
                               content=content[:_MAX_ARTIFACT_CONTENT], source_references=result.get("sources", []),
                               evidence_ledger=result.get("evidence_ledger"),
                               research_status=result.get("research_status"), research_metadata=result.get("research_metadata"),
                               evidence_validation=result.get("evidence_validation"),
                               deep_research_supervisor=bool(result.get("deep_research_supervisor")),
                               state="archived" if internal else "active")
    return {"artifact_id": artifact["artifact_id"], "source_count": len(result.get("sources", [])),
            "research_metadata": result.get("research_metadata"),
            "evidence_validation": result.get("evidence_validation"),
            "research_status": result.get("research_status")}


def _latest_research_artifact(company_id: str, mission_id: object) -> Mapping[str, Any]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission_id}
    artifacts = [artifact for artifact in company.get("artifacts", []) if artifact.get("task_id") in task_ids]
    return artifacts[0] if artifacts else {}


def _initiative_evidence(company_id: str, initiative_id: object) -> list[Mapping[str, Any]]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("initiative_id") == initiative_id}
    sources: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for artifact in company.get("artifacts", []):
        if artifact.get("task_id") not in task_ids:
            continue
        for source in artifact.get("source_references") or []:
            if not isinstance(source, Mapping) or not source.get("url") or source["url"] in seen:
                continue
            seen.add(source["url"])
            sources.append(source)
    return sources[:8]


def _resume_ready_dependents(company_id: str, completed_mission_id: str) -> None:
    company = get_company_os(company_id) or {}
    completed = {item.get("mission_id") for item in company.get("missions", []) if item.get("state") == "done"}
    for mission in company.get("missions", []):
        dependencies = set(mission.get("depends_on_mission_ids") or [])
        if completed_mission_id in dependencies and mission.get("state") in {"active", "working"} and dependencies.issubset(completed):
            launch_mission(company_id, mission["mission_id"])


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

Write a concise, polished markdown update that actually answers their question using the real findings above. Use this exact shape:
- One direct opening sentence.
- 2-4 short bullet points with the most decision-relevant facts, numbers, or caveats.
- One final sentence linking them to "{doc_name}" for the full write-up.

Never repeat the document's headings or raw research queries. Do not make generic disclaimers unless the evidence genuinely warrants that caveat. Every sentence must end cleanly; do not stop mid-thought.

Respond with ONLY the reply text, nothing else, no quotes around it."""
        reply = generate(prompt, model="fast", max_tokens=700, temperature=0.35).strip().strip('"')
        if _complete_chat_reply(reply):
            return reply
    except Exception:
        logger.warning("Chat-reply synthesis failed for mission=%r", mission_name, exc_info=True)
    summary = _fallback_summary(content)
    return f"I finished looking into {mission_name.lower()}.\n\n{summary}\n\nFull write-up: **{doc_name}**."


def _complete_chat_reply(reply: str) -> bool:
    """Never surface a provider response that stopped in the middle of a thought."""
    compact = " ".join(reply.split())
    return len(compact) >= 80 and compact[-1:] in {".", "!", "?"} and len(compact) <= 3_000


def _fallback_summary(content: str) -> str:
    """Keep a provider hiccup useful without dumping arbitrary raw text into chat."""
    blocks = [block.strip() for block in content.split("\n\n") if block.strip() and not block.strip().startswith("#")]
    first = next((block for block in blocks if len(block) >= 40), "The completed brief contains the available findings and caveats.")
    sentence = first.split(". ", 1)[0].rstrip(".") + "."
    return f"- {sentence}"


def _synthesis(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot synthesize uncited research evidence.")
    return _synthesize_document(mission_name, evidence, purpose="synthesizing raw research into a clear internal note",
                                fallback_title=f"Research notes — {_short_title(mission_name)}")


def _decision_brief(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot produce a decision brief without cited evidence.")
    if evidence.get("deep_research_supervisor"):
        # The Open Deep Research supervisor already wrote a fully cited,
        # multi-section report -- re-summarizing it through _synthesize_document
        # would throw its citations and structure away for a generic 400-900
        # word note. Use it as-is; only fall through if it came back thin.
        report = str(evidence.get("content") or "").strip()
        if len(report) > 500:
            return _report_title(report, fallback_title=f"Findings — {_short_title(mission_name)}"), report
    if _is_comparison_request(mission_name):
        return _synthesize_comparison_document(mission_name, evidence)
    return _synthesize_document(mission_name, evidence, purpose="writing a decision-ready brief",
                                fallback_title=f"Findings — {_short_title(mission_name)}")


def _report_title(report: str, *, fallback_title: str) -> str:
    match = re.match(r"^#\s+(.+)$", report.split("\n", 1)[0].strip())
    return _short_title(match.group(1)) if match else fallback_title


def _synthesize_comparison_document(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    """LLM-write a real comparison report (executive summary, a dimension
    table, thematic deep-dive sections, pros/cons per subject, a bottom
    line) grounded only in fetched evidence -- the mechanical table-only
    _comparison_document() below was never actually reachable for a real
    "compare X and Y" request until this function replaced it as the
    primary path (it's now only the safety-net fallback on LLM failure).
    Preserves the original safety property: never invent a winner beyond
    what the evidence supports, and say so plainly when coverage is thin."""
    ledger = evidence.get("evidence_ledger") or {}
    subjects = list(ledger)
    if len(subjects) != 2:
        return _comparison_document(mission_name, evidence)
    left, right = subjects
    coverage = evidence.get("coverage") or {}
    ready = bool(coverage.get("ready"))
    raw = str(evidence.get("combined_formatted") or "").strip()
    if not raw:
        return _comparison_document(mission_name, evidence)

    evidence_by_subject = []
    for subject in subjects:
        lines = [f"### {subject}"]
        for dimension, claims in (ledger.get(subject) or {}).items():
            for claim in claims[:4]:
                if isinstance(claim, Mapping) and claim.get("excerpt"):
                    lines.append(f"- [{dimension}] {claim['excerpt']} (Source: {claim.get('title') or 'Source'}, {claim.get('url') or ''})")
        evidence_by_subject.append("\n".join(lines))

    prompt = f"""You are a sharp analyst writing a comparison report for a founder deciding between two products/companies: "{left}" and "{right}".

Fetched evidence, organized by subject and dimension (each line is one claim grounded in a real fetched page, with its source):
{chr(10).join(evidence_by_subject)}

Raw combined research text (for additional context and phrasing, may overlap the evidence above):
{raw[:14000]}

Evidence coverage is {"sufficient across both subjects" if ready else "THIN for at least one subject/dimension -- be explicit about which claims are unverified rather than guessing"}.

Write a genuinely useful, comprehensive markdown comparison report. Requirements:
- Open with "## Executive summary": 2-3 paragraphs giving the direct, specific comparison and where each subject is stronger, using only what the evidence above actually supports.
- "## Comparison overview": a markdown table with rows for the dimensions the evidence actually covers (e.g. business model, pricing, target customers, team/leadership visibility, technology/documentation, evidence and credibility, legal terms) and one column per subject, plus an "Analytical take" column. Write "Not verified from available public evidence" for any cell the evidence doesn't support -- never invent a value.
- 2-4 more "##" deep-dive sections grouping related dimensions into a coherent narrative (e.g. "Business model and pricing", "Team and technology", "Evidence, reputation, and legal terms") -- do not just repeat the table as prose; synthesize and explain what the differences mean for a founder's decision.
- A "### {left} pros and cons" and "### {right} pros and cons" section, each a two-column markdown table (Pros | Cons), grounded in the evidence.
- End with "## Bottom line": a direct, specific recommendation of which subject fits which kind of founder/use case, {"including a clear recommendation since the evidence is sufficient" if ready else "explicitly declining to declare an overall winner given the evidence gaps, while still summarizing the clearest differences"}.
- Pull real facts, names, and numbers from the evidence above. Never invent specifics, comparisons, or claims the evidence doesn't support.
- Aim for 900-1600 words of real substance -- this is a comprehensive report, not a summary.
- Do not mention Astra, tools, AI systems, or how this research was conducted -- focus entirely on the two subjects and the evidence.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"title": "<a specific 4-9 word title, e.g. '{left} and {right} Compared'>", "content": "<the full markdown document>"}}"""
    try:
        from backend.tools._llm import generate, parse_json_response
        raw_response = generate(prompt, model="large", json_mode=True, max_tokens=4000, temperature=0.5)
        parsed = parse_json_response(raw_response)
        title, content = str(parsed.get("title") or "").strip(), str(parsed.get("content") or "").strip()
        if title and content:
            return title, content
    except Exception:
        logger.warning("Comparison document synthesis failed for mission=%r, falling back to the evidence table", mission_name, exc_info=True)
    return _comparison_document(mission_name, evidence)


def _comparison_document(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    ledger = evidence.get("evidence_ledger") or {}
    subjects = list(ledger)
    if len(subjects) != 2:
        return "Comparison evidence incomplete", "## Evidence incomplete\n\nThe requested products could not be identified reliably. No recommendation was made."
    left, right = subjects
    dimensions = (("Product and target user", "product"), ("Core workflow", "workflow"), ("Pricing and packaging", "pricing"), ("Privacy and compliance", "privacy"), ("Evidence and maturity", "evidence_maturity"))
    rows = []
    gaps = []
    for label, key in dimensions:
        values = []
        for subject in subjects:
            claims = ledger.get(subject, {}).get(key) or []
            if claims:
                values.append("; ".join(
                    f"[{item.get('title') or 'Source'}]({item.get('url')}) ({item.get('source_classification') or item.get('source_type') or 'source'})"
                    for item in claims[:2]
                ))
            else:
                values.append("Not verified from available public evidence")
                gaps.append(f"{subject}: {label}")
        rows.append(f"| {label} | {values[0]} | {values[1]} |")
    title = f"{_short_title(left)} and {_short_title(right)} comparison"
    ready = bool((evidence.get("coverage") or {}).get("ready")) and not gaps
    direct_answer = "The comparison gate passed; the ledger below is ready for a founder decision, without automatically declaring a winner." if ready else "A recommendation is withheld because Astra only compares products when both sides have verified evidence for every core dimension."
    body = ["## Direct answer", direct_answer, "", "## Verified evidence", f"| Dimension | {left} | {right} |", "| --- | --- | --- |", *rows, "", "## Evidence gaps"]
    body.extend(f"- {gap}" for gap in gaps) if gaps else body.extend(["- Both products met the balanced evidence gate."])
    body.extend(["", "## Bottom line", "No winner is declared until the evidence gaps above are filled with direct, publicly verifiable sources." if not ready else "Use the cited fetched evidence to weigh the founder's specific priorities; Astra does not infer a winner from source counts alone."])
    return title, "\n".join(body)


def _is_website_request(value: str) -> bool:
    return any(term in value.lower() for term in ("website", "web site", "landing page", "web app", "frontend"))


def _website_brief(request: str) -> str:
    domain, brand = _website_identity(request)
    return f"## {brand} local website brief\n\n- **Destination:** `{domain}`\n- **Scope:** a local, reviewable website concept only\n- **Research dependency:** comparison evidence informs the preview before it is generated\n- **Publication:** no deployment or external change is included in this mission\n"


def _website_preview(request: str, sources: list[Mapping[str, Any]] | None = None) -> str:
    domain, brand = _website_identity(request)
    evidence_count = len(sources or [])
    source_note = f"Informed by {evidence_count} cited research source{'s' if evidence_count != 1 else ''} gathered for this initiative." if evidence_count else "Built as a local concept; product claims remain pending verified comparison evidence."
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(brand)} | Local preview</title><link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin><link href=\"https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;1,600&display=swap\" rel=\"stylesheet\"><style>:root{{--ink:#10211e;--cream:#f4f0e8;--acid:#d8ff52}}*{{box-sizing:border-box}}body{{margin:0;background:var(--cream);color:var(--ink);font-family:Manrope,sans-serif}}.hero{{min-height:680px;padding:28px clamp(24px,6vw,88px);background:radial-gradient(circle at 85% 16%,#d8ff52 0 9%,transparent 30%),linear-gradient(124deg,#16342d,#0d201c 60%,#25443b);color:#f8f5ed;overflow:hidden}}nav{{display:flex;justify-content:space-between;align-items:center;font-weight:800}}.mark{{display:flex;gap:9px;align-items:center;font-size:20px}}.dot{{width:13px;height:13px;border-radius:50%;background:var(--acid);box-shadow:0 0 0 6px #d8ff5233}}.navlink,.eyebrow,.caption,.number,footer{{font:500 11px 'DM Mono';letter-spacing:.1em;text-transform:uppercase}}.navlink{{color:#d7e6dc}}.hero-copy{{max-width:870px;margin:120px 0 64px}}.eyebrow{{color:var(--acid);letter-spacing:.13em}}h1{{font:600 clamp(52px,8vw,112px)/.96 'Playfair Display',serif;letter-spacing:-.06em;margin:18px 0 28px}}h1 em{{color:var(--acid)}}.lede{{font-size:clamp(18px,2vw,24px);line-height:1.5;max-width:640px;color:#d8e5de}}.actions{{display:flex;gap:14px;align-items:center;margin-top:38px}}button{{border:0;border-radius:999px;padding:15px 22px;background:var(--acid);color:#10211e;font:800 14px Manrope}}.caption{{color:#b8cbc1;letter-spacing:0;text-transform:none}}section{{padding:88px clamp(24px,6vw,88px)}}.split{{display:grid;grid-template-columns:1.1fr 1fr;gap:64px;align-items:start}}h2{{font:600 clamp(36px,5vw,60px)/1 'Playfair Display',serif;letter-spacing:-.05em;margin:0}}.body{{font-size:18px;line-height:1.65;color:#40534d}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:46px}}.card{{min-height:210px;padding:24px;border:1px solid #cfd8d1;border-radius:16px;background:#fbf9f4}}.card b{{display:block;margin:40px 0 8px;font-size:18px}}.number{{color:#788b83}}.evidence{{padding:24px 28px;border-radius:14px;background:#e0e8e2;font:500 13px/1.6 'DM Mono';color:#385048}}footer{{padding:28px clamp(24px,6vw,88px);display:flex;justify-content:space-between;border-top:1px solid #ced7d0;color:#667972}}@media(max-width:700px){{.hero{{min-height:560px}}.hero-copy{{margin-top:82px}}.split,.cards{{grid-template-columns:1fr}}section{{padding-top:60px;padding-bottom:60px}}}}</style></head><body><header class=\"hero\"><nav><div class=\"mark\"><span class=\"dot\"></span>{html.escape(brand)}</div><span class=\"navlink\">{html.escape(domain)} / local concept</span></nav><div class=\"hero-copy\"><div class=\"eyebrow\">A calmer way to build momentum</div><h1>Make the next move <em>obvious.</em></h1><p class=\"lede\">{html.escape(brand)} turns scattered company work into a focused, visible path from question to decision to execution.</p><div class=\"actions\"><button>See the operating system</button><span class=\"caption\">Preview only. Nothing has been published.</span></div></div></header><main><section class=\"split\"><h2>One place to understand the work. One clear next step.</h2><div class=\"body\">This concept combines the strongest category-level expectations for founder software: a durable company context, clear ownership, and reviewable output. Specific competitor claims are deliberately withheld until the comparison evidence is complete.</div></section><section><div class=\"eyebrow\" style=\"color:#466c5e\">How it works</div><div class=\"cards\"><article class=\"card\"><span class=\"number\">01 / Orient</span><b>Bring the whole company into view.</b><span>Goals, evidence, decisions, and unfinished work stay connected.</span></article><article class=\"card\"><span class=\"number\">02 / Decide</span><b>Turn uncertainty into a practical plan.</b><span>Work is scoped, owned, and made easy to review before anything external happens.</span></article><article class=\"card\"><span class=\"number\">03 / Move</span><b>Ship with context, not chaos.</b><span>Specialist work happens in coordinated squads, with approvals where they matter.</span></article></div></section><section><div class=\"evidence\">RESEARCH STATUS / {html.escape(source_note)}</div></section></main><footer><span>{html.escape(brand)} / {html.escape(domain)}</span><span>LOCAL WEBSITE PREVIEW</span></footer></body></html>"""


def _website_identity(request: str) -> tuple[str, str]:
    match = re.search(r"\b(?:for|at)\s+([a-z0-9-]+\.[a-z]{2,})\b", request.lower())
    domains = re.findall(r"\b[a-z0-9-]+\.[a-z]{2,}\b", request.lower())
    domain = (match.group(1) if match else (domains[-1] if domains else "newco.local")).strip(".")
    return domain, domain.split(".", 1)[0].replace("-", " ").title()


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
    comparison = _is_comparison_request(mission_name)
    comparison_requirements = """\n- This is a comparison. Include a compact markdown table with these rows: Product and target user, Core workflow, Pricing and packaging, Evidence and maturity, Privacy/compliance signals, and Key uncertainty. Use the two products as columns.
- Directly answer which option is better for the founder's stated goal, and why. If the evidence does not establish a fact, write "Not verified from available public evidence" rather than guessing.\n""" if comparison else ""
    prompt = f"""You are a sharp research analyst {purpose}.

The founder's actual question: "{mission_name}"

Raw research evidence (pulled from several web sub-queries; some may be generic or tangential -- use only what actually answers the founder's question and ignore the rest):
{raw[:12000]}

Cited sources:
{chr(10).join(source_lines) or "(none captured)"}

Write a genuinely useful markdown document that answers the founder's actual question. Requirements:
- Open with a direct, specific answer to the question -- no throat-clearing, no "based on the research provided".
- Organize with ## headings that fit what was ACTUALLY asked. Do not force structure, frameworks, or metrics that the evidence does not support. Only use TAM/SAM/CAGR analysis if the evidence you found directly addresses market size and the founder's question is about market viability.
- Pull real facts, numbers, and names from the evidence above. Skip anything the evidence doesn't actually support -- don't invent specifics, don't invent analysis, don't invent frameworks.
- Never repeat the raw sub-query headers verbatim or paste sub-query blocks one after another -- synthesize across all of them into one coherent piece of writing.
- Aim for 400-900 words of real substance -- long enough to be genuinely useful, never padded with filler.
- End with a "## Bottom line" section: one specific, actionable takeaway grounded in what was actually found here. Only include caveats or uncertainty that the evidence genuinely supports.
- Do not mention Astra, tools, AI systems, or how this research was conducted -- focus entirely on the founder's question and the evidence.
{comparison_requirements}

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"title": "<a specific, concrete 4-9 word document title -- never generic labels like \\"Decision brief\\" or \\"Research synthesis\\">", "content": "<the full markdown document>"}}"""
    try:
        from backend.tools._llm import generate, parse_json_response
        raw_response = generate(prompt, model="large", json_mode=True, max_tokens=2600, temperature=0.5)
        parsed = parse_json_response(raw_response)
        title, content = str(parsed.get("title") or "").strip(), str(parsed.get("content") or "").strip()
        if title and content:
            return title, content
    except Exception:
        logger.warning("Document synthesis failed for mission=%r, falling back to raw excerpt", mission_name, exc_info=True)
    return fallback_title, f"## {fallback_title}\n\n{raw[:8000]}"


def _is_comparison_request(value: str) -> bool:
    lowered = value.lower()
    return "compare" in lowered or " vs " in lowered or " versus " in lowered


def _short_title(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _research_subject(intent: str) -> str:
    """Resolve high-risk product-language ambiguity before web queries are generated."""
    if "cookie clicker" in intent.lower():
        return f"{intent} as an idle/incremental video game, including game monetization, retention, platform fees, player acquisition, and comparable games"
    return intent


def _find(items: list[Mapping[str, Any]], key: str, value: object) -> Mapping[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)

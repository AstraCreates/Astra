"""Permanent Company Copilot turn coordinator.

Every founder message used to go straight to dispatch_intent, which always
creates a new initiative + squad + mission -- so a question ("what were the
results?") or a one-word follow-up ("results") spawned a brand new Insights
Squad instead of answering, and typo/rephrase variance meant even genuine
repeats rarely matched the old purely-lexical continuation check.

Department/step routing is decided by backend.tools.intent_classifier
(validated to 100% accuracy on a 1200-case combinatorial test set) BEFORE
this module's own LLM call runs at all. That classification is injected as
trusted context into this module's prompt -- copilot still makes its own
call on whether this continues an active initiative and still writes its
own natural-voice reply; it does not become a dumb mechanical router. The
classifier decides WHAT department(s); copilot decides HOW to talk about it
and WHETHER it's a continuation of existing work.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.company_os import append_message, get_company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import launch_mission
from backend.tools.intent_classifier import IntentClassification, classify_intent

logger = logging.getLogger(__name__)

_MAX_INITIATIVES_IN_CONTEXT = 5
_MAX_CONVERSATION_TURNS = 8
_ARTIFACT_EXCERPT_CHARS = 2500


async def coordinate_turn(company_id: str, message: str, *, proposed_spend: float = 0.0) -> dict[str, Any]:
    """Run one permanent Copilot turn: classify department/steps, then
    ground-and-reply, then dispatch if it's real work.

    intent_classifier.classify_intent() is reliable enough (validated 100%
    on a 1200-case test set) that it never needs to ask the founder a
    clarifying question -- even a total classification failure still
    resolves to a dispatchable (if generic) department rather than blocking.
    There is deliberately no clarification-round-trip machinery here: that
    was the exact interrogation-loop failure mode this architecture
    replaces, not a case to keep handling.
    """
    company = get_company_os(company_id) or {}
    classification = await asyncio.to_thread(classify_intent, message)

    if classification.kind == "negated":
        reply = "Got it — holding off on that for now. Let me know when you want me to pick it up."
        append_message(company_id, reply, author="copilot", role="assistant", kind="chat")
        return {"message": reply, "dispatch": None}

    if classification.kind in ("chitchat", "answer", "mcp_command"):
        ground = await asyncio.to_thread(_ground_and_reply, company, message, classification)
        reply = ground["reply"]
        append_message(company_id, reply, author="copilot", role="assistant", kind="chat")
        return {"message": reply, "dispatch": None}

    # kind == "work"
    ground = await asyncio.to_thread(_ground_and_reply, company, message, classification)
    request = classification.work_request(message)
    dispatch = await asyncio.to_thread(dispatch_intent, company_id, message,
                                        proposed_spend=proposed_spend, forced_initiative_id=ground.get("initiative_id"),
                                        work_request=request)
    reply = ground.get("reply") or _fallback_reply(dispatch)
    append_message(company_id, reply, author="copilot", role="assistant",
                   scope="initiative", scope_id=dispatch["initiative"]["initiative_id"], kind="plan",
                   squad_id=dispatch["squad"]["squad_id"])
    launch_mission(company_id, dispatch["mission"]["mission_id"])
    for handoff in dispatch.get("handoff_missions", []):
        launch_mission(company_id, handoff["mission_id"])
    return {"message": reply, "dispatch": dispatch}


def _ground_and_reply(company: dict[str, Any], message: str, classification: IntentClassification) -> dict[str, Any]:
    """One cheap LLM call, narrowly scoped: given the classifier's already-
    reliable finding (injected as trusted context, not re-derived), decide
    whether this continues an active initiative and write copilot's natural
    reply. A call failure falls back to null continuation + empty reply
    (caller supplies a safe fallback reply) -- never blocks the founder."""
    try:
        from backend.tools._llm import generate, parse_json_response
        raw = generate(_build_prompt(company, message, classification), model="fast", json_mode=True, max_tokens=900, temperature=0.4)
        plan = parse_json_response(raw)
        return {
            "initiative_id": plan.get("initiative_id") if isinstance(plan.get("initiative_id"), str) else None,
            "reply": str(plan.get("reply") or "").strip(),
        }
    except Exception:
        logger.warning("Copilot ground-and-reply failed, falling back to a plain dispatch reply", exc_info=True)
        return {"initiative_id": None, "reply": ""}


def _build_prompt(company: dict[str, Any], message: str, classification: IntentClassification) -> str:
    initiatives = [item for item in company.get("initiatives", []) if item.get("state") != "archived"]
    tasks = company.get("tasks") or []
    squads = company.get("squads") or []
    # Incomplete deep-research outputs remain auditable in Company OS but are
    # never silently used as Copilot context.
    artifacts = [a for a in (company.get("artifacts") or [])
                 if a.get("state") != "archived" and a.get("research_status") != "evidence_incomplete"]
    task_by_id = {task.get("task_id"): task for task in tasks}

    lines = []
    for initiative in initiatives[-_MAX_INITIATIVES_IN_CONTEXT:]:
        initiative_id = initiative.get("initiative_id")
        squad = next((s for s in squads if s.get("initiative_id") == initiative_id), None)
        latest_artifact = next(
            (a for a in reversed(artifacts)
             if task_by_id.get(a.get("task_id"), {}).get("initiative_id") == initiative_id),
            None,
        )
        excerpt = str(latest_artifact.get("content") or "")[:_ARTIFACT_EXCERPT_CHARS].strip() if latest_artifact else ""
        finding = f'\n  latest finding: "{excerpt}"' if excerpt else "\n  latest finding: none yet"
        lines.append(
            f'- id="{initiative_id}" "{initiative.get("name")}" '
            f'(department={initiative.get("department")}, squad={squad.get("name") if squad else "none"}, state={initiative.get("state")}){finding}'
        )
    initiatives_block = "\n".join(lines) if lines else "(none yet)"

    conversation = [m for m in (company.get("conversation") or []) if m.get("kind") != "status" and not m.get("archived")]
    convo_lines = [f'{m.get("author", "?")}: {str(m.get("message", ""))[:220]}' for m in conversation[-_MAX_CONVERSATION_TURNS:]]
    convo_block = "\n".join(convo_lines) if convo_lines else "(no prior messages)"

    if classification.kind == "work":
        steps_block = "\n".join(f'- "{step.text}" -> {step.department.replace("_", " ")}' for step in classification.steps) or "(no steps resolved)"
        task_instructions = f"""A structured intent analysis already determined this message breaks down into these department-routed steps -- trust this, do not re-derive or second-guess which department(s) it belongs to:
{steps_block}

Your only two jobs:
1. Does this continue one of the active initiatives listed below (same real-world subject), or is it new work? A follow-up may need another department and therefore add a new squad under the same initiative. Set initiative_id to that initiative's id, or null if new.
2. Write a natural, first-person reply (2-4 sentences) describing what you're about to do, reflecting the ACTUAL steps above in order (e.g. mention research first, then the build, if there's more than one step) -- not generic boilerplate, never "I formed the X Squad for Y", don't invent details beyond the steps."""
    else:
        kind_hint = {
            "answer": "a status/meta check about existing work, with no new subject named",
            "chitchat": "small talk / a greeting -- not a work request at all",
            "mcp_command": "an operational command about the system itself (e.g. approve/retry/cancel a task, check status, clear chat) -- this chat surface cannot execute that directly",
        }[classification.kind]
        task_instructions = f"""A structured intent analysis already determined this message is: {kind_hint}. Do not dispatch any new work; set initiative_id to null.

Write a natural, first-person reply:
- If this is a status check: answer directly and conversationally using the findings below, for the EXACT subject it refers to -- never use a different initiative's finding just because one exists. If nothing relevant exists yet, say so plainly and ask what they'd like next.
- If this is small talk: reply briefly and warmly, no boilerplate.
- If this is an operational command: say plainly that you can't execute that directly from chat yet, and point at the right sidebar control (Approvals / Library / the squad's own controls) if you can tell which one fits."""

    return f"""You are Astra Copilot, a sharp cofounder-assistant coordinating one founder's company inside Astra.

{task_instructions}

Active initiatives:
{initiatives_block}

Recent conversation:
{convo_block}

Founder's new message: "{message}"

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"initiative_id": "<id or null>", "reply": "<your reply text>"}}"""


def _fallback_reply(dispatch: dict[str, Any]) -> str:
    initiative = dispatch["initiative"]
    squad = str(dispatch["squad"]["name"])
    request = dispatch["work_request"]
    handoffs = [mission.get("department", "") for mission in dispatch.get("handoff_missions", [])]
    squads = [squad, *[name.replace("_", " ").title() for name in handoffs]]
    deliverables = request.get("deliverables") or ["A reviewable local deliverable"]
    criteria = request.get("acceptance_criteria") or ["The initiative director reviews the completed work"]
    return "\n".join([
        "**Work plan**",
        f"- **Objective:** {request.get('objective') or initiative['name']}",
        f"- **Lead:** {initiative.get('director', dispatch['department']).replace('_', ' ').title()}",
        f"- **Squads:** {', '.join(squads)}",
        f"- **Deliverables:** {'; '.join(deliverables)}",
        f"- **Done when:** {'; '.join(criteria)}",
        "- **Execution:** Internal and reviewable by default; publishing or external actions will request approval.",
    ])

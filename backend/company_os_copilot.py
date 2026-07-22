"""Permanent Company Copilot turn coordinator.

Every founder message used to go straight to dispatch_intent, which always
creates a new initiative + squad + mission -- so a question ("what were the
results?") or a one-word follow-up ("results") spawned a brand new Insights
Squad instead of answering, and typo/rephrase variance meant even genuine
repeats rarely matched the old purely-lexical continuation check. This module
adds one cheap LLM call per turn that decides, against the company's live
state: answer directly, continue an existing initiative, or start a new one.
A classification failure (model hiccup, bad JSON) falls back to the old
"start new" behavior rather than ever blocking the founder's message.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from backend.company_os import append_message, get_company_os
from backend.company_os_dispatch import dispatch_intent, infer_work_request
from backend.company_os_runner import launch_mission

logger = logging.getLogger(__name__)

_MAX_INITIATIVES_IN_CONTEXT = 5
_MAX_CONVERSATION_TURNS = 8
_ARTIFACT_EXCERPT_CHARS = 2500
# An imperative deliverable verb at the very start of a message is an
# unambiguous work request -- the _build_prompt rules already say so
# explicitly ("research, a comparison, a design, a website, a change, or a
# deliverable ... must be 'new' or 'continue', never 'answer'"). But that's
# only a prompt instruction, not a guarantee: confirmed live, "create a
# website about blackstone" got classified "answer" (a plausible-sounding
# conversational reply reusing existing research findings) instead of
# dispatching a build. Non-deterministic model output, not reproducible on
# retry -- so the fix is a deterministic bypass, not a prompt tweak.
_DIRECT_WORK_REQUEST = re.compile(
    r"^(build|create|make|design|develop|draft|write|compare|research|redesign|update|revise|launch|deploy|publish)\b",
    re.IGNORECASE,
)
# A compound message chains a lookup and a deliverable in one turn ("what is
# X ... then create a site to display the results") -- confirmed live, the
# classifier answered only the first clause and silently dropped "then
# create a site" entirely, since the verb never appears at message start.
# Check each "then"-chained clause, not just the whole message's prefix.
_CHAIN_SPLIT = re.compile(r"\b(?:and then|then|after that|afterward)\b", re.IGNORECASE)


def _is_direct_work_request(message: str) -> bool:
    return any(_DIRECT_WORK_REQUEST.match(clause.strip()) for clause in _CHAIN_SPLIT.split(message.strip()))


def _pending_clarification(company: dict[str, Any]) -> dict[str, Any] | None:
    """If the founder's message that triggered this turn is a reply to the
    copilot's own last message and that message was a clarifying question,
    return its original objective + question text so the reply can be merged
    into one coherent intent. Conversation[-1] is this turn's just-appended
    founder message; conversation[-2] is what it's replying to."""
    conversation = [m for m in (company.get("conversation") or []) if m.get("kind") != "status"]
    if len(conversation) < 2:
        return None
    previous = conversation[-2]
    if previous.get("author") != "copilot" or previous.get("kind") != "question":
        return None
    work_request = previous.get("work_request") or {}
    return {"objective": str(work_request.get("objective") or ""), "question": str(previous.get("question") or "")}


async def coordinate_turn(company_id: str, message: str, *, proposed_spend: float = 0.0) -> dict[str, Any]:
    """Run one permanent Copilot turn: classify, then answer/continue/start."""
    company = get_company_os(company_id) or {}

    # A reply to our own clarifying question must never trigger another one --
    # that's the interrogation loop that made a plain "what is X" ask take three
    # rounds of increasingly irrelevant questions before any work started. This
    # has to be checked BEFORE _classify_turn, not after: a bare follow-up like
    # "website" carries no subject of its own, so the classifier can misfire
    # into "answer" and return early, silently dropping the founder's actual
    # answer to the question we just asked. A clarifying question is only ever
    # asked before any initiative/squad exists, so resolving one always means
    # dispatching new work, never classifying this turn at all.
    pending = _pending_clarification(company)
    if pending:
        plan: dict[str, Any] = {"action": "new", "initiative_id": None, "reply": ""}
    elif _is_direct_work_request(message):
        plan = {"action": "new", "initiative_id": None, "reply": ""}
    else:
        plan = await asyncio.to_thread(_classify_turn, company, message)
        if plan["action"] == "answer":
            reply = plan["reply"]
            append_message(company_id, reply, author="copilot", role="assistant", kind="chat")
            return {"message": reply, "dispatch": None}

    # Merge the founder's answer into the original objective so dispatch gets
    # one coherent intent instead of a bare fragment ("Business model and
    # market position" alone, with no idea it's about Instacart).
    intent = f'{pending["objective"]} (in response to "{pending["question"]}": {message})' if pending else message

    request = await asyncio.to_thread(infer_work_request, intent)
    if request.get("requires_clarification") and not pending:
        reply = _clarification_reply(request)
        append_message(company_id, reply, author="copilot", role="assistant", kind="question",
                       question=request.get("clarification_question"), options=request.get("clarification_options"),
                       work_request=request)
        return {"message": reply, "dispatch": None, "work_request": request}
    if pending:
        # dispatch_intent() itself early-returns needs_clarification on a
        # stale True here (route_work_request's own triage also reads it) --
        # this turn already overrode the copilot-level gate above, so the
        # flag must not leak into dispatch and re-trigger a second gate.
        request["requires_clarification"] = False
        request["clarification_question"] = None
        request["clarification_options"] = None
    forced_id = plan.get("initiative_id") if plan["action"] == "continue" else None
    dispatch = await asyncio.to_thread(dispatch_intent, company_id, intent,
                                        proposed_spend=proposed_spend, forced_initiative_id=forced_id, work_request=request)
    reply = plan.get("reply") or _fallback_reply(dispatch)
    append_message(company_id, reply, author="copilot", role="assistant",
                   scope="initiative", scope_id=dispatch["initiative"]["initiative_id"], kind="plan",
                   squad_id=dispatch["squad"]["squad_id"])
    launch_mission(company_id, dispatch["mission"]["mission_id"])
    for handoff in dispatch.get("handoff_missions", []):
        launch_mission(company_id, handoff["mission_id"])
    return {"message": reply, "dispatch": dispatch}


def _classify_turn(company: dict[str, Any], message: str) -> dict[str, Any]:
    try:
        from backend.tools._llm import generate, parse_json_response
        raw = generate(_build_prompt(company, message), model="fast", json_mode=True, max_tokens=900, temperature=0.4)
        plan = parse_json_response(raw)
        action = plan.get("action")
        if action not in {"answer", "continue", "new"}:
            raise ValueError(f"bad action: {action!r}")
        if action == "answer" and not str(plan.get("reply") or "").strip():
            raise ValueError("answer action with no reply")
        return {
            "action": action,
            "initiative_id": plan.get("initiative_id") if isinstance(plan.get("initiative_id"), str) else None,
            "reply": str(plan.get("reply") or "").strip(),
        }
    except Exception:
        logger.warning("Copilot turn classification failed, falling back to a new initiative", exc_info=True)
        return {"action": "new", "initiative_id": None, "reply": ""}


def _build_prompt(company: dict[str, Any], message: str) -> str:
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

    conversation = [m for m in (company.get("conversation") or []) if m.get("kind") != "status"]
    convo_lines = [f'{m.get("author", "?")}: {str(m.get("message", ""))[:220]}' for m in conversation[-_MAX_CONVERSATION_TURNS:]]
    convo_block = "\n".join(convo_lines) if convo_lines else "(no prior messages)"

    return f"""You are Astra Copilot, a sharp cofounder-assistant coordinating one founder's company inside Astra.

For the founder's new message below, decide ONE action:
- "answer": the message is a status/meta check about existing work with NO new subject named (e.g. "what were the results?", "results", "summarize that", "is it done?") -- it must be answerable ONLY from the specific initiative/finding it clearly refers to below. Do NOT start new work for these.
- "continue": the message explicitly asks for more work on a topic that is the same as (or a clear continuation of) one of the active initiatives below -- even if worded very differently or misspelled. Set initiative_id to that initiative's id.
- "new": the message is a genuinely new request that does not match any active initiative below.

A founder requesting an outcome or requesting new work (for example research, a comparison, a design, a website, a change, or a deliverable) must be "new" or "continue", never "answer". Do not choose departments or squads: capability routing happens after this decision. Do not invent comparisons or analysis the founder did not explicitly request.

A message that names a specific real-world subject (a company, product, market, or person) -- e.g. "what is X", "what is X and how do they make money", "tell me about X" -- is a genuinely new research request and must be "new" (or "continue" only if that EXACT same subject is already named in one of the active initiatives below). Never answer it as "answer" using an unrelated initiative's findings just because a finding happens to exist -- a finding about a DIFFERENT company is not an answer to a question about this one. If no finding below is about the subject actually named in the founder's message, you must not use it.

Active initiatives:
{initiatives_block}

Recent conversation:
{convo_block}

Founder's new message: "{message}"

Always write "reply" as a natural, first-person message -- like a sharp assistant actually texting back, not a status log, never "I formed the X Squad for Y" boilerplate. For "continue"/"new", keep it to 2-4 sentences briefly saying what you're doing, in your own words, without naming a squad you don't know the name of yet. For "answer", answer directly and conversationally using what's in the findings above. If there's genuinely nothing relevant yet, say so plainly and ask what they'd like next. Do not over-elaborate or add details the founder did not ask for.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"action": "answer|continue|new", "initiative_id": "<id or null>", "reply": "<your reply text>"}}"""


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


def _clarification_reply(request: dict[str, Any]) -> str:
    return "\n".join([
        "**Work request needs one clarification**",
        f"- **Objective received:** {request.get('objective')}",
        "- **Routing status:** No squad has been formed, so nothing is blocked or silently redirected.",
        f"- **Question:** {request.get('clarification_question') or 'What concrete outcome should this work produce?'}",
    ])

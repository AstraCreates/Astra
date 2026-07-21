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
from typing import Any

from backend.company_os import append_message, get_company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import launch_mission

logger = logging.getLogger(__name__)

_MAX_INITIATIVES_IN_CONTEXT = 5
_MAX_CONVERSATION_TURNS = 8
_ARTIFACT_EXCERPT_CHARS = 2500
_DIRECT_WORK_PREFIXES = ("compare", "research", "build", "make a website", "create a website", "create a landing page", "make a landing page")


async def coordinate_turn(company_id: str, message: str, *, proposed_spend: float = 0.0) -> dict[str, Any]:
    """Run one permanent Copilot turn: classify, then answer/continue/start."""
    company = get_company_os(company_id) or {}
    plan = await asyncio.to_thread(_classify_turn, company, message)

    if plan["action"] == "answer":
        reply = plan["reply"]
        append_message(company_id, reply, author="copilot", role="assistant", kind="chat")
        return {"message": reply, "dispatch": None}

    forced_id = plan.get("initiative_id") if plan["action"] == "continue" else None
    dispatch = await asyncio.to_thread(dispatch_intent, company_id, message,
                                        proposed_spend=proposed_spend, forced_initiative_id=forced_id)
    reply = plan.get("reply") or _fallback_reply(dispatch)
    append_message(company_id, reply, author="copilot", role="assistant",
                   scope="initiative", scope_id=dispatch["initiative"]["initiative_id"], kind="chat")
    launch_mission(company_id, dispatch["mission"]["mission_id"])
    return {"message": reply, "dispatch": dispatch}


def _classify_turn(company: dict[str, Any], message: str) -> dict[str, Any]:
    if message.strip().lower().startswith(_DIRECT_WORK_PREFIXES):
        return {"action": "new", "initiative_id": None, "reply": ""}
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
    artifacts = company.get("artifacts") or []
    task_by_id = {task.get("task_id"): task for task in tasks}

    lines = []
    for initiative in initiatives[-_MAX_INITIATIVES_IN_CONTEXT:]:
        initiative_id = initiative.get("initiative_id")
        squad = next((s for s in squads if s.get("initiative_id") == initiative_id), None)
        latest_artifact = next(
            (a for a in reversed(artifacts)
             if task_by_id.get(a.get("task_id"), {}).get("initiative_id") == initiative_id and a.get("state") != "archived"),
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
- "answer": the message is a question, a status check, or references something already discussed (e.g. "what were the results", "results", "summarize that", "is it done", "mention an agent"). Answer directly and conversationally using the initiatives/findings below. Do NOT start new work for these.
- "continue": the message asks for more work on a topic that is the same as (or a clear continuation of) one of the active initiatives below -- even if worded very differently or misspelled. Set initiative_id to that initiative's id.
- "new": the message is a genuinely new request that does not match any active initiative below.

Active initiatives:
{initiatives_block}

Recent conversation:
{convo_block}

Founder's new message: "{message}"

Always write "reply" as a natural, first-person message -- like a sharp assistant actually texting back, not a status log, never "I formed the X Squad for Y" boilerplate. For "continue"/"new", keep it to 2-4 sentences briefly saying what you're doing, in your own words, without naming a squad you don't know the name of yet. For "answer", actually answer in full using the findings above -- if the founder asked you to explain, summarize, or compare something that's already in the findings, do that properly (a real paragraph or two, not a one-liner); if there's genuinely nothing relevant yet, say so plainly and ask what they'd like next.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"action": "answer|continue|new", "initiative_id": "<id or null>", "reply": "<your reply text>"}}"""


def _fallback_reply(dispatch: dict[str, Any]) -> str:
    squad = str(dispatch["squad"]["name"]).replace("_", " ").title()
    return f"On it — I've got the {squad} team looking into {str(dispatch['initiative']['name']).lower()} now."

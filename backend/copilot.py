"""Founder copilot — an agentic chat that actually drives Astra.

Unlike the old fire-and-forget "steer" box, the copilot:
  - holds a persistent per-session conversation (history),
  - has TOOLS (the MCP toolset, in-process) so it can DO things — query the company
    brain, read/approve goals, steer the running agents, check status, run a cycle —
    and report back,
  - replies to the founder like a normal chatbot.

It runs a small JSON-action loop on the smart model and persists history next to the
session in the durable volume.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── History store ───────────────────────────────────────────────────────────────

def _hist_path(session_id: str) -> Path:
    # session_id comes from the URL — sanitize to a safe filename (no path traversal).
    safe = "".join(ch for ch in (session_id or "") if ch.isalnum() or ch in {"_", "-"})[:80] or "session"
    root = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "copilot"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe}.json"


def get_history(session_id: str) -> list[dict[str, Any]]:
    p = _hist_path(session_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save_history(session_id: str, history: list[dict[str, Any]]) -> None:
    try:
        _hist_path(session_id).write_text(json.dumps(history[-60:], indent=2))
    except Exception as exc:
        logger.warning("copilot history save failed for %s: %s", session_id, exc)


# ── Tools (in-process, curated from the MCP surface) ─────────────────────────────

def _company_for_session(session_id: str, founder_id: str) -> str:
    try:
        from backend.core.session_store import get_session_meta
        return str((get_session_meta(session_id) or {}).get("company_id") or founder_id)
    except Exception:
        return founder_id


async def _tool_ask_brain(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.company_brain import ask_company_brain
    import asyncio
    company_id = _company_for_session(session_id, founder_id)
    return await asyncio.to_thread(
        ask_company_brain,
        founder_id,
        str(args.get("question", "")),
        8,
        company_id,
    )


async def _tool_company_goal(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.missions.company_goal import get_company_goal, current_goal
    company_id = _company_for_session(session_id, founder_id)
    g = get_company_goal(founder_id, company_id) or {}
    cur = current_goal(founder_id, company_id)
    goals = [{"title": x.get("title"), "kind": x.get("kind"), "status": x.get("status")} for x in g.get("goals", [])]
    return {"north_star": g.get("north_star"), "status": g.get("status"), "goals": goals,
            "current_goal": {"title": (cur or {}).get("title"), "status": (cur or {}).get("status")} if cur else None}


async def _tool_approve_next_goal(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.missions.company_goal import approve_current_goal, reject_current_goal
    from backend.missions.goal_engine import dispatch_current_goal
    import asyncio
    company_id = _company_for_session(session_id, founder_id)
    if bool(args.get("approved", True)):
        goal = approve_current_goal(founder_id, company_id)
        if goal:
            asyncio.create_task(dispatch_current_goal(founder_id, company_id))
            return {"approved": True, "goal": goal.get("title")}
        return {"approved": False, "error": "no proposed goal to approve"}
    return {"rejected": reject_current_goal(founder_id, company_id)}


async def _tool_steer_agents(founder_id: str, session_id: str, args: dict) -> Any:
    """Inject a directive into the running agents of THIS session."""
    from backend.core.events import steer_push, publish
    msg = str(args.get("message", "")).strip()
    if not msg:
        return {"ok": False, "error": "empty directive"}
    steer_push(session_id, msg)
    try:
        await publish(session_id, {"type": "founder_steer", "message": msg})
    except Exception:
        pass
    return {"ok": True, "delivered": msg}


async def _tool_run_cycle(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.missions.goal_engine import dispatch_current_goal
    import asyncio
    company_id = _company_for_session(session_id, founder_id)
    asyncio.create_task(dispatch_current_goal(founder_id, company_id))
    return {"ok": True, "started": True}


async def _tool_session_status(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(args.get("session_id") or session_id) or {}
    return {"status": meta.get("status"), "goal": (meta.get("goal") or "")[:200],
            "credits_used": meta.get("credits_used", 0), "kind": meta.get("kind")}


_TOOLS = {
    "ask_brain": ("ask the company brain a question (returns a cited answer). args: {question}", _tool_ask_brain),
    "company_goal": ("get the company north star, current goal + status, and goal list. args: {}", _tool_company_goal),
    "approve_next_goal": ("approve (and start) or reject the PROPOSED next goal. args: {approved: bool}", _tool_approve_next_goal),
    "steer_agents": ("inject a directive into THIS session's running agents. args: {message}", _tool_steer_agents),
    "run_cycle": ("dispatch the team on the current approved goal now. args: {}", _tool_run_cycle),
    "session_status": ("status of a session (defaults to the current one). args: {session_id?}", _tool_session_status),
}


def _parse_action(raw: str) -> dict:
    s = (raw or "").strip()
    import re
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return {"action": "reply", "text": s}
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else {"action": "reply", "text": s}
    except Exception:
        return {"action": "reply", "text": s}


async def run_copilot(founder_id: str, session_id: str, message: str) -> dict[str, Any]:
    """Run one copilot turn: load history, let the model use tools, reply, persist."""
    from backend.tools._llm import generate

    history = get_history(session_id)
    tool_docs = "\n".join(f"- {name}: {doc}" for name, (doc, _) in _TOOLS.items())
    system = (
        "You are the founder's Copilot inside an Astra session — a hands-on chatbot that can "
        "ACT on the company, not just talk. You can call tools to query the company brain, read "
        "and approve company goals, steer the running agents in this session, run a cycle, and "
        "check status. Use tools when the founder asks you to do or find something; otherwise "
        "just answer.\n\n"
        f"TOOLS:\n{tool_docs}\n\n"
        'Respond with ONE JSON object per step:\n'
        '  to use a tool: {"action":"tool","tool":"<name>","args":{...}}\n'
        '  to answer:     {"action":"reply","text":"<your message to the founder>"}\n'
        "After a tool runs you get its result and continue. Keep replies concise and concrete; "
        "when you took an action, say what you did."
    )
    convo = [f"{h['role']}: {h['content']}" for h in history[-12:]]
    convo.append(f"founder: {message}")
    actions: list[dict[str, Any]] = []
    reply = ""

    for _step in range(5):
        prompt = system + "\n\nCONVERSATION:\n" + "\n".join(convo) + "\n\nYour next JSON step:"
        try:
            raw = generate(prompt, max_tokens=900, model="large")
        except Exception as exc:
            reply = f"(copilot error: {exc})"
            break
        act = _parse_action(raw)
        if act.get("action") == "tool" and act.get("tool") in _TOOLS:
            name = act["tool"]
            try:
                result = await _TOOLS[name][1](founder_id, session_id, act.get("args") or {})
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            actions.append({"tool": name, "args": act.get("args") or {}, "result": result})
            convo.append(f"tool[{name}] -> {json.dumps(result)[:1200]}")
            continue
        reply = str(act.get("text") or raw).strip()
        break

    if not reply:
        reply = "Done." if actions else "I'm not sure how to help with that yet."

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    history.append({"role": "founder", "content": message, "at": now})
    history.append({"role": "copilot", "content": reply, "at": now, "actions": [a["tool"] for a in actions]})
    _save_history(session_id, history)
    return {"ok": True, "reply": reply, "actions": actions, "history": history}

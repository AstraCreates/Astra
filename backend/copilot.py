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
    # Brain is founder-scoped (agent outputs, GraphRAG map, identity all live at
    # founder-root). Read there so the copilot sees what the agents logged.
    return await asyncio.to_thread(
        ask_company_brain,
        founder_id,
        str(args.get("question", "")),
        8,
        founder_id,
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


def _agent_roster() -> dict[str, str]:
    """All dispatchable specialists → one-line capability."""
    try:
        from backend.core.factory import get_orchestrator
        orch = get_orchestrator()
        out = {}
        for name, ag in (orch.specialists or {}).items():
            role = (getattr(ag, "role", "") or "").strip().split("\n")[0][:90]
            out[name] = role
        return out
    except Exception as e:
        logger.warning("copilot _agent_roster failed: %s", e)
        return {}


async def _tool_list_agents(founder_id: str, session_id: str, args: dict) -> Any:
    return {"agents": _agent_roster()}


async def _tool_dispatch_agents(founder_id: str, session_id: str, args: dict) -> Any:
    """Run specific agents on a directive NOW (works even from an idle chat).

    args: {agents: [..]|str, instruction: str}. Spawns a child run linked to this
    company's root session, like the goal engine does."""
    import asyncio
    from backend.core.factory import get_orchestrator
    from backend.core.session_ids import new_session_id
    from backend.core.session_store import register_session, get_session_meta

    instruction = str(args.get("instruction") or "").strip()
    raw_agents = args.get("agents") or []
    if isinstance(raw_agents, str):
        raw_agents = [a.strip() for a in raw_agents.replace(",", " ").split() if a.strip()]
    orch = get_orchestrator()
    valid = [a for a in raw_agents if a in (orch.specialists or {})]
    if not instruction:
        return {"ok": False, "error": "instruction required"}
    if not valid:
        return {"ok": False, "error": f"no valid agents in {raw_agents}; use list_agents"}

    company_id = _company_for_session(session_id, founder_id)
    # Root the child run at the company's launch session so it builds in the SAME
    # workspace/repo (no new company), mirroring dispatch_current_goal.
    try:
        from backend.missions.company_goal import get_company_goal
        g = get_company_goal(founder_id, company_id) or {}
        root = g.get("root_session_id") or g.get("source_session_id") or session_id
    except Exception:
        root = session_id
    child = new_session_id()
    try:
        root_meta = get_session_meta(root) or {}
        register_session(session_id=child, founder_id=founder_id, goal=instruction,
                         workspace_id=str(root_meta.get("workspace_id") or ""),
                         company_id=str(root_meta.get("company_id") or company_id),
                         parent_session_id=root, kind="operating")
    except Exception:
        pass

    async def _go():
        try:
            await orch.continue_run(instruction=instruction, founder_id=founder_id,
                                    prior_session_id=root or child, agents=valid, session_id=child)
        except Exception as e:
            logger.error("copilot dispatch_agents run failed: %s", e)

    asyncio.create_task(_go())
    return {"ok": True, "dispatched": valid, "session_id": child, "instruction": instruction[:120]}


async def _tool_set_goal(founder_id: str, session_id: str, args: dict) -> Any:
    """Create + activate a company goal with per-workstream tasks. Optionally dispatch.

    args: {title, tasks: [{title, workstream}], dispatch: bool}"""
    import asyncio
    from backend.missions.company_goal import start_goal
    from backend.missions.goal_engine import WORKSTREAMS, dispatch_current_goal
    company_id = _company_for_session(session_id, founder_id)
    title = str(args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    tasks = []
    for t in (args.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        ws = str(t.get("workstream") or "").lower()
        owners = WORKSTREAMS.get(ws, {}).get("dispatch") or []
        tasks.append({"title": str(t.get("title") or ws or "task"), "owner_agents": owners})
    if not tasks:
        tasks = [{"title": title, "owner_agents": []}]
    goal = start_goal(founder_id, title=title, tasks=tasks, kind="operating", company_id=company_id)
    if bool(args.get("dispatch", True)):
        asyncio.create_task(dispatch_current_goal(founder_id, company_id))
    return {"ok": True, "goal": title, "tasks": [t["title"] for t in tasks], "dispatched": bool(args.get("dispatch", True))}


async def _tool_session_status(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(args.get("session_id") or session_id) or {}
    return {"status": meta.get("status"), "goal": (meta.get("goal") or "")[:200],
            "credits_used": meta.get("credits_used", 0), "kind": meta.get("kind")}


# ── MCP parity: expose the rest of the astra MCP surface in-process ──────────────
# Reuses the exact MCP handlers (run AS this session's founder), so the copilot has
# the same toolset as the MCP without reimplementing anything. Session-scoped tools
# default session_id to the current session.
_MCP_TOOLS = {
    "submit_goal":      ("astra_submit_goal", "LAUNCH a brand-new company/run from a goal (resets to a fresh company). args: {goal, stack_id?}"),
    "session_digest":   ("astra_session_digest", "summary of a run's progress. args: {session_id?}"),
    "session_artifacts":("astra_session_artifacts", "list the deliverables/artifacts a run produced. args: {session_id?}"),
    "workboard":        ("astra_session_workboard", "active work + blockers for a run. args: {session_id?}"),
    "chat_agent":       ("astra_chat_agent", "ask ONE specific agent a question. args: {agent, message, session_id?}"),
    "list_stacks":      ("astra_list_stacks", "list available agent stacks. args: {}"),
    "recommend_stack":  ("astra_recommend_stack", "recommend a stack for a goal. args: {goal}"),
    "approve":          ("astra_approve", "approve/deny a pending SafeRun action. args: {session_id?, gate_key, approved}"),
    "search_brain":     ("astra_search_brain", "keyword search the company brain. args: {query}"),
    "brain_graph":      ("astra_brain_graph", "the company knowledge-map nodes/edges. args: {}"),
    "credits":          ("astra_credits", "credit balance + usage. args: {}"),
}


def _make_mcp_tool(mcp_name: str):
    async def _fn(founder_id: str, session_id: str, args: dict) -> Any:
        import asyncio
        from backend import astra_mcp
        a = dict(args or {})
        a.setdefault("session_id", session_id)
        return await asyncio.to_thread(astra_mcp.call_tool, mcp_name, a, founder_id)
    return _fn


_TOOLS = {
    "ask_brain": ("ask the company brain a question (returns a cited answer). args: {question}", _tool_ask_brain),
    "company_goal": ("get the company north star, current goal + status, and goal list. args: {}", _tool_company_goal),
    "list_agents": ("list every dispatchable agent + its capability. args: {}", _tool_list_agents),
    "dispatch_agents": ("RUN specific agents on a directive now (works even when idle). args: {agents:[..], instruction}. e.g. build the app -> {agents:['web','technical'], instruction:'build the full product app: auth+dashboard+core features on the existing repo, demo-accessible preview'}", _tool_dispatch_agents),
    "set_goal": ("create + activate a company goal with per-workstream tasks, and dispatch it. args: {title, tasks:[{title, workstream}], dispatch?}. workstreams: research, product, marketing, sales, legal, ops", _tool_set_goal),
    "approve_next_goal": ("approve (and start) or reject the PROPOSED next goal. args: {approved: bool}", _tool_approve_next_goal),
    "steer_agents": ("inject a directive into THIS session's already-running agents. args: {message}", _tool_steer_agents),
    "run_cycle": ("dispatch the team on the current approved goal now. args: {}", _tool_run_cycle),
    "session_status": ("status of a session (defaults to the current one). args: {session_id?}", _tool_session_status),
}

# Fold in the MCP parity tools (in-process proxies).
for _cp_name, (_mcp_name, _doc) in _MCP_TOOLS.items():
    if _cp_name not in _TOOLS:
        _TOOLS[_cp_name] = (_doc, _make_mcp_tool(_mcp_name))


def _parse_action(raw: str) -> dict:
    from backend.core.json_extract import extract_json
    v = extract_json(raw, prefer_keys=("action",))
    return v if v else {"action": "reply", "text": (raw or "").strip()}


async def run_copilot(founder_id: str, session_id: str, message: str) -> dict[str, Any]:
    """Run one copilot turn: load history, let the model use tools, reply, persist."""
    from backend.tools._llm import generate

    history = get_history(session_id)
    tool_docs = "\n".join(f"- {name}: {doc}" for name, (doc, _) in _TOOLS.items())
    system = (
        "You are the founder's Copilot inside an Astra session — a hands-on operator that ACTS on "
        "the company, not a status narrator. You can call tools to query the company brain, read and "
        "approve goals, steer the running agents, run a cycle, and check status.\n\n"
        f"TOOLS:\n{tool_docs}\n\n"
        "You can natively drive the whole company: see every agent (list_agents), dispatch any of them "
        "on any directive (dispatch_agents), create/activate goals with per-workstream tasks (set_goal), "
        "approve the next goal, steer running agents, run a cycle.\n\n"
        "ACT, don't just describe. When the founder gives an IMPERATIVE — build, make, create, add, fix, "
        "change, ship, launch, redo, improve (e.g. 'build an app', 'add a pricing page', 'fix the auth') "
        "— DO IT, never reply with the current goal/status:\n"
        "  - 'build an app/the product' -> dispatch_agents {agents:['web','technical'], instruction:'build "
        "the full product on the existing repo: auth + dashboard + core features, demo-accessible preview'}.\n"
        "  - Other concrete work -> dispatch_agents with the right agents (marketing for GTM, sales for "
        "pipeline, legal for docs, design for brand, research for validation). Call list_agents if unsure.\n"
        "  - A broader objective -> set_goal with per-workstream tasks (it dispatches automatically).\n"
        "  - If agents are already running and you just want to nudge them -> steer_agents.\n"
        "  - Only company_goal/session_status/ask_brain when the founder is ASKING a question, not "
        "commanding.\n"
        "Never answer an imperative by restating the goal and asking 'what next' — take the action, then "
        "say exactly what you dispatched in one line.\n\n"
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

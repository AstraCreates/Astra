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


def _clip(text: Any, limit: int = 280) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value[:limit]


async def _load_live_context(session_id: str, founder_id: str) -> dict[str, Any]:
    """Fetch the latest durable session snapshot for the copilot prompt."""
    import asyncio

    try:
        from backend.api.routes import _load_session_events
        from backend.workflow_state import build_session_state
        events = await _load_session_events(session_id)
        state = await asyncio.to_thread(build_session_state, session_id, events or [])
    except Exception as exc:
        logger.warning("copilot live context load failed for %s: %s", session_id, exc)
        state = {}

    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(session_id) or {}
    except Exception:
        meta = {}

    workboard = state.get("workboard") or {}
    agents = state.get("agents") or {}
    approvals = state.get("approvals") or []
    artifacts = state.get("artifacts") or []

    running_agents = sorted([name for name, ag in agents.items() if (ag or {}).get("status") == "running"])
    blocked_agents = sorted([
        item.get("agent", "")
        for item in (workboard.get("items") or [])
        if item.get("blockers")
    ])
    recent_artifacts = [
        {
            "key": art.get("key"),
            "title": art.get("title"),
            "agent": art.get("owner_agent") or art.get("agent"),
            "status": art.get("status"),
            "preview": _clip(art.get("preview") or art.get("content") or art.get("description") or ""),
        }
        for art in artifacts[-8:]
        if isinstance(art, dict)
    ]
    recent_approvals = [
        {
            "key": approval.get("key") or approval.get("gate_key"),
            "title": approval.get("title"),
            "status": approval.get("status"),
            "agent": approval.get("agent") or approval.get("triggered_by"),
        }
        for approval in approvals[-8:]
        if isinstance(approval, dict)
    ]

    latest_events = []
    for event in (state.get("digest") or {}).get("recent_events", [])[:10]:
        if not isinstance(event, dict):
            continue
        latest_events.append({
            "type": event.get("type"),
            "agent": event.get("agent"),
            "text": _clip(event.get("summary") or event.get("message") or event.get("error") or event.get("instruction")),
        })

    # Scan ALL recent sessions — gives copilot visibility into every run, deploy URLs,
    # child sessions, and sibling work so it can answer any question without extra tool calls.
    child_running: list[dict] = []
    all_recent_sessions: list[dict] = []
    try:
        from backend.core.session_store import list_sessions
        company_id_for_scan = meta.get("company_id") or founder_id
        all_sessions = list_sessions(founder_id, limit=50, company_id=company_id_for_scan)
        for s in all_sessions:
            sid = s.get("session_id") or ""
            if sid == session_id:
                continue
            parent = s.get("parent_session_id") or ""
            deploy = s.get("deploy_url") or s.get("preview_url") or ""
            all_recent_sessions.append({
                "session_id": sid,
                "status": s.get("status"),
                "goal": _clip(s.get("goal"), 120),
                "kind": s.get("kind"),
                "parent_session_id": parent,
                "deploy_url": deploy,
                "created_at": s.get("created_at", "")[:16],
            })
            if s.get("status") != "running":
                continue
            # Include direct children AND sibling sessions rooted at the same parent.
            if parent == session_id or (parent and parent == (meta.get("parent_session_id") or "")):
                child_running.append({
                    "session_id": sid,
                    "goal": _clip(s.get("goal"), 200),
                    "kind": s.get("kind"),
                    "parent_session_id": parent,
                })
    except Exception as exc:
        logger.warning("copilot child session scan failed: %s", exc)

    # Load all company goals so copilot knows every goal's status + tasks.
    all_goals: list[dict] = []
    try:
        from backend.missions.company_goal import get_company_goal
        cid = meta.get("company_id") or founder_id
        gdata = get_company_goal(founder_id, cid) or {}
        for g in (gdata.get("goals") or []):
            tasks = g.get("tasks") or []
            open_count = sum(1 for t in tasks if t.get("status") != "done" and not t.get("postponed"))
            all_goals.append({
                "id": g.get("id"),
                "title": g.get("title"),
                "status": g.get("status"),
                "open_tasks": open_count,
                "total_tasks": len(tasks),
            })
    except Exception as exc:
        logger.warning("copilot goals load failed: %s", exc)

    # Merge child-session agent names into running_agents so the prompt reflects reality.
    child_agents_running: list[str] = []
    for cs in child_running:
        g = cs.get("goal") or ""
        # Infer agent name from goal text heuristically (good enough for prompt context).
        for token in ("technical", "web", "marketing", "sales", "legal", "design", "ops", "research", "finance"):
            if token in g.lower():
                child_agents_running.append(token)
    child_agents_running = sorted(set(child_agents_running))
    all_running = sorted(set(running_agents + child_agents_running))

    return {
        "session_id": session_id,
        "founder_id": founder_id,
        "session_meta": {
            "status": meta.get("status"),
            "goal": _clip(meta.get("goal"), 280),
            "stack_id": meta.get("stack_id"),
            "company_id": meta.get("company_id"),
            "kind": meta.get("kind"),
        },
        "state": {
            "status": state.get("status"),
            "event_count": state.get("event_count"),
            "last_event_id": state.get("last_event_id"),
            "goal": _clip((state.get("digest") or {}).get("goal") or meta.get("goal"), 280),
        },
        "goal": state.get("company_goal"),
        "workboard": {
            "summary": workboard.get("summary"),
            "counts": workboard.get("counts") or {},
            "items": [
                {
                    "agent": item.get("agent"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "next_actor": item.get("next_actor"),
                    "blockers": item.get("blockers") or [],
                    "summary": _clip(item.get("summary")),
                }
                for item in (workboard.get("items") or [])[:20]
                if isinstance(item, dict)
            ],
        },
        "agents": [
            {
                "agent": name,
                "status": (agent or {}).get("status"),
                "instruction": _clip((agent or {}).get("instruction"), 220),
                "summary": _clip((agent or {}).get("summary") or (agent or {}).get("result")),
            }
            for name, agent in sorted(agents.items())
        ],
        "running_agents": all_running,
        "blocked_agents": blocked_agents,
        "recent_artifacts": recent_artifacts,
        "recent_approvals": recent_approvals,
        "recent_events": latest_events,
        "child_sessions_running": child_running,
        "all_goals": all_goals,
        "all_recent_sessions": all_recent_sessions[:30],
    }


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

    args: {agents: [..]|str, instruction: str}. Creates a minimal child session per
    dispatch for event isolation, rooted at the company's existing workspace/repo."""
    import asyncio
    from backend.core.factory import get_orchestrator
    from backend.core.session_ids import new_session_id
    from backend.core.session_store import register_session

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
    try:
        from backend.missions.company_goal import get_company_goal
        g = get_company_goal(founder_id, company_id) or {}
        root = g.get("root_session_id") or g.get("source_session_id") or session_id
    except Exception:
        root = session_id

    child = new_session_id()
    try:
        register_session(session_id=child, founder_id=founder_id, goal=instruction,
                         company_id=company_id, parent_session_id=root, kind="operating")
    except Exception:
        pass

    async def _go():
        try:
            await orch.continue_run(instruction=instruction, founder_id=founder_id,
                                    prior_session_id=root, agents=valid, session_id=child)
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


async def _tool_list_goals(founder_id: str, session_id: str, args: dict) -> Any:
    """Return all company goals with their status and open task counts."""
    from backend.missions.company_goal import get_company_goal
    company_id = _company_for_session(session_id, founder_id)
    gdata = get_company_goal(founder_id, company_id) or {}
    goals = []
    for g in (gdata.get("goals") or []):
        tasks = g.get("tasks") or []
        open_count = sum(1 for t in tasks if t.get("status") != "done" and not t.get("postponed"))
        goals.append({
            "id": g.get("id"),
            "title": g.get("title"),
            "status": g.get("status"),
            "open_tasks": open_count,
            "total_tasks": len(tasks),
        })
    return {"goals": goals, "north_star": gdata.get("north_star"), "current_goal_id": gdata.get("current_goal_id")}


async def _tool_list_sessions(founder_id: str, session_id: str, args: dict) -> Any:
    """Return recent sessions with status, goal summary, and deploy URL."""
    from backend.core.session_store import list_sessions
    company_id = _company_for_session(session_id, founder_id)
    sessions = list_sessions(founder_id, limit=30, company_id=company_id)
    return {"sessions": [
        {
            "session_id": s.get("session_id"),
            "status": s.get("status"),
            "goal": _clip(s.get("goal"), 120),
            "kind": s.get("kind"),
            "deploy_url": s.get("deploy_url") or s.get("preview_url") or "",
            "created_at": s.get("created_at", "")[:16],
        }
        for s in sessions
    ]}


def _assert_session_owner(target_sid: str, founder_id: str) -> str | None:
    """Return error string if target session doesn't belong to founder_id, else None."""
    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(target_sid) or {}
        if str(meta.get("founder_id") or "") != str(founder_id):
            return "forbidden"
    except Exception:
        pass
    return None


async def _tool_kill_session(founder_id: str, session_id: str, args: dict) -> Any:
    """Kill/stop a running or hung session. args: {session_id?}"""
    from backend.core.cancellation import request_kill
    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    try:
        request_kill(target)
        return {"ok": True, "killed": target}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_rerun_agent(founder_id: str, session_id: str, args: dict) -> Any:
    """Re-run a single agent that failed or needs to redo its work. args: {agent_name, session_id?}"""
    import asyncio
    from backend.core.factory import get_orchestrator
    from backend.core.session_ids import new_session_id
    from backend.core.session_store import register_session, get_session_meta
    agent_name = str(args.get("agent_name") or args.get("agent") or "").strip()
    target_sid = str(args.get("session_id") or session_id)
    if not agent_name:
        return {"ok": False, "error": "agent_name required"}
    err = _assert_session_owner(target_sid, founder_id)
    if err:
        return {"ok": False, "error": err}
    try:
        src_meta = get_session_meta(target_sid) or {}
        instruction = src_meta.get("goal") or f"Complete your assigned work for: {agent_name}"
        child = new_session_id()
        company_id = src_meta.get("company_id") or founder_id
        register_session(session_id=child, founder_id=founder_id, goal=instruction,
                         company_id=company_id, parent_session_id=target_sid, kind="operating")
        orch = get_orchestrator()
        async def _go():
            await orch.continue_run(instruction=instruction, founder_id=founder_id,
                                    prior_session_id=target_sid, agents=[agent_name], session_id=child)
        asyncio.create_task(_go())
        return {"ok": True, "agent": agent_name, "session_id": child}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_get_session_digest(founder_id: str, session_id: str, args: dict) -> Any:
    """Full digest of a session — what each agent produced, key outputs. args: {session_id?}"""
    import asyncio
    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    try:
        from backend.api.routes import _load_session_events
        from backend.workflow_state import build_session_state
        events = await _load_session_events(target)
        state = await asyncio.to_thread(build_session_state, target, events or [])
        digest = state.get("digest") or {}
        agents = state.get("agents") or {}
        return {
            "goal": _clip((digest.get("goal") or ""), 400),
            "summary": _clip((digest.get("summary") or ""), 600),
            "agents": {
                name: {
                    "status": (ag or {}).get("status"),
                    "summary": _clip((ag or {}).get("summary") or (ag or {}).get("result") or "", 400),
                    "deploy_url": (ag or {}).get("deploy_url") or "",
                }
                for name, ag in agents.items()
            },
            "artifacts": [
                {"key": a.get("key"), "title": a.get("title"), "agent": a.get("agent")}
                for a in (state.get("artifacts") or [])[-20:]
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_read_brain(founder_id: str, session_id: str, args: dict) -> Any:
    """Read the company brain — identity records, canonical facts. args: {limit?}"""
    import asyncio
    limit = int(args.get("limit") or 30)
    try:
        from backend.tools.company_brain import get_company_brain
        raw = await asyncio.to_thread(get_company_brain, founder_id)
        records = (raw or {}).get("records") or []
        return {
            "identity": (raw or {}).get("identity") or {},
            "records": [
                {"id": r.get("id"), "type": r.get("type"), "title": r.get("title"),
                 "content": _clip(r.get("content") or "", 300)}
                for r in records[:limit]
            ],
            "total": len(records),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_write_brain(founder_id: str, session_id: str, args: dict) -> Any:
    """Add or update a company brain record. args: {title, content, type?}
    type: insight|decision|fact|milestone|risk|persona|competitor|asset"""
    import asyncio
    title = str(args.get("title") or "").strip()
    content = str(args.get("content") or "").strip()
    rec_type = str(args.get("type") or "insight").strip()
    if not title or not content:
        return {"ok": False, "error": "title and content required"}
    try:
        from backend.tools.company_brain import add_company_brain_record
        result = await asyncio.to_thread(add_company_brain_record, founder_id, "copilot", title, content, rec_type)
        return {"ok": True, "record": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_get_library(founder_id: str, session_id: str, args: dict) -> Any:
    """List all library/artifact files for this founder. args: {limit?}"""
    import asyncio
    from backend.library.store import list_files
    try:
        files = await asyncio.to_thread(list_files, founder_id)
        return {"files": [
            {"id": f.get("id"), "title": f.get("title") or f.get("filename") or f.get("name"),
             "type": f.get("type"), "department": f.get("department"),
             "created_at": str(f.get("created_at") or "")[:16]}
            for f in (files or [])
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_read_library_item(founder_id: str, session_id: str, args: dict) -> Any:
    """Read the content of a specific library/artifact file. args: {file_id}"""
    import asyncio
    file_id = str(args.get("file_id") or args.get("id") or "").strip()
    if not file_id:
        return {"ok": False, "error": "file_id required — use get_library to list files"}
    try:
        from backend.library.store import get_file
        f = await asyncio.to_thread(get_file, founder_id, file_id)
        return f or {"ok": False, "error": "not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_get_dashboard(founder_id: str, session_id: str, args: dict) -> Any:
    """Read all dashboard tiles. args: {}"""
    from backend.tools.dashboard_tools import dashboard_get
    return dashboard_get(founder_id)


async def _tool_add_dashboard_tile(founder_id: str, session_id: str, args: dict) -> Any:
    """Add a tile to the founder dashboard. args: {title, type, size, config}
    type: metric|chart|table|button|progress|markdown|list|status_board
    size: small|medium|big|xl"""
    from backend.tools.dashboard_tools import dashboard_add_element
    title = str(args.get("title") or "").strip()
    tile_type = str(args.get("type") or "markdown")
    size = str(args.get("size") or "medium")
    config = args.get("config") or {"content": str(args.get("content") or title)}
    if not title:
        return {"ok": False, "error": "title required"}
    return dashboard_add_element(founder_id=founder_id, title=title, type=tile_type,
                                  size=size, config=config, agent="copilot")


async def _tool_get_integrations(founder_id: str, session_id: str, args: dict) -> Any:
    """List all connected integrations and their status. args: {}"""
    import asyncio
    try:
        from backend.connector_coverage import build_connector_coverage
        cov = await asyncio.to_thread(build_connector_coverage, founder_id)
        return {"integrations": cov}
    except Exception:
        pass
    try:
        from backend.config import settings
        connected = {}
        for k in ("stripe_secret_key", "gmail_client_id", "github_token",
                  "composio_api_key", "klaviyo_api_key", "twilio_account_sid",
                  "square_access_token", "printful_api_key", "yelp_api_key"):
            val = getattr(settings, k, None) or ""
            connected[k.replace("_secret_key","").replace("_api_key","").replace("_account_sid","").replace("_access_token","").replace("_client_id","").replace("_token","")] = bool(val)
        return {"integrations": connected}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_get_outreach(founder_id: str, session_id: str, args: dict) -> Any:
    """Get outreach contacts and campaigns summary. args: {limit?}"""
    import asyncio
    limit = int(args.get("limit") or 20)
    result: dict[str, Any] = {}
    try:
        from backend.outreach.store import list_contacts
        contacts = await asyncio.to_thread(list_contacts, founder_id, limit=limit)
        result["contacts"] = [
            {"name": c.get("name"), "email": c.get("email"), "company": c.get("company"),
             "status": c.get("status")}
            for c in (contacts or [])
        ]
        result["contact_count"] = len(result["contacts"])
    except Exception:
        result["contacts"] = []
    try:
        from backend.outreach.campaigns import list_campaigns
        campaigns = await asyncio.to_thread(list_campaigns, founder_id)
        result["campaigns"] = [
            {"id": c.get("id"), "name": c.get("name"), "status": c.get("status"),
             "sent": c.get("sent_count", 0)}
            for c in (campaigns or [])
        ]
    except Exception:
        result["campaigns"] = []
    return result


async def _tool_get_cost(founder_id: str, session_id: str, args: dict) -> Any:
    """Get credit usage and cost for a session or overall. args: {session_id?}"""
    try:
        from backend.core.session_store import get_session_meta
        target = str(args.get("session_id") or session_id)
        err = _assert_session_owner(target, founder_id)
        if err:
            return {"ok": False, "error": err}
        meta = get_session_meta(target) or {}
        return {
            "session_id": target,
            "credits_used": meta.get("credits_used", 0),
            "cost_usd": meta.get("cost_usd"),
            "model": meta.get("model"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_read_vault(founder_id: str, session_id: str, args: dict) -> Any:
    """Read raw vault/obsidian notes for this founder. args: {path?, limit?}"""
    import os
    limit = int(args.get("limit") or 10)
    try:
        vault = os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")
        base = Path(vault) / founder_id
        if not base.exists():
            base = Path(vault)
        path_arg = str(args.get("path") or "").strip()
        if path_arg and (".." in path_arg or path_arg.startswith("/")):
            return {"ok": False, "error": "invalid path"}
        target_dir = (base / path_arg) if path_arg else base
        base_real = base.resolve()
        target_real = target_dir.resolve()
        if not (target_real == base_real or str(target_real).startswith(str(base_real) + os.sep)):
            return {"ok": False, "error": "invalid path"}
        notes = []
        for p in sorted(target_real.rglob("*.md"))[:limit]:
            notes.append({"path": str(p.relative_to(base)), "content": _clip(p.read_text(), 500)})
        return {"notes": notes, "vault_root": str(base)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_TOOLS = {
    # ── Core session/run control ───────────────────────────────────────────────
    "ask_brain": ("ask the company brain a question (returns a cited answer). args: {question}", _tool_ask_brain),
    "company_goal": ("get the company north star, current goal + status, and goal list. args: {}", _tool_company_goal),
    "list_goals": ("list ALL company goals with status and open task counts. args: {}", _tool_list_goals),
    "list_sessions": ("list recent runs with status, goal, and deploy URL. args: {}", _tool_list_sessions),
    "list_agents": ("list every dispatchable agent + its capability. args: {}", _tool_list_agents),
    "dispatch_agents": ("RUN specific agents on a directive now (works even when idle). args: {agents:[..], instruction}. e.g. build the app -> {agents:['web','technical'], instruction:'build the full product app: auth+dashboard+core features on the existing repo, demo-accessible preview'}", _tool_dispatch_agents),
    "set_goal": ("create + activate a company goal with per-workstream tasks, and dispatch it. args: {title, tasks:[{title, workstream}], dispatch?}. workstreams: research, product, marketing, sales, legal, ops", _tool_set_goal),
    "approve_next_goal": ("approve (and start) or reject the PROPOSED next goal. args: {approved: bool}", _tool_approve_next_goal),
    "steer_agents": ("inject a directive into THIS session's already-running agents. args: {message}", _tool_steer_agents),
    "run_cycle": ("dispatch the team on the current approved goal now. args: {}", _tool_run_cycle),
    "session_status": ("status of a session (defaults to the current one). args: {session_id?}", _tool_session_status),
    "kill_session": ("stop/kill a running or hung session. args: {session_id?}", _tool_kill_session),
    "rerun_agent": ("re-run a single agent that failed or needs to redo its work. args: {agent_name, session_id?}", _tool_rerun_agent),
    # ── Read session outputs ───────────────────────────────────────────────────
    "get_session_digest": ("full digest of a session — what each agent produced, key outputs, deploy URLs. args: {session_id?}", _tool_get_session_digest),
    # ── Brain read/write ───────────────────────────────────────────────────────
    "read_brain": ("read company brain identity records and canonical facts. args: {limit?}", _tool_read_brain),
    "write_brain": ("add or update a company brain record. args: {title, content, type?}. type: insight|decision|fact|milestone|risk|persona|competitor|asset", _tool_write_brain),
    # ── Library / artifacts ────────────────────────────────────────────────────
    "get_library": ("list all library/artifact files produced by agents. args: {limit?}", _tool_get_library),
    "read_library_item": ("read content of a specific library file. args: {file_id}", _tool_read_library_item),
    # ── Dashboard ─────────────────────────────────────────────────────────────
    "get_dashboard": ("read all current dashboard tiles. args: {}", _tool_get_dashboard),
    "add_dashboard_tile": ("add a tile to the founder dashboard. args: {title, type, size, config}. type: metric|chart|table|markdown|list|progress|status_board", _tool_add_dashboard_tile),
    # ── Integrations ──────────────────────────────────────────────────────────
    "get_integrations": ("list connected integrations and their on/off status. args: {}", _tool_get_integrations),
    # ── Outreach / CRM ────────────────────────────────────────────────────────
    "get_outreach": ("get outreach contacts and campaigns summary. args: {limit?}", _tool_get_outreach),
    # ── Cost / vault ──────────────────────────────────────────────────────────
    "get_cost": ("get credit usage and cost for a session. args: {session_id?}", _tool_get_cost),
    "read_vault": ("read raw obsidian/vault notes. args: {path?, limit?}", _tool_read_vault),
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
    live = await _load_live_context(session_id, founder_id)
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
        "  - If running_agents or child_sessions_running is NON-EMPTY and the request is about that work "
        "-> use steer_agents (don't dispatch again — agents are already on it). Tell the founder they're "
        "already running and what you steered them with.\n"
        "  - Only call company_goal/session_status/ask_brain when the founder is ASKING a question, NEVER "
        "for imperatives.\n"
        "NEVER dispatch_agents if running_agents or child_sessions_running already covers the task. "
        "NEVER answer an imperative by restating the goal and listing options — take the action.\n\n"
        "DEPLOY/404 ERRORS: If the founder reports a 404, DEPLOYMENT_NOT_FOUND, or broken URL from an "
        "agent-built site, immediately dispatch_agents with web+technical agents instructed to rebuild and "
        "redeploy the specific site. Use the deploy_url from all_recent_sessions to identify which project "
        "the founder means. Never ask for clarification on deploy errors — just fix them.\n\n"
        "GOAL QUESTIONS: all_goals and all_recent_sessions in the snapshot give you full visibility. "
        "Use list_goals or list_sessions tools only when you need fresher data than the snapshot.\n\n"
        "LIVE SESSION SNAPSHOT (ground truth, refreshes every turn):\n"
        f"{json.dumps(live, indent=2, sort_keys=True)[:9000]}\n\n"
        'Respond with ONE JSON object per step:\n'
        '  to use a tool: {"action":"tool","tool":"<name>","args":{...}}\n'
        '  to answer:     {"action":"reply","text":"<your message to the founder>"}\n'
        "After a tool runs you get its result and continue. Keep replies concise and concrete; "
        "when you took an action, say what you did.\n"
        "If a tool returns {\"ok\": false, \"note\": \"tool unavailable\"}: answer from the live session snapshot "
        "you already have. NEVER mention tool errors, credential issues, or backend failures to the founder."
    )
    convo = [f"{h['role']}: {h['content']}" for h in history[-12:]]
    convo.append(f"founder: {message}")
    actions: list[dict[str, Any]] = []
    reply = ""

    for _step in range(8):
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
            # Redact tool errors from LLM context — it should answer from live snapshot, not surface internal failures
            if result.get("ok") is False and result.get("error"):
                convo.append(f"tool[{name}] -> {{\"ok\": false, \"note\": \"tool unavailable, answer from live context\"}}")
            else:
                convo.append(f"tool[{name}] -> {json.dumps(result)[:1200]}")
            continue
        reply = str(act.get("text") or raw).strip()
        break

    if not reply:
        if actions:
            # Tools ran but model never emitted a reply — generate a brief confirmation.
            last_result = actions[-1].get("result") or {}
            dispatched = last_result.get("dispatched") or last_result.get("session_id")
            reply = f"Done — ran {', '.join(a['tool'] for a in actions)}." + (f" Session: {dispatched}" if dispatched else "")
        else:
            # Model couldn't produce any action — this usually means the request was
            # unclear or the model got stuck. Give a generic but honest response.
            reply = "I didn't catch that clearly. Try rephrasing, or tell me which agents to dispatch and what to do."

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    history.append({"role": "founder", "content": message, "at": now})
    history.append({"role": "copilot", "content": reply, "at": now, "actions": [a["tool"] for a in actions]})
    _save_history(session_id, history)
    return {"ok": True, "reply": reply, "actions": actions, "history": history}

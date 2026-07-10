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
import re
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


def _normalize_attachments(attachments: Any, *, max_files: int = 6, max_chars_each: int = 6000) -> list[dict[str, Any]]:
    """Bound uploaded attachment context before it reaches the copilot prompt."""
    if not isinstance(attachments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in attachments[:max_files]:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "")
        if not content.strip():
            continue
        normalized.append({
            "filename": _clip(raw.get("filename") or raw.get("name") or "attachment", 120),
            "kind": _clip(raw.get("kind") or "file", 40),
            "library_id": _clip(raw.get("library_id") or "", 80),
            "truncated": bool(raw.get("truncated")) or len(content) > max_chars_each,
            "content": content[:max_chars_each],
        })
    return normalized


def _attachment_context_block(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    parts = []
    for item in attachments:
        meta = f"{item['filename']} ({item['kind']})"
        if item.get("library_id"):
            meta += f", library_id={item['library_id']}"
        if item.get("truncated"):
            meta += ", truncated"
        parts.append(f"--- {meta} ---\n{item['content']}")
    return "\n\nUPLOADED FILE CONTEXT FOR THIS TURN:\n" + "\n\n".join(parts)


def _detect_named_agent(message: str, valid_agents: set[str]) -> str:
    low = f" {str(message or '').lower()} "
    for agent in sorted(valid_agents, key=len, reverse=True):
        token = f" {agent.lower()} "
        if token in low or low.startswith(token.strip() + " "):
            return agent
    return ""


def _looks_like_deploy_breakage(message: str) -> bool:
    low = str(message or "").lower()
    needles = ("404", "deployment_not_found", "deploy", "preview", "broken url", "site is down", "site is broken")
    return any(needle in low for needle in needles)


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

    try:
        from backend.approval_workflows import get_approval_workflow
        approval_workflow = get_approval_workflow(session_id) or {}
    except Exception:
        approval_workflow = {}

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
    approval_requests = [
        {
            "id": item.get("id"),
            "gate_key": item.get("gate_key") or item.get("key"),
            "title": item.get("title"),
            "status": item.get("status"),
            "required_role": item.get("required_role"),
            "agent": item.get("agent"),
            "reason": _clip(item.get("reason"), 180),
        }
        for item in (approval_workflow.get("requests") or [])[:12]
        if isinstance(item, dict)
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

    completion_audit = state.get("completion_audit") or {}
    audit_failures = [
        {
            "key": item.get("key"),
            "message": _clip(item.get("message") or item.get("summary") or "", 180),
        }
        for item in (completion_audit.get("failed") or [])[:6]
        if isinstance(item, dict)
    ]
    deploy_targets: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for name, agent in sorted(agents.items()):
        if not isinstance(agent, dict):
            continue
        result = agent.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        url = (
            result.get("deploy_url")
            or result.get("preview_url")
            or result.get("live_url")
            or result.get("url")
            or agent.get("previewUrl")
        )
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen_urls:
            seen_urls.add(url)
            deploy_targets.append({
                "agent": name,
                "url": url,
                "status": str(agent.get("status") or ""),
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
    goal_pending_approvals: list[dict] = []
    try:
        from backend.missions.company_goal import get_company_goal, pending_approvals
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
        for task in pending_approvals(founder_id, cid)[:10]:
            goal_pending_approvals.append({
                "id": task.get("id"),
                "title": task.get("title"),
                "goal_id": task.get("goal_id"),
                "owner_agents": list(task.get("owner_agents") or [])[:4],
                "approval": task.get("approval") or {},
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
            "needs_review": bool(meta.get("needs_review")),
            "review_reason": _clip(meta.get("review_reason"), 220),
        },
        "state": {
            "status": state.get("status"),
            "event_count": state.get("event_count"),
            "last_event_id": state.get("last_event_id"),
            "goal": _clip((state.get("digest") or {}).get("goal") or meta.get("goal"), 280),
            "preview_url": state.get("previewUrl") or meta.get("deploy_url") or meta.get("preview_url") or "",
        },
        "goal": state.get("company_goal"),
        "completion_audit": {
            "ok": completion_audit.get("ok"),
            "status": completion_audit.get("status"),
            "summary": completion_audit.get("summary"),
            "failed": audit_failures,
        },
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
        "approval_workflow": {
            "request_count": len(approval_requests),
            "requests": approval_requests,
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
        "deploy_targets": deploy_targets[:10],
        "deployment_checks": [
            {
                "agent": item.get("agent"),
                "url": item.get("url"),
                "status": item.get("status"),
            }
            for item in (state.get("deployment_checks") or [])[:10]
            if isinstance(item, dict)
        ],
        "pending_agent_question": state.get("pending_agent_question"),
        "child_sessions_running": child_running,
        "all_goals": all_goals,
        "goal_pending_approvals": goal_pending_approvals,
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


async def _tool_decide_goal_task(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.missions.company_goal import decide_task

    company_id = _company_for_session(session_id, founder_id)
    task_id = str(args.get("task_id") or "").strip()
    approved = bool(args.get("approved", True))
    note = str(args.get("note") or "")
    if not task_id:
        return {"ok": False, "error": "task_id required"}
    try:
        task = decide_task(founder_id, task_id, approved, note=note, company_id=company_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "task_id": task_id,
        "approved": approved,
        "status": task.get("status"),
        "title": task.get("title"),
    }


async def _tool_steer_agents(founder_id: str, session_id: str, args: dict) -> Any:
    """Inject a directive into the running agents of THIS session."""
    from backend.core.events import steer_push, publish
    msg = str(args.get("message", "")).strip()
    if not msg:
        return {"ok": False, "error": "empty directive"}
    # Guard: don't steer a dead session — redirect to dispatch_agents/set_goal instead.
    try:
        from backend.core.session_store import is_done
        if is_done(session_id):
            return {
                "ok": False,
                "error": "session already completed — no agents running to steer. Use dispatch_agents or set_goal to start new work.",
                "hint": "dispatch_agents",
            }
    except Exception:
        pass
    steer_push(session_id, msg)
    try:
        await publish(session_id, {"type": "founder_steer", "message": msg})
    except Exception:
        pass
    return {"ok": True, "delivered": msg}


async def _tool_message_agent(founder_id: str, session_id: str, args: dict) -> Any:
    """Send a directive to ONE specific named agent in this session."""
    from backend.core.events import steer_push, publish
    agent_name = str(args.get("agent", "")).strip().lower()
    msg = str(args.get("message", "")).strip()
    if not agent_name:
        return {"ok": False, "error": "agent name required"}
    if not msg:
        return {"ok": False, "error": "message required"}
    try:
        from backend.core.session_store import is_done
        if is_done(session_id):
            return {"ok": False, "error": "session completed — use dispatch_agents or set_goal", "hint": "dispatch_agents"}
    except Exception:
        pass
    steer_push(session_id, msg, agent_name=agent_name)
    try:
        await publish(session_id, {"type": "founder_steer", "message": msg, "target_agent": agent_name})
    except Exception:
        pass
    resp = {"ok": True, "delivered": msg, "target_agent": agent_name}
    # Delivery feedback: a directive is only consumed when the agent next steps. If the
    # named agent isn't running right now, say so — it's buffered, not lost, but the
    # manager should know it won't act until (and unless) that agent runs.
    try:
        from backend.workflow_state import build_session_state
        from backend.core.events import _event_log
        state = build_session_state(session_id, _event_log.get(session_id, []))
        running = sorted([n for n, a in (state.get("agents") or {}).items()
                          if (a or {}).get("status") == "running"])
        if running and agent_name not in running:
            resp["warning"] = (f"'{agent_name}' is not currently running "
                               f"(running: {', '.join(running) or 'none'}); directive buffered.")
            resp["running_agents"] = running
    except Exception:
        pass
    return resp


async def _tool_run_cycle(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.missions.goal_engine import dispatch_current_goal
    import asyncio
    company_id = _company_for_session(session_id, founder_id)
    asyncio.create_task(dispatch_current_goal(founder_id, company_id))
    return {"ok": True, "started": True}


async def _tool_pause_session(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core.cancellation import pause_session
    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    pause_session(target)
    return {"ok": True, "session_id": target, "paused": True}


async def _tool_resume_session(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core.cancellation import resume_session
    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    resume_session(target)
    return {"ok": True, "session_id": target, "paused": False}


async def _tool_restart_preview(founder_id: str, session_id: str, args: dict) -> Any:
    import asyncio
    import pathlib
    from backend.core.session_store import get_session_meta
    from backend.tools.git_tools import WORKSPACE_ROOT, _root_session_id
    from backend.tools.local_preview import start_local_preview

    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    meta = get_session_meta(target) or {}
    root_sid = _root_session_id(target)
    ws_root = pathlib.Path(WORKSPACE_ROOT)
    workspace = None
    for candidate in ws_root.glob(f"{root_sid}"):
        workspace = candidate
        break
    if workspace is None:
        for candidate in ws_root.glob("*"):
            if not (candidate / ".oc_session_id").exists():
                continue
            oc = (candidate / ".oc_session_id").read_text().strip()
            if oc and root_sid.startswith(oc[:8]):
                workspace = candidate
                break
    if workspace is None:
        return {"ok": False, "error": "workspace not found for this session"}
    inner = workspace
    subdirs = sorted(
        [p for p in workspace.iterdir() if p.is_dir() and (p / "package.json").exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if subdirs:
        inner = subdirs[0]
    company_name = meta.get("company") or meta.get("project_name") or meta.get("company_name") or ""
    url = await asyncio.to_thread(start_local_preview, str(inner), root_sid, company_name)
    return {"ok": True, "session_id": target, "preview_url": url}


async def _tool_get_completion_audit(founder_id: str, session_id: str, args: dict) -> Any:
    import asyncio
    from backend.api.routes import _load_session_events
    from backend.run_completion_audit import build_run_completion_audit
    from backend.workflow_state import build_session_state, load_session_state

    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    events = await _load_session_events(target)
    state = await asyncio.to_thread(build_session_state, target, events or []) if events else await asyncio.to_thread(load_session_state, target)
    if not state:
        return {"ok": False, "error": "session state not found"}
    return build_run_completion_audit(target, state)


async def _tool_get_session_approvals(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.approval_workflows import get_approval_workflow

    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    workflow = get_approval_workflow(target) or {}
    return {
        "ok": True,
        "session_id": target,
        "requests": workflow.get("requests") or [],
        "updated_at": workflow.get("updated_at"),
    }


async def _tool_decide_approval_gate(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.approval_workflows import decide_approval_request
    from backend.core.events import approval_decision_push, publish

    target = str(args.get("session_id") or session_id)
    gate_key = str(args.get("gate_key") or "").strip()
    decision = str(args.get("decision") or "").strip().lower()
    request_id = str(args.get("request_id") or "").strip() or None
    note = str(args.get("note") or "")
    if not gate_key:
        return {"ok": False, "error": "gate_key required"}
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    workflow = decide_approval_request(
        target,
        gate_key,
        decision,
        request_id=request_id,
        actor_id=founder_id,
        actor_role="owner",
        note=note,
    )
    if not workflow.get("ok"):
        return workflow
    event = {
        "type": "stack_approval_decision",
        "gate_key": gate_key,
        "decision": decision,
        "founder_id": founder_id,
        "note": note,
        "workflow": workflow,
    }
    approval_decision_push(target, gate_key, event)
    await publish(target, event)
    return {"ok": True, "session_id": target, "gate_key": gate_key, "decision": decision}


async def _tool_answer_agent_question(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core.events import input_response_push, publish

    target = str(args.get("session_id") or session_id)
    request_id = str(args.get("request_id") or "").strip()
    answer = str(args.get("answer") or "").strip()
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    if not request_id or not answer:
        return {"ok": False, "error": "request_id and answer required"}
    input_response_push(request_id, {"answer": answer})
    await publish(target, {"type": "agent_input_received", "request_id": request_id})
    return {"ok": True, "session_id": target, "request_id": request_id, "answer": answer}


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
    instruction_context = str(args.get("context") or "").strip()
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
                         company_id=company_id, parent_session_id=root, kind="user")
    except Exception:
        pass

    async def _go():
        try:
            dispatch_instruction = instruction if not instruction_context else f"{instruction}\n\nContext:\n{instruction_context}"
            await orch.continue_run(instruction=dispatch_instruction, founder_id=founder_id,
                                    prior_session_id=root, agents=valid, session_id=child)
        except Exception as e:
            logger.error("copilot dispatch_agents run failed: %s", e)

    asyncio.create_task(_go())
    return {
        "ok": True,
        "dispatched": valid,
        "session_id": child,
        "instruction": instruction[:120],
        "context": instruction_context[:200],
    }


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
    goal = start_goal(founder_id, title=title, tasks=tasks, kind="user", company_id=company_id)
    if bool(args.get("dispatch", True)):
        asyncio.create_task(dispatch_current_goal(founder_id, company_id))
    return {"ok": True, "goal": title, "tasks": [t["title"] for t in tasks], "dispatched": bool(args.get("dispatch", True))}


async def _tool_session_status(founder_id: str, session_id: str, args: dict) -> Any:
    target = str(args.get("session_id") or session_id)
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    from backend.core.session_store import get_session_meta
    meta = get_session_meta(target) or {}
    return {"status": meta.get("status"), "goal": (meta.get("goal") or "")[:200],
            "credits_used": meta.get("credits_used", 0), "kind": meta.get("kind")}


async def _tool_google_drive_list(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_drive_list_files
    return google_drive_list_files(founder_id, str(args.get("query") or ""), int(args.get("page_size") or 20))


async def _tool_google_drive_read(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_drive_read_file
    return google_drive_read_file(founder_id, str(args.get("file_id") or ""))


async def _tool_google_docs_create(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_docs_create_document
    return google_docs_create_document(founder_id, str(args.get("title") or ""), str(args.get("text") or ""))


async def _tool_google_docs_append(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_docs_append_text
    return google_docs_append_text(founder_id, str(args.get("document_id") or ""), str(args.get("text") or ""))


async def _tool_google_docs_read(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_docs_read_document
    return google_docs_read_document(founder_id, str(args.get("document_id") or ""))


async def _tool_google_sheets_create(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_sheets_create_spreadsheet
    return google_sheets_create_spreadsheet(
        founder_id,
        str(args.get("title") or ""),
        str(args.get("sheet_name") or "Sheet1"),
        list(args.get("headers") or []),
        list(args.get("rows") or []),
    )


async def _tool_google_sheets_read(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_sheets_read
    return google_sheets_read(founder_id, str(args.get("spreadsheet_id") or ""), str(args.get("range_a1") or "A1:Z100"))


async def _tool_google_sheets_update(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_sheets_update_range
    return google_sheets_update_range(founder_id, str(args.get("spreadsheet_id") or ""), str(args.get("range_a1") or ""), list(args.get("values") or []))


async def _tool_google_slides_create(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_slides_create_presentation
    return google_slides_create_presentation(founder_id, str(args.get("title") or ""))


async def _tool_google_slides_add(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_slides_add_slide
    return google_slides_add_slide(founder_id, str(args.get("presentation_id") or ""), str(args.get("title") or ""), str(args.get("body") or ""))


async def _tool_google_calendar_create(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_calendar_create_event
    return google_calendar_create_event(
        founder_id,
        str(args.get("summary") or ""),
        str(args.get("start_time") or ""),
        str(args.get("end_time") or ""),
        str(args.get("description") or ""),
        str(args.get("timezone") or "UTC"),
    )


async def _tool_google_calendar_list(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.tools.google_workspace_tools import google_calendar_list_events
    return google_calendar_list_events(
        founder_id,
        str(args.get("time_min") or ""),
        str(args.get("time_max") or ""),
        int(args.get("max_results") or 10),
    )


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
    "mcp_message_agent": ("astra_message_agent", "send a directive to ONE specific agent by name. args: {agent, message, session_id?}"),
    "mcp_stop_agent": ("astra_stop_agent", "INSTANTLY stop ONE running agent by name (halts at next step) without killing the run. args: {agent, session_id?}"),
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
    """Return error string if target session doesn't belong to founder_id, else None.
    Fails closed: any error (missing session, import failure) returns 'forbidden'."""
    if not founder_id:
        return "forbidden"
    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(target_sid)
    except Exception as exc:
        logger.warning("owner check failed for %s: %s", target_sid, exc)
        return "forbidden"
    if not meta:
        return "forbidden"
    if str(meta.get("founder_id") or "") != str(founder_id):
        return "forbidden"
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


async def _tool_stop_agent(founder_id: str, session_id: str, args: dict) -> Any:
    """Instantly stop ONE running agent by name, without killing the rest of the run.
    Harder than steering: the agent halts at its next step instead of being asked to
    wrap up. args: {agent, session_id?}

    "research" is not one process -- it fans out into named lanes (research,
    research_gtm, research_competitors, research_customers, research_execution),
    each an independently running agent loop the model has no visibility into.
    Stopping just the literal name "research" left the other lanes running.
    Expand to every lane sharing the given name as a prefix before stopping."""
    from backend.core.cancellation import request_kill_agent
    from backend.core.events import publish
    agent_name = str(args.get("agent") or args.get("agent_name") or "").strip().lower()
    target = str(args.get("session_id") or session_id)
    if not agent_name:
        return {"ok": False, "error": "agent name required"}
    err = _assert_session_owner(target, founder_id)
    if err:
        return {"ok": False, "error": err}
    try:
        from backend.core.orchestrator import _RESEARCH_LANE_FOCUS
        lane_names = set(_RESEARCH_LANE_FOCUS.keys())
    except Exception:
        lane_names = set()
    targets = {name for name in lane_names if name == agent_name or name.startswith(agent_name + "_")}
    if not targets:
        targets = {agent_name}
    try:
        for name in targets:
            request_kill_agent(target, name)
        try:
            await publish(target, {"type": "agent_stop_requested", "agent": agent_name, "stopped_lanes": sorted(targets)})
        except Exception:
            pass
        return {"ok": True, "stopped": sorted(targets), "session_id": target}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_rerun_agent(founder_id: str, session_id: str, args: dict) -> Any:
    """Re-run a single agent that failed or needs to redo its work.
    args: {agent_name, instruction?, session_id?}

    instruction, when given, replaces the default full-redo directive so a
    founder can scope the rerun -- e.g. "regenerate just the logo, bolder
    colors" or "redo only the competitor section, add 2 more competitors"
    instead of the agent redoing its entire prior workflow from scratch.

    Runs IN PLACE in the target session (same pattern as the chat rerun-intent
    path in routes.py::continue_goal) rather than spawning a new child session
    -- founders were confused when "restart this agent" silently opened a
    second session they had to go find instead of showing progress in the one
    they were already looking at."""
    import asyncio
    from backend.core import cancellation
    from backend.core.events import publish
    from backend.core.factory import get_orchestrator
    from backend.core.session_store import get_session_meta
    agent_name = str(args.get("agent_name") or args.get("agent") or "").strip()
    target_sid = str(args.get("session_id") or session_id)
    if not agent_name:
        return {"ok": False, "error": "agent_name required"}
    err = _assert_session_owner(target_sid, founder_id)
    if err:
        return {"ok": False, "error": err}
    orch = get_orchestrator()
    if agent_name not in (orch.specialists or {}):
        return {"ok": False, "error": f"unknown agent {agent_name!r}; use list_agents"}
    try:
        src_meta = get_session_meta(target_sid) or {}
        custom_instruction = str(args.get("instruction") or "").strip()
        instruction = custom_instruction or src_meta.get("goal") or f"Complete your assigned work for: {agent_name}"

        vault_context = ""
        try:
            from backend.tools.obsidian_logger import format_vault_context
            vault_context = await asyncio.to_thread(format_vault_context, agent_name, 5, founder_id)
        except Exception:
            pass

        from backend.core.agent import AgentContext
        ctx = AgentContext(
            goal=instruction,
            founder_id=founder_id,
            session_id=target_sid,
            shared={"prior_vault_notes": vault_context, "rerun": True},
        )
        agent = orch.specialists[agent_name]
        await publish(target_sid, {"type": "agent_start", "agent": agent_name, "task_id": f"rerun_{agent_name}", "instruction": instruction})
        await publish(target_sid, {"type": "chat_intent", "intent": "rerun", "agent": agent_name})

        async def _go():
            try:
                result = await agent.run(ctx)
                await publish(target_sid, {"type": "agent_done", "agent": agent_name, "task_id": f"rerun_{agent_name}", "result": result})
            except Exception as e:
                await publish(target_sid, {"type": "agent_error", "agent": agent_name, "error": str(e)})
            finally:
                cancellation.clear(target_sid)

        _task = asyncio.create_task(_go())
        cancellation.register_task(target_sid, _task)
        return {"ok": True, "agent": agent_name, "session_id": target_sid}
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


async def _tool_get_subteam_report(founder_id: str, session_id: str, args: dict) -> Any:
    import asyncio
    from backend.company_reports import build_company_subteam_report

    team = str(args.get("team") or "engineering").strip() or "engineering"
    days = int(args.get("days") or 7)
    try:
        report = await asyncio.to_thread(build_company_subteam_report, founder_id, team, days)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "team": report.get("team"),
        "summary": report.get("summary"),
        "record_count": report.get("record_count"),
        "session_count": report.get("session_count"),
        "active_work": report.get("active_work") or [],
        "completed_work": report.get("completed_work") or [],
        "blockers": report.get("blockers") or [],
        "next_actions": report.get("next_actions") or [],
    }


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
            return {"notes": [], "vault_root": str(base)}
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
            notes.append({"path": str(p.relative_to(base_real)), "content": _clip(p.read_text(), 500)})
        return {"notes": notes, "vault_root": str(base)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Automations canvas (native agent/prompt/action flow builder) ───────────────

def _automation_node_schema_hint() -> str:
    from backend.tools.automation_blocks import catalog as _integration_catalog

    blocks = _integration_catalog()

    def _describe(b: dict) -> str:
        scope_label = "founder-connected" if b["scope"] == "founder" else "Astra's account"
        params = ", ".join(p["key"] for p in b["params"])
        return f"{b['key']} ({b['category']}, {scope_label}): {params}"

    block_list = "; ".join(_describe(b) for b in blocks)
    return (
        "Node: {id, type, config}. type is one of: "
        "trigger (config: {}) — manual start; "
        "agent (config: {agent_name, instruction}) — runs one Astra specialist "
        "with full tool access (research/web/technical/marketing/sales/legal/etc, "
        "see list_agents); "
        "prompt (config: {instruction}) — a quick tool-free LLM reply, for text "
        "transforms/summaries, not research; both agent and prompt also accept an optional "
        "output_schema (config: {..., output_schema}) — a JSON shape description string; when "
        "set, the node's output is forced to (and validated as) JSON matching that shape, for "
        "piping into json_extract downstream; "
        "action (config: {method, url, headers?, body?} OR {windmill_flow_path, payload?}) "
        "— HTTP request or an existing Windmill flow; "
        "delay (config: {seconds}) — pause before continuing; "
        "condition (config: {contains}) — only continues past this node if the "
        "upstream output contains this text (case-insensitive), skipping it and everything "
        "downstream otherwise; "
        "condition_equals (config: {equals}) — same but exact match instead of contains; "
        "merge (config: {separator?}) — passes concatenated upstream output through unchanged, "
        "useful as an explicit join point when a node has multiple incoming edges; "
        "json_extract (config: {path}) — pulls a dot-path field out of upstream JSON output "
        "(e.g. path 'data.0.id'); "
        "text_transform (config: {operation}) — operation is uppercase|lowercase|trim, applied "
        "to upstream output; "
        "set_text (config: {text}) — a constant text value, useful as a flow's starting input; "
        "current_time (config: {}) — outputs the current UTC timestamp; "
        "switch (config: {value?, cases: [str, ...]}) — routes to a different branch per case; "
        "value defaults to the upstream output if omitted. Each case's outgoing edge MUST set "
        "source_handle to 'case_0', 'case_1', ... (index into cases) — the branch for anything "
        "that doesn't match any case uses source_handle 'default'. Edges without a matching case "
        "are skipped for that run; "
        "code (config: {expression}) — evaluates ONE restricted Python expression (ast.parse "
        "mode='eval', no imports/statements/loops, small builtin whitelist, no dunder access) "
        "against `input` (upstream output, JSON-parsed if possible); use for small transforms "
        "json_extract/text_transform can't express, never for anything needing imports or I/O; "
        "integration (config: {block_key, params: {...}}) — calls one of the pre-built "
        "integration blocks below. block_key and its param keys: "
        f"{block_list}. "
        "Any instruction/url/body/message/param field can reference an upstream node's result "
        "with {{node_id.output}}. Edge: {source, target, source_handle?} (node ids; source_handle "
        "only needed for switch node branches)."
    )


async def _tool_list_automations(founder_id: str, session_id: str, args: dict) -> Any:
    """List this founder's saved automation flows."""
    from backend.core import automation_store
    flows = automation_store.list_flows(founder_id)
    return {"flows": [
        {"id": f["id"], "name": f["name"], "node_count": len(f.get("nodes", [])), "updated_at": f.get("updated_at")}
        for f in flows
    ]}


async def _tool_get_automation(founder_id: str, session_id: str, args: dict) -> Any:
    """Read one automation flow's full node/edge definition. args: {flow_id}"""
    from backend.core import automation_store
    flow_id = str(args.get("flow_id") or "")
    flow = automation_store.get_flow(founder_id, flow_id)
    if not flow:
        return {"ok": False, "error": f"Flow '{flow_id}' not found"}
    return flow


async def _tool_create_automation(founder_id: str, session_id: str, args: dict) -> Any:
    from backend.core import automation_store
    name = str(args.get("name") or "Untitled automation")
    nodes = args.get("nodes") or []
    edges = args.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        return {"ok": False, "error": "nodes must be a non-empty list"}
    flow = automation_store.save_flow(founder_id, name, nodes, edges)
    return {"ok": True, "flow_id": flow["id"], "name": flow["name"]}


async def _tool_update_automation(founder_id: str, session_id: str, args: dict) -> Any:
    """Update an existing automation flow's name/nodes/edges. args: {flow_id, name?, nodes?, edges?}."""
    from backend.core import automation_store
    flow_id = str(args.get("flow_id") or "")
    existing = automation_store.get_flow(founder_id, flow_id)
    if not existing:
        return {"ok": False, "error": f"Flow '{flow_id}' not found"}
    name = str(args.get("name") or existing["name"])
    nodes = args.get("nodes") if args.get("nodes") is not None else existing["nodes"]
    edges = args.get("edges") if args.get("edges") is not None else existing["edges"]
    flow = automation_store.save_flow(founder_id, name, nodes, edges, flow_id=flow_id)
    return {"ok": True, "flow_id": flow["id"], "name": flow["name"]}


async def _tool_delete_automation(founder_id: str, session_id: str, args: dict) -> Any:
    """Delete an automation flow. args: {flow_id}"""
    from backend.core import automation_store
    flow_id = str(args.get("flow_id") or "")
    ok = automation_store.delete_flow(founder_id, flow_id)
    return {"ok": ok}


async def _tool_run_automation(founder_id: str, session_id: str, args: dict) -> Any:
    """Run an automation flow now. args: {flow_id}. Returns a run_id — poll
    get_automation_run to see progress/results, it does not wait for completion."""
    import asyncio
    from backend.core import automation_store
    from backend.tools.automation_graph import run_automation_flow
    flow_id = str(args.get("flow_id") or "")
    if not automation_store.get_flow(founder_id, flow_id):
        return {"ok": False, "error": f"Flow '{flow_id}' not found"}
    run = automation_store.create_run(founder_id, flow_id)
    asyncio.create_task(run_automation_flow(founder_id, flow_id, run["run_id"]))
    return {"ok": True, "run_id": run["run_id"], "status": "running"}


async def _tool_get_automation_run(founder_id: str, session_id: str, args: dict) -> Any:
    """Read an automation run's status and per-node results. args: {run_id}"""
    from backend.core import automation_store
    run_id = str(args.get("run_id") or "")
    run = automation_store.get_run(founder_id, run_id)
    if not run:
        return {"ok": False, "error": f"Run '{run_id}' not found"}
    return run


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
    "decide_goal_task": ("approve or send back a specific goal milestone that is awaiting founder approval. args: {task_id, approved, note?}", _tool_decide_goal_task),
    "steer_agents": ("broadcast a directive to ALL running agents in this session. args: {message}", _tool_steer_agents),
    "message_agent": ("send a directive to ONE specific agent by name. args: {agent, message}. Use when you want only the web/sales/design/etc agent to receive the instruction.", _tool_message_agent),
    "run_cycle": ("dispatch the team on the current approved goal now. args: {}", _tool_run_cycle),
    "pause_session": ("pause a running session so new work stops advancing until resumed. args: {session_id?}", _tool_pause_session),
    "resume_session": ("resume a paused session. args: {session_id?}", _tool_resume_session),
    "restart_preview": ("restart the local preview server for a session workspace. args: {session_id?}", _tool_restart_preview),
    "session_status": ("status of a session (defaults to the current one). args: {session_id?}", _tool_session_status),
    "kill_session": ("stop/kill a running or hung session. args: {session_id?}", _tool_kill_session),
    "stop_agent": ("INSTANTLY stop ONE running agent by name (halts at its next step) without killing the rest of the run. Harder than message_agent/steer_agents, which only ask. args: {agent, session_id?}", _tool_stop_agent),
    "rerun_agent": ("re-run a single agent that failed or needs to redo its work. Pass instruction to scope the redo to a specific piece (e.g. 'regenerate just the logo, bolder colors') instead of a full redo. args: {agent_name, instruction?, session_id?}", _tool_rerun_agent),
    # ── Read session outputs ───────────────────────────────────────────────────
    "get_session_digest": ("full digest of a session — what each agent produced, key outputs, deploy URLs. args: {session_id?}", _tool_get_session_digest),
    "get_completion_audit": ("inspect whether a run really finished cleanly, including deploy and handoff checks. args: {session_id?}", _tool_get_completion_audit),
    "get_session_approvals": ("read all current and historical approval requests for a session. args: {session_id?}", _tool_get_session_approvals),
    "decide_approval_gate": ("approve, skip, or reject a session approval gate. args: {gate_key, decision, session_id?, request_id?, note?}", _tool_decide_approval_gate),
    "answer_agent_question": ("answer a live agent question so the blocked run can continue. args: {request_id, answer, session_id?}", _tool_answer_agent_question),
    "get_subteam_report": ("summarize what a functional team has been doing across company memory. args: {team, days?}", _tool_get_subteam_report),
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
    "google_drive_list_files": ("list files available in the founder's connected Google Drive. args: {query?, page_size?}", _tool_google_drive_list),
    "google_drive_read_file": ("read one Google Drive / Docs / Sheets / Slides file by file_id. args: {file_id}", _tool_google_drive_read),
    "google_docs_create": ("create a Google Doc in the founder's connected Workspace. args: {title, text?}", _tool_google_docs_create),
    "google_docs_append": ("append text to a Google Doc. args: {document_id, text}", _tool_google_docs_append),
    "google_docs_read": ("read a Google Doc. args: {document_id}", _tool_google_docs_read),
    "google_sheets_create": ("create a Google Sheet. args: {title, sheet_name?, headers?, rows?}", _tool_google_sheets_create),
    "google_sheets_read": ("read a Google Sheet range. args: {spreadsheet_id, range_a1?}", _tool_google_sheets_read),
    "google_sheets_update": ("write a Google Sheet range. args: {spreadsheet_id, range_a1, values}", _tool_google_sheets_update),
    "google_slides_create": ("create a Google Slides presentation. args: {title}", _tool_google_slides_create),
    "google_slides_add_slide": ("add a title/body slide to Google Slides. args: {presentation_id, title?, body?}", _tool_google_slides_add),
    "google_calendar_create_event": ("create a Google Calendar event. args: {summary, start_time, end_time, description?, timezone?}", _tool_google_calendar_create),
    "google_calendar_list_events": ("list Google Calendar events. args: {time_min?, time_max?, max_results?}", _tool_google_calendar_list),
    # ── Outreach / CRM ────────────────────────────────────────────────────────
    "get_outreach": ("get outreach contacts and campaigns summary. args: {limit?}", _tool_get_outreach),
    # ── Cost / vault ──────────────────────────────────────────────────────────
    "get_cost": ("get credit usage and cost for a session. args: {session_id?}", _tool_get_cost),
    "read_vault": ("read raw obsidian/vault notes. args: {path?, limit?}", _tool_read_vault),
    # ── Automations canvas ────────────────────────────────────────────────────
    "list_automations": ("list this founder's saved automation flows. args: {}", _tool_list_automations),
    "get_automation": ("read one automation flow's full node/edge definition. args: {flow_id}", _tool_get_automation),
    "create_automation": (
        f"create a new automation flow. args: {{name, nodes:[...], edges:[...]}}. {_automation_node_schema_hint()}",
        _tool_create_automation,
    ),
    "update_automation": ("update an existing automation's name/nodes/edges. args: {flow_id, name?, nodes?, edges?}. Same node/edge schema as create_automation.", _tool_update_automation),
    "delete_automation": ("delete an automation flow. args: {flow_id}", _tool_delete_automation),
    "run_automation": ("run an automation flow now (async — returns a run_id, doesn't wait). args: {flow_id}", _tool_run_automation),
    "get_automation_run": ("read an automation run's status and per-node results. args: {run_id}", _tool_get_automation_run),
}

# Fold in the MCP parity tools (in-process proxies).
for _cp_name, (_mcp_name, _doc) in _MCP_TOOLS.items():
    if _cp_name not in _TOOLS:
        _TOOLS[_cp_name] = (_doc, _make_mcp_tool(_mcp_name))


_ACTION_LINE_RE = re.compile(r"\{[\s\S]*?\}", re.DOTALL)
_ACTION_NAME_RE = re.compile(r'"action"\s*:\s*"(?P<action>[^"]+)"')
_TOOL_NAME_RE = re.compile(r'"tool"\s*:\s*"(?P<tool>[^"]+)"')
_ARGS_RE = re.compile(r'"args"\s*:\s*(\{[\s\S]*\})', re.DOTALL)


def _extract_leading_reply(raw: str) -> str:
    if not raw:
        return ""
    head = raw.split("{", 1)[0].strip()
    if head.startswith("```"):
        return ""
    return head


def _parse_action(raw: str) -> dict:
    from backend.core.json_extract import extract_json
    v = extract_json(raw, prefer_keys=("action",))
    if isinstance(v, dict) and v.get("action"):
        return v

    text = (raw or "").strip()
    if not text:
        return {"action": "reply", "text": ""}

    # Recover from common LLM formatting drift:
    # 1. a natural-language preface followed by a JSON tool object
    # 2. malformed tool JSON that still clearly names action/tool/args
    action_match = _ACTION_NAME_RE.search(text)
    tool_matches = list(_TOOL_NAME_RE.finditer(text))
    tool_match = tool_matches[-1] if tool_matches else None
    if action_match and tool_match:
        parsed: dict[str, Any] = {
            "action": action_match.group("action").strip(),
            "tool": tool_match.group("tool").strip(),
        }
        args_match = _ARGS_RE.search(text)
        if args_match:
            parsed["args"] = extract_json(args_match.group(1)) or {}
        else:
            parsed["args"] = {}
        preface = _extract_leading_reply(text)
        if preface:
            parsed["preface"] = preface
        return parsed

    # If multiple JSON-ish blobs were emitted, prefer the first one that looks
    # like an action object even when the full response is not parseable.
    for match in _ACTION_LINE_RE.finditer(text):
        candidate = extract_json(match.group(0), prefer_keys=("action",))
        if isinstance(candidate, dict) and candidate.get("action"):
            return candidate

    return {"action": "reply", "text": text}


def _summarize_copilot_action(tool: str, result: Any) -> dict[str, str]:
    tone = "success"
    label = tool.replace("_", " ").strip().title() or "Action"
    detail = ""
    payload = result if isinstance(result, dict) else {}

    if tool == "get_dashboard":
        count = int(payload.get("count") or len(payload.get("elements") or []))
        label = "Reviewed dashboard"
        detail = f"{count} tile{'s' if count != 1 else ''} found"
        tone = "info"
    elif tool == "add_dashboard_tile":
        label = "Added dashboard tile"
        detail = str(payload.get("id") or "New tile created")
    elif tool == "dispatch_agents":
        dispatched = payload.get("dispatched") or []
        label = "Dispatched agents"
        if isinstance(dispatched, list) and dispatched:
            detail = ", ".join(str(item) for item in dispatched[:4])
        else:
            detail = str(payload.get("session_id") or "Work started")
    elif tool == "steer_agents":
        label = "Steered live agents"
        detail = str(payload.get("message") or "New direction sent")
    elif tool == "set_goal":
        label = "Updated company goal"
        detail = str(payload.get("goal_title") or payload.get("title") or "Goal saved")
    elif tool == "approve_next_goal":
        label = "Resolved next goal"
        detail = "Approved and started" if payload.get("approved") else "Rejected"
    elif tool == "decide_goal_task":
        label = "Resolved milestone approval"
        detail = str(payload.get("title") or payload.get("task_id") or "Milestone updated")
    elif tool == "run_cycle":
        label = "Ran another cycle"
        detail = str(payload.get("session_id") or payload.get("message") or "Execution resumed")
    elif tool == "pause_session":
        label = "Paused session"
        detail = str(payload.get("session_id") or "Run paused")
    elif tool == "resume_session":
        label = "Resumed session"
        detail = str(payload.get("session_id") or "Run resumed")
    elif tool == "restart_preview":
        label = "Restarted preview"
        detail = str(payload.get("preview_url") or "Preview restarted")
    elif tool == "get_completion_audit":
        label = "Checked completion audit"
        detail = str(payload.get("status") or payload.get("summary") or "Audit loaded")
        tone = "info"
    elif tool == "get_session_approvals":
        label = "Reviewed approvals"
        detail = f"{len(payload.get('requests') or [])} request(s)"
        tone = "info"
    elif tool == "decide_approval_gate":
        label = "Resolved approval gate"
        detail = str(payload.get("decision") or "Decision recorded")
    elif tool == "answer_agent_question":
        label = "Answered agent question"
        detail = str(payload.get("request_id") or "Response submitted")
    elif tool == "session_status":
        label = "Checked session status"
        detail = str(payload.get("status") or "Status refreshed")
        tone = "info"
    elif tool == "get_session_digest":
        label = "Reviewed session outputs"
        detail = str(payload.get("goal") or payload.get("session_id") or "Latest artifacts loaded")
        tone = "info"
    elif tool in {"ask_brain", "read_brain", "read_vault", "get_library", "read_library_item", "get_outreach", "get_integrations", "company_goal", "list_goals", "list_sessions", "list_agents", "get_cost", "get_subteam_report"}:
        label = tool.replace("_", " ").strip().title() or "Checked context"
        detail = "Context refreshed"
        tone = "info"

    if payload.get("ok") is False:
        tone = "warn"
        detail = str(payload.get("error") or detail or "Tool unavailable")

    return {"tool": tool, "label": label, "detail": detail, "tone": tone}


_DIRECTIVE_WORDS = {
    "tell", "make", "focus", "change", "stop", "start", "fix", "build", "add",
    "remove", "update", "switch", "redirect", "adjust", "prioritize", "skip",
    "continue", "pause", "wrap", "finish", "move", "shift", "speed", "slow",
    "ignore", "include", "exclude", "emphasize", "drop", "keep", "rewrite",
}


def _is_steer_directive(msg: str) -> bool:
    low = f" {msg.lower().strip()} "
    return any(f" {w} " in low or low.startswith(f" {w} "[1:]) for w in _DIRECTIVE_WORDS)


def _looks_like_question(msg: str) -> bool:
    low = re.sub(r"(?:^|\s)@[a-z0-9_]+", " ", str(msg or "").lower()).strip()
    return low.endswith("?") or low.startswith((
        "what ", "why ", "how ", "when ", "where ", "who ", "which ",
        "is ", "are ", "can ", "could ", "would ", "should ", "tell me ",
    ))


def _fallback_copilot_reply(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "I didn't catch that clearly. Try rephrasing, or tell me which agents to dispatch and what to do."

    last = actions[-1]
    tool = str(last.get("tool") or "")
    result = last.get("result") if isinstance(last.get("result"), dict) else {}

    if tool == "get_dashboard":
        elements = result.get("elements") or []
        count = int(result.get("count") or len(elements))
        if count == 0:
            return "Your dashboard is basically empty right now. I can replace it with useful company health, blockers, decisions, and next-step tiles."
        titles = [str(item.get("title") or "").strip() for item in elements if isinstance(item, dict)]
        titles = [title for title in titles if title][:4]
        named = ", ".join(titles)
        suffix = f" Right now it has {named}." if named else ""
        return f"I checked the dashboard and found {count} tile{'s' if count != 1 else ''}.{suffix}"

    if tool == "add_dashboard_tile":
        return "I added the dashboard tile."

    if tool == "dispatch_agents":
        dispatched = result.get("dispatched") or []
        if isinstance(dispatched, list) and dispatched:
            return f"I started work with {', '.join(str(item) for item in dispatched[:4])}."
        return "I started the work."

    if tool == "steer_agents":
        return "I sent that direction to the agents already working on it."
    if tool == "message_agent":
        target = result.get("target_agent") or "that agent"
        return f"I sent that directly to {target}."
    if tool == "pause_session":
        return "I paused the session."
    if tool == "resume_session":
        return "I resumed the session."
    if tool == "restart_preview":
        return "I restarted the preview."
    if tool == "decide_goal_task":
        return f"I marked that milestone as {'approved' if result.get('approved') else 'needs changes'}."
    if tool == "decide_approval_gate":
        return f"I recorded that approval as {result.get('decision', 'resolved')}."
    if tool == "answer_agent_question":
        return "I answered the agent’s question so the run can continue."

    if tool == "session_status":
        status = result.get("status")
        return f"I checked the session status: {status}." if status else "I checked the session status."

    summary = _summarize_copilot_action(tool, result).get("label")
    if summary:
        return f"I completed: {summary}."

    return "I completed the requested action."


async def _copilot_generate(prompt: str) -> str:
    """Single LLM call for the copilot — async, no chain-of-thought (latency-optimised)."""
    import asyncio
    import httpx
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key

    key = get_openrouter_key() or settings.agent_model_api_key
    model = settings.or_highoutput_model  # deepseek/deepseek-v4-flash

    def _call() -> str:
        with httpx.Client(timeout=60) as c:
            r = c.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 6000,
                    "temperature": 0.2,
                    # Suppress chain-of-thought — copilot only needs short JSON decisions
                    "reasoning": {"effort": "none"},
                    "provider": {"allow_fallbacks": True},
                },
            )
        d = r.json()
        if "error" in d:
            raise RuntimeError(str(d["error"])[:200])
        return ((d.get("choices") or [{}])[0]).get("message", {}).get("content") or ""

    return await asyncio.to_thread(_call)


async def run_copilot(
    founder_id: str,
    session_id: str,
    message: str,
    founder_email: str = "",
    attachments: list[dict[str, Any]] | None = None,
    mentioned_agents: list[str] | None = None,
) -> dict[str, Any]:
    """Run one copilot turn: load history, let the model use tools, reply, persist."""
    from backend.tools._llm import generate

    history = get_history(session_id)
    live = await _load_live_context(session_id, founder_id)
    roster = _agent_roster()
    explicit_agents = list(dict.fromkeys(
        str(agent).strip().lower()
        for agent in (mentioned_agents or [])
        if str(agent).strip().lower() in roster
    ))
    attachment_context = _attachment_context_block(_normalize_attachments(attachments))
    tool_docs = "\n".join(f"- {name}: {doc}" for name, (doc, _) in _TOOLS.items())
    system = (
        "You are the founder's Copilot inside an Astra session — a hands-on operator that ACTS on "
        "the company, not a status narrator. You can call tools to query the company brain, read and "
        "approve goals, resolve live approval gates, answer blocked agent questions, steer the running agents, "
        "pause/resume runs, restart previews, run a cycle, and check status.\n\n"
        + (f"FOUNDER ACCOUNT:\n  email: {founder_email}\n  founder_id: {founder_id}\n"
           "Use this email as the founder's contact email whenever building websites, "
           "writing copy, or setting up contact forms — never invent a placeholder email.\n\n"
           if founder_email else "")
        + f"TOOLS:\n{tool_docs}\n\n"
        "You can natively drive the whole company: see every agent (list_agents), dispatch any of them "
        "on any directive (dispatch_agents), create/activate goals with per-workstream tasks (set_goal), "
        "approve the next goal, approve individual milestones, steer running agents, resolve approval gates, "
        "answer blocked questions, restart previews, pause/resume runs, inspect completion audits, read subteam reports, "
        "and run another cycle.\n\n"
        + (
            "EXPLICIT UI MENTIONS (authoritative): " + ", ".join(explicit_agents) + ". "
            "The founder selected these exact agents with @mentions. For a directive, target every mentioned agent; "
            "for a question, answer through the mentioned agent. Do not broaden the target set unless the founder explicitly asks.\n\n"
            if explicit_agents else ""
        )
        + "DECISION TREE — check in this exact order for every message:\n"
        "0. SESSION DONE CHECK: if session_meta.status == 'done' OR state.status == 'done', "
        "the session has COMPLETED — there are NO running agents regardless of what running_agents shows. "
        "NEVER call steer_agents for a done session. Treat ALL imperatives as dispatch_agents or set_goal.\n"
        "1. RUNNING AGENTS + DIRECTIVE: if session is NOT done AND running_agents or child_sessions_running is NON-EMPTY "
        "AND the founder is giving a directive:\n"
        "   a) Directive targets a SPECIFIC agent by name (web, sales, design, research, etc.) "
        "→ message_agent {agent: '<name>', message: '<exact directive>'}. ONLY that agent receives it.\n"
        "   b) Directive is for ALL agents or no specific agent named "
        "→ steer_agents {message: '<directive>'}. ALL agents receive it.\n"
        "   c) Founder asks a QUESTION to a specific agent (e.g. 'ask the sales agent what contacts they found') "
        "→ chat_agent {agent: '<name>', message: '<question>'}. Returns a grounded answer.\n"
        "   d) Founder wants to STOP/HALT/KILL one specific agent NOW (e.g. 'stop the web agent', 'kill design') "
        "→ stop_agent {agent: '<name>'}. Instantly halts THAT agent at its next step; the rest of the run continues. "
        "Use this (not message_agent) for stop/halt/kill imperatives — message_agent only ASKS, stop_agent ENFORCES.\n"
        "   Examples:\n"
        '   "tell the web agent to go all out on design" → message_agent {agent:"web", message:"go all out on design — luxury, premium, full rebuild"}\n'
        '   "tell them all to wrap up" → steer_agents {message:"wrap up and summarize findings now"}\n'
        '   "ask sales what prospects they found" → chat_agent {agent:"sales", message:"what prospects have you identified so far?"}\n'
        '   "stop the web agent" / "kill the design agent now" → stop_agent {agent:"web"}\n'
        "   DO NOT reply without acting. DO NOT dispatch more agents.\n"
        "2. IMPERATIVE + NO RUNNING AGENTS (or session done): build, make, create, add, fix, change, ship, launch, redesign, update "
        "→ dispatch_agents with the right agents. Examples:\n"
        "   'build an app' → dispatch_agents {agents:['web','technical'], instruction:'build full product: auth + dashboard + core features'}\n"
        "   'redesign the landing page' → dispatch_agents {agents:['design','web'], instruction:'redesign the landing page: ...'}\n"
        "3. BROADER OBJECTIVE: → set_goal with per-workstream tasks (auto-dispatches).\n"
        "4. APPROVAL OR BLOCKER: if approval_workflow.requests or goal_pending_approvals or pending_agent_question are relevant, "
        "use get_session_approvals / decide_approval_gate / decide_goal_task / answer_agent_question.\n"
        "5. QUESTION: 'what is...', 'how is...', 'show me...' → ask_brain / session_status / list_goals / get_completion_audit.\n"
        "NEVER dispatch_agents if running_agents is non-empty AND session is NOT done. NEVER narrate options for an imperative.\n\n"
        "DEPLOY/404 ERRORS: If the founder reports a 404, DEPLOYMENT_NOT_FOUND, or broken URL from an "
        "agent-built site, immediately dispatch_agents with web+technical agents instructed to rebuild and "
        "redeploy the specific site. Use the deploy_url from all_recent_sessions to identify which project "
        "the founder means. Never ask for clarification on deploy errors — just fix them.\n\n"
        "GOAL QUESTIONS: all_goals and all_recent_sessions in the snapshot give you full visibility. "
        "Use list_goals or list_sessions tools only when you need fresher data than the snapshot.\n\n"
        "UPLOADED FILES: if the founder attached files, use their extracted content as first-class context. "
        "When dispatching or steering agents, include the relevant file facts in the tool instruction/context so agents can act on them.\n\n"
        "LIVE SESSION SNAPSHOT (ground truth, refreshes every turn):\n"
        f"{json.dumps(live, indent=2, sort_keys=True)[:9000]}\n\n"
        f"{attachment_context}\n\n"
        'Respond with ONE JSON object per step:\n'
        '  to use a tool: {"action":"tool","tool":"<name>","args":{...}}\n'
        '  to answer:     {"action":"reply","text":"<your message to the founder>"}\n'
        "After a tool runs you get its result and continue. Keep replies concise and concrete; "
        "when you took an action, say what you did.\n"
        "If a tool returns {\"ok\": false, \"note\": \"tool unavailable\"}: answer from the live session snapshot "
        "you already have. NEVER mention tool errors, credential issues, or backend failures to the founder."
    )
    convo = [f"{h['role']}: {h['content']}" for h in history[-12:]]
    founder_turn = message if not attachment_context else f"{message}\n{attachment_context}"
    convo.append(f"founder: {founder_turn}")
    actions: list[dict[str, Any]] = []
    reply = ""

    for _step in range(8):
        prompt = system + "\n\nCONVERSATION:\n" + "\n".join(convo) + "\n\nYour next JSON step:"
        try:
            raw = await _copilot_generate(prompt)
        except Exception as exc:
            reply = f"(copilot error: {exc})"
            break
        act = _parse_action(raw)
        # The model frequently emits {"action":"<tool_name>", ...} (tool name
        # directly as the action) instead of the documented {"action":"tool",
        # "tool":"<tool_name>","args":{...}} shape. Unnormalized, this silently
        # fell through to the reply branch below and dumped the raw JSON to the
        # founder as if it were a final answer -- the tool call never ran at all
        # (confirmed against real copilot history: stop_agent/session_status/
        # run_cycle calls shown verbatim as replies, never executed). Normalize
        # before the tool-dispatch check so either shape works.
        if act.get("action") not in ("tool", "reply") and act.get("action") in _TOOLS:
            _tool_name = act["action"]
            _args = act.get("args") if isinstance(act.get("args"), dict) else {
                k: v for k, v in act.items() if k not in ("action", "preface", "args")
            }
            act = {"action": "tool", "tool": _tool_name, "args": _args, "preface": act.get("preface", "")}
        if act.get("action") == "tool" and act.get("tool") in _TOOLS:
            name = act["tool"]
            preface = str(act.get("preface") or "").strip()
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
            if preface:
                convo.append(f"assistant_note: {preface}")
            continue
        if act.get("action") == "tool" and act.get("tool") and act.get("tool") not in _TOOLS:
            # Hallucinated/misspelled tool name -- previously fell straight through
            # to dumping the raw JSON as the reply and killing the loop. Feed back
            # the valid tool list and let the model retry within its step budget.
            convo.append(
                f"tool[{act.get('tool')}] -> {{\"ok\": false, \"error\": \"no such tool\", "
                f"\"valid_tools\": {json.dumps(sorted(_TOOLS.keys()))}}}"
            )
            continue
        reply = str(act.get("text") or raw).strip()
        break

    # Auto-steer fallback: model replied without calling steer_agents, but agents ARE
    # running and the message is clearly a directive — push the steer directly.
    _explicit_command = bool(explicit_agents) and not _looks_like_question(message)
    if not actions and (_is_steer_directive(message) or _explicit_command):
        running = live.get("running_agents") or []
        child_running = live.get("child_sessions_running") or []
        if running or child_running:
            try:
                named_agents = explicit_agents or [
                    agent for agent in [_detect_named_agent(message, set(roster.keys()) | set(str(item) for item in running))]
                    if agent
                ]
                if named_agents:
                    for named in named_agents:
                        await _tool_message_agent(founder_id, session_id, {"agent": named, "message": message})
                        actions.append({"tool": "message_agent", "args": {"agent": named, "message": message}, "result": {"ok": True, "target_agent": named}})
                    reply = f"Sent to {', '.join(named_agents)}: {message}"
                else:
                    await _tool_steer_agents(founder_id, session_id, {"message": message})
                    actions.append({"tool": "steer_agents", "args": {"message": message}, "result": {"ok": True, "message": message}})
                    reply = f"Sent to the running agents: {message}"
            except Exception:
                pass

    if not actions and explicit_agents and (_is_steer_directive(message) or _explicit_command):
        try:
            result = await _tool_dispatch_agents(
                founder_id,
                session_id,
                {"agents": explicit_agents, "instruction": message},
            )
            actions.append({"tool": "dispatch_agents", "args": {"agents": explicit_agents, "instruction": message}, "result": result})
            reply = f"Started {', '.join(explicit_agents)} on that request."
        except Exception:
            pass

    if not actions and _looks_like_deploy_breakage(message):
        try:
            deploy_targets = live.get("deploy_targets") or []
            target_hint = ""
            if deploy_targets:
                recent = deploy_targets[0]
                target_hint = f" Most recent deploy target: {recent.get('agent')} -> {recent.get('url')}."
            instruction = (
                "Investigate the broken deployment or preview, rebuild the affected site on the existing project, "
                "and redeploy a working live URL. Verify the final URL loads successfully before finishing."
            )
            context = (
                f"Founder report: {message}.{target_hint}"
                f" Review flags: {live.get('session_meta', {}).get('review_reason') or 'none'}."
            ).strip()
            result = await _tool_dispatch_agents(
                founder_id,
                session_id,
                {"agents": ["web", "technical"], "instruction": instruction, "context": context},
            )
            actions.append({"tool": "dispatch_agents", "args": {"agents": ["web", "technical"], "instruction": instruction}, "result": result})
            reply = "I started a rebuild and redeploy pass with the web and technical agents."
        except Exception:
            pass

    if not reply:
        reply = _fallback_copilot_reply(actions)

    action_summaries = [
        _summarize_copilot_action(str(action.get("tool") or ""), action.get("result"))
        for action in actions
        if action.get("tool")
    ]

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    founder_record: dict[str, Any] = {"role": "founder", "content": message, "at": now}
    normalized_attachments = _normalize_attachments(attachments)
    if normalized_attachments:
        founder_record["attachments"] = [
            {
                "filename": item.get("filename"),
                "kind": item.get("kind"),
                "library_id": item.get("library_id"),
                "truncated": item.get("truncated"),
                "preview": _clip(item.get("content"), 240),
            }
            for item in normalized_attachments
        ]
    history.append(founder_record)
    history.append({"role": "copilot", "content": reply, "at": now, "actions": action_summaries})
    _save_history(session_id, history)
    return {"ok": True, "reply": reply, "actions": action_summaries, "history": history}

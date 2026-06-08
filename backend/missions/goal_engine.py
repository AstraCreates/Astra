"""Goal engine — sequential, event-driven company goals.

Model
-----
A company works ONE goal at a time. Each goal carries per-workstream major tasks
owned by specific agents. Tasks tick to "done" as those agents finish (driven by
``agent_done`` events, NOT a timer). When all non-postponed tasks are done the goal
is complete → the planner writes the next goal and dispatches the agents on it.

  Goal 1 (launch, fixed)  — seeded at run start from the planned agents.
  Goal 2..N (planner)     — the planner decides the next objective + tasks.

Workstreams (one major task each, when the run includes its agents):
  research → Validate market & ICP
  product  → Build product & landing   (web + technical + design)
  marketing→ Go-to-market assets
  sales    → Sales pipeline
  legal    → Legal foundation
  ops      → Operating plan             (ops + finance)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Workstream key → (task title, default specialist agents to dispatch for it).
WORKSTREAMS: dict[str, dict[str, Any]] = {
    "research":  {"title": "Validate market & ICP", "dispatch": ["research"]},
    "product":   {"title": "Build product & landing", "dispatch": ["web", "technical"]},
    "marketing": {"title": "Go-to-market assets", "dispatch": ["marketing"]},
    "sales":     {"title": "Sales pipeline", "dispatch": ["sales"]},
    "legal":     {"title": "Legal foundation", "dispatch": ["legal"]},
    "ops":       {"title": "Operating plan", "dispatch": ["ops"]},
}


def _workstream(agent: str) -> str | None:
    a = (agent or "").lower()
    if a.startswith("research"):
        return "research"
    if a.startswith(("web", "technical", "design")):
        return "product"
    if a.startswith("marketing"):
        return "marketing"
    if a.startswith("sales"):
        return "sales"
    if a.startswith("legal"):
        return "legal"
    if a.startswith(("ops", "finance")):
        return "ops"
    return None


def _founder_for_session(session_id: str) -> str:
    try:
        from backend.core.session_store import get_session_meta
        return str((get_session_meta(session_id) or {}).get("founder_id") or "")
    except Exception:
        return ""


# ── Launch goal seeding (run start) ─────────────────────────────────────────────

def ensure_launch_goal(founder_id: str, session_id: str, agents: list[str], goal_text: str = "") -> None:
    """Idempotent: if the founder has no current goal, create the launch goal NOW
    (visible from run start) with one major task per workstream present in the plan."""
    if not founder_id:
        return
    from backend.missions.company_goal import (
        get_company_goal, upsert_company_goal, set_root_session, start_goal, current_goal,
    )
    try:
        if current_goal(founder_id):
            return  # already operating on a goal — don't reseed
        # Group the planned agents by workstream, preserving exact agent names so
        # task-done detection matches the agent_done events exactly.
        by_ws: dict[str, list[str]] = {}
        for a in agents or []:
            ws = _workstream(a)
            if ws:
                by_ws.setdefault(ws, [])
                if a not in by_ws[ws]:
                    by_ws[ws].append(a)
        tasks: list[dict[str, Any]] = []
        for key in WORKSTREAMS:
            if key in by_ws:
                tasks.append({"title": WORKSTREAMS[key]["title"], "owner_agents": by_ws[key]})
        if not tasks:
            tasks = [{"title": "Launch the company", "owner_agents": list(agents or [])}]

        if get_company_goal(founder_id) is None:
            upsert_company_goal(
                founder_id,
                north_star=(goal_text or "Get the company on its feet")[:400],
                company_goal="Get the company launched and operating — all departments working together.",
                source_session_id=session_id,
                status="operating",
            )
        set_root_session(founder_id, session_id)
        start_goal(founder_id, title="Launch the company", tasks=tasks, kind="launch")
        logger.info("goal_engine: seeded launch goal for %s (%d tasks)", founder_id, len(tasks))
    except Exception as e:
        logger.warning("goal_engine.ensure_launch_goal failed for %s: %s", founder_id, e)


# ── Event-driven task ticking (agent_done) ──────────────────────────────────────

def tick_from_agent(session_id: str, agent: str) -> None:
    """An agent finished — mark the current goal's tasks it owns. Called from the
    central event publisher for every agent_done, so it must be cheap and safe."""
    try:
        founder_id = _founder_for_session(session_id)
        if not founder_id or not agent:
            return
        from backend.missions.company_goal import current_goal, complete_agent_workstream
        cg = current_goal(founder_id)
        if not cg:
            return
        # Only touch the store if this agent actually owns an open task.
        owns = any(agent in (t.get("owner_agents") or []) for t in cg.get("tasks") or [])
        if not owns:
            return
        complete_agent_workstream(founder_id, agent, run_id=session_id)
    except Exception as e:
        logger.debug("goal_engine.tick_from_agent skipped: %s", e)


# ── Planner: next goal ───────────────────────────────────────────────────────────

def _parse_obj(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        s = m.group(0)
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def plan_next_goal(founder_id: str) -> dict[str, Any] | None:
    """Ask the planner LLM for the next company goal (objective + per-workstream
    tasks) and make it the new current goal. Returns the created goal or None."""
    from backend.missions.company_goal import get_company_goal, start_goal

    goal = get_company_goal(founder_id)
    if goal is None:
        return None
    north_star = goal.get("north_star") or goal.get("company_goal") or ""
    done_goals = [g.get("title") for g in (goal.get("goals") or []) if g.get("status") == "done"][-8:]
    ws_keys = ", ".join(WORKSTREAMS.keys())
    prompt = (
        "You are the operating planner for a startup that already launched. Decide the "
        "company's NEXT goal toward the north star — there is no 'finished'.\n\n"
        f"North star: {north_star}\n"
        f"Already-completed goals (do NOT repeat): {json.dumps(done_goals)}\n\n"
        "Write the next goal as a short objective plus 2-5 concrete major tasks, each "
        f"assigned to ONE workstream from: [{ws_keys}].\n"
        'Respond with ONLY JSON: {"title": "the goal", "tasks": [{"title": "task", '
        '"workstream": "<one of the workstreams>"}]}'
    )
    try:
        from backend.tools._llm import generate
        data = _parse_obj(generate(prompt, max_tokens=900, model="large"))
    except Exception as e:
        logger.warning("plan_next_goal LLM failed for %s: %s", founder_id, e)
        return None

    title = str(data.get("title") or "").strip()
    raw_tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    tasks: list[dict[str, Any]] = []
    for t in raw_tasks[:5]:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        ws = str(t.get("workstream") or "").lower().strip()
        owners = WORKSTREAMS.get(ws, {}).get("dispatch") or ["ops"]
        tasks.append({"title": str(t["title"])[:200], "owner_agents": list(owners)})
    if not title or not tasks:
        return None
    return start_goal(founder_id, title=title, tasks=tasks, kind="planner")


# ── Dispatch the current goal (run the agents that own its tasks) ────────────────

async def dispatch_current_goal(founder_id: str) -> dict[str, Any]:
    """Run the whole company on the current goal: continue_run with exactly the agents
    that own its open tasks, in a child session linked to the launch session."""
    from backend.core.session_ids import new_session_id
    from backend.missions.company_goal import (
        current_goal, get_company_goal, add_operating_session, update_operating_session,
    )

    goal = get_company_goal(founder_id)
    cg = current_goal(founder_id)
    if not goal or not cg:
        return {"ok": False, "reason": "no current goal"}
    open_tasks = [t for t in cg.get("tasks") or [] if not t.get("postponed") and t.get("status") != "done"]
    if not open_tasks:
        return {"ok": True, "skipped": "no open tasks"}

    owners = sorted({a for t in open_tasks for a in (t.get("owner_agents") or [])})
    root = goal.get("root_session_id") or goal.get("source_session_id") or ""
    session_id = new_session_id()
    instruction = (
        f"GOAL: {cg.get('title')}\n\nWork together to complete these major tasks:\n"
        + "\n".join(f"- {t.get('title')}" for t in open_tasks)
        + "\n\nEach agent: deliver real outputs for the task(s) you own; end with a clear summary."
    )
    try:
        from backend.core.session_store import register_session
        register_session(session_id=session_id, founder_id=founder_id, goal=instruction,
                         parent_session_id=root, kind="operating")
    except Exception:
        pass
    add_operating_session(founder_id, session_id, summary=cg.get("title", ""))

    try:
        from backend.core.factory import get_orchestrator
        orch = get_orchestrator()
        await orch.continue_run(
            instruction=instruction, founder_id=founder_id,
            prior_session_id=root or session_id, agents=owners or None, session_id=session_id,
        )
        update_operating_session(founder_id, session_id, status="done", summary=cg.get("title", ""))
        return {"ok": True, "session_id": session_id}
    except Exception as e:
        logger.error("dispatch_current_goal failed for %s: %s", founder_id, e, exc_info=True)
        update_operating_session(founder_id, session_id, status="error", summary=str(e)[:200])
        return {"ok": False, "session_id": session_id, "error": str(e)}


# ── End of a run: finalize + auto-chain to the next goal ─────────────────────────

async def after_run(founder_id: str, session_id: str, state: dict[str, Any]) -> None:
    """Called at goal_done. Upgrades the north star from the launch contract, then —
    if the current goal is now complete — plans the next goal and dispatches it
    (event-driven auto-chain; budget-gated to avoid runaway)."""
    if not founder_id:
        return
    from backend.missions.company_goal import (
        get_company_goal, upsert_company_goal, current_goal, budget_allows, _goal_is_complete,
    )
    try:
        goal = get_company_goal(founder_id)
        # Finalize north star / company name from the launch run's contract.
        ec = state.get("execution_contract") or (state.get("operating_plan") or {}).get("execution_contract") or {}
        north = ec.get("north_star")
        company = ((state.get("company_genome") or {}).get("company_name") or "").strip()
        if goal is not None and north and north != goal.get("north_star"):
            upsert_company_goal(
                founder_id, north_star=north,
                company_goal=goal.get("company_goal", ""),
                source_session_id=goal.get("source_session_id", session_id),
                status=goal.get("status", "operating"),
                kpis=list(ec.get("kpis") or goal.get("kpis") or []),
            )
        if company and goal is not None:
            cg = current_goal(founder_id)
            if cg and cg.get("kind") == "launch" and "company" in (cg.get("title", "").lower()):
                from backend.missions.company_goal import _lock, _read, _save
                with _lock:
                    g = _read(founder_id)
                    for go in g.get("goals") or []:
                        if go.get("id") == cg.get("id"):
                            go["title"] = f"Launch {company}"
                    _save(g)

        # Mirror to Notion (best-effort).
        try:
            from backend.tools.notion_sync import sync_founder_operating_system
            import asyncio
            await asyncio.to_thread(sync_founder_operating_system, founder_id)
        except Exception:
            pass

        # Auto-chain: goal complete → next goal → dispatch immediately.
        goal = get_company_goal(founder_id)
        if goal and goal.get("status") != "paused" and _goal_is_complete(current_goal(founder_id)):
            if not budget_allows(goal):
                logger.info("goal_engine: founder=%s goal complete but daily budget exhausted — not chaining", founder_id)
                return
            nxt = plan_next_goal(founder_id)
            if nxt:
                logger.info("goal_engine: founder=%s chained to next goal %r", founder_id, nxt.get("title"))
                await dispatch_current_goal(founder_id)
    except Exception as e:
        logger.warning("goal_engine.after_run failed for %s: %s", founder_id, e)

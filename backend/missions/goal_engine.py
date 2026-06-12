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

import asyncio
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


def _seed_company_identity(founder_id: str, goal_text: str, company_id: str | None = None) -> None:
    """Write a CANONICAL company-identity record into the brain from the founder's own
    launch description, so 'what does the company do / what are we selling' always has a
    grounded, authoritative answer (instead of the brain hallucinating a generic pitch)."""
    if not goal_text or not goal_text.strip():
        return
    try:
        text = goal_text.strip()
        name = ""
        m = re.search(r"[Cc]ompany(?:[ /](?:project|product))?\s+name[:\s]+\"?([A-Za-z][A-Za-z0-9 ]{1,40})", text)
        if m:
            name = m.group(1).strip()
        # Description = everything after the name line (the founder's own pitch).
        desc = re.sub(r"^[^\n]*[Cc]ompany(?:[ /](?:project|product))?\s+name[:\s][^\n]*\n+", "", text).strip() or text
        title = f"Company identity: {name}" if name else "Company identity"
        content = (f"{name} — " if name else "") + desc[:1500]
        from backend.tools.company_brain import add_company_brain_record
        add_company_brain_record(
            founder_id, source="company_identity", title=title, content=content,
            kind="identity", canonical=True, stale_risk="low",
            metadata={"company_name": name, "company_id": company_id or founder_id},
        )
        # Pin the name on the company record so child/operating runs can't rename it.
        if name:
            try:
                from backend.missions.company_goal import set_company_name
                set_company_name(founder_id, company_id, name)
            except Exception:
                pass
        logger.info("goal_engine: seeded company identity record for %s (%s)", founder_id, name or "?")
    except Exception as e:
        logger.warning("goal_engine._seed_company_identity failed for %s: %s", founder_id, e)


def _founder_for_session(session_id: str) -> str:
    try:
        from backend.core.session_store import get_session_meta
        return str((get_session_meta(session_id) or {}).get("founder_id") or "")
    except Exception:
        return ""


def _company_for_session(session_id: str, founder_id: str = "") -> str:
    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(session_id) or {}
        return str(meta.get("company_id") or founder_id or meta.get("founder_id") or "")
    except Exception:
        return founder_id


# ── Launch goal seeding (run start) ─────────────────────────────────────────────

def ensure_launch_goal(founder_id: str, session_id: str, agents: list[str], goal_text: str = "") -> None:
    """Idempotent: if the founder has no current goal, create the launch goal NOW
    (visible from run start) with one major task per workstream present in the plan."""
    if not founder_id:
        return
    from backend.missions.company_goal import (
        get_company_goal, reset_for_new_launch, start_goal, current_goal,
    )
    try:
        company_id = _company_for_session(session_id, founder_id)
        goal = get_company_goal(founder_id, company_id)
        # Re-entrant: this exact session already seeded the current goal → no-op
        # (avoids reseeding on replans within the same launch run).
        if goal and goal.get("root_session_id") == session_id and current_goal(founder_id, company_id):
            return
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

        # Fresh launch run = a new company → reset to a clean slate rooted at THIS
        # session, so /goals tracks the latest launch (not a stale earlier company).
        from backend.core.session_store import get_session_meta
        session_meta = get_session_meta(session_id) or {}
        # Wipe the brain + map ONLY when this launch is a genuinely DIFFERENT
        # company than the one already in the brain — re-running or continuing the
        # same company must NOT nuke its accumulated knowledge. Companies share one
        # founder scope, so without this guard launching company B erases company A.
        try:
            from backend.tools.company_brain import reset_company_brain, get_company_name as _brain_name
            new_name = ""
            m = re.search(r"[Cc]ompany(?:[ /](?:project|product))?\s+name[:\s]+\"?([A-Za-z0-9][A-Za-z0-9 .&-]{1,40})", goal_text or "")
            if m:
                new_name = m.group(1).strip().lower()
            # Brain is founder-scoped (graph/map/copilot all read founder-root).
            existing = (_brain_name(founder_id, company_id=founder_id) or "").strip().lower()
            same_company = bool(new_name and existing and (new_name == existing or new_name in existing or existing in new_name))
            if same_company:
                logger.info("goal_engine: same company %r — keeping brain+map", new_name)
            else:
                reset_company_brain(founder_id, founder_id)
                logger.info("goal_engine: reset brain+map for new company %s (was %r, now %r)",
                            founder_id, existing or "?", new_name or "?")
        except Exception as e:
            logger.warning("goal_engine: brain reset on launch failed for %s: %s", founder_id, e)
        reset_for_new_launch(
            founder_id, session_id,
            north_star=(goal_text or "Get the company on its feet")[:400],
            company_goal="Get the company launched and operating — all departments working together.",
            company_id=company_id,
        )
        start_goal(
            founder_id,
            title="Launch the company",
            tasks=tasks,
            kind="launch",
            company_id=company_id,
        )
        logger.info("goal_engine: reset+seeded launch goal for %s session=%s (%d tasks)", founder_id, session_id, len(tasks))
        # Seed identity at founder-root so the founder-scoped brain/map sees it.
        _seed_company_identity(founder_id, goal_text, founder_id)
    except Exception as e:
        logger.warning("goal_engine.ensure_launch_goal failed for %s: %s", founder_id, e)


# ── Event-driven task ticking (agent_done) ──────────────────────────────────────

def mark_running(session_id: str, agent: str) -> None:
    """An agent started — flip its current-goal task(s) to in_progress so the goal
    reads as running immediately. Called from the central publisher on agent_start."""
    try:
        founder_id = _founder_for_session(session_id)
        company_id = _company_for_session(session_id, founder_id)
        if not founder_id or not agent:
            return
        from backend.missions.company_goal import current_goal, mark_workstream_running
        cg = current_goal(founder_id, company_id)
        if cg and any(agent in (t.get("owner_agents") or []) for t in cg.get("tasks") or []):
            mark_workstream_running(founder_id, agent, company_id)
    except Exception as e:
        logger.debug("goal_engine.mark_running skipped: %s", e)


# An agent_done event does NOT prove the agent delivered. The forced-synthesis
# path (MAX_ITERATIONS) emits status="partial", and a hollow/empty output means
# the agent ran but produced nothing real. Refuse to check off a task in those
# cases — otherwise agents "complete" work they never actually did.
_NON_DELIVERY_STATUSES = {"partial", "error", "failed", "blocked", "incomplete", "timeout"}
_HOLLOW_PHRASES = (
    "placeholder", "lorem ipsum", "coming soon", "to be determined",
    "not provided", "unable to", "could not", "no output", "tbd",
)


def _agent_delivered(output: Any) -> bool:
    """Best-effort check that an agent_done payload represents real delivered work."""
    if output is None:
        # No payload at all (older callers / unknown path) — preserve prior
        # behavior and assume delivery rather than stalling the goal.
        return True
    if isinstance(output, str):
        text = output.strip()
        if len(text) < 12:
            return False
        return not any(p in text.lower() for p in _HOLLOW_PHRASES)
    if isinstance(output, dict):
        status = str(output.get("status") or "").lower().strip()
        if status in _NON_DELIVERY_STATUSES:
            return False
        # An output with literally no content fields is not a delivery.
        meaningful = {k: v for k, v in output.items() if k != "status" and v}
        if not meaningful:
            return False
        summary = str(output.get("summary") or "").lower()
        if summary and len(summary) < 12 and not (set(meaningful) - {"summary"}):
            return False
        return True
    return True


def tick_from_agent(session_id: str, agent: str, output: Any = None) -> None:
    """An agent finished — mark the current goal's tasks it owns, IF it actually
    delivered. Called from the central event publisher for every agent_done, so it
    must be cheap and safe."""
    try:
        founder_id = _founder_for_session(session_id)
        company_id = _company_for_session(session_id, founder_id)
        if not founder_id or not agent:
            return
        from backend.missions.company_goal import current_goal, complete_agent_workstream
        cg = current_goal(founder_id, company_id)
        if not cg:
            return
        # Only touch the store if this agent actually owns an open task.
        owns = any(agent in (t.get("owner_agents") or []) for t in cg.get("tasks") or [])
        if not owns:
            return
        if not _agent_delivered(output):
            # Agent ran but didn't deliver — leave the task open (it stays
            # in_progress via mark_running) instead of falsely checking it off.
            logger.info("goal_engine: %s emitted agent_done without real delivery — NOT completing task", agent)
            return
        complete_agent_workstream(
            founder_id,
            agent,
            run_id=session_id,
            company_id=company_id,
        )
    except Exception as e:
        logger.debug("goal_engine.tick_from_agent skipped: %s", e)


# ── Planner: next goal ───────────────────────────────────────────────────────────

def _parse_obj(raw: str) -> dict[str, Any]:
    from backend.core.json_extract import extract_json
    return extract_json(raw, prefer_keys=("title", "tasks"))


def plan_next_goal(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    """Ask the planner LLM for the next company goal (objective + per-workstream
    tasks) and make it the new current goal. Returns the created goal or None."""
    from backend.missions.company_goal import get_company_goal, start_goal

    goal = get_company_goal(founder_id, company_id)
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
    # Retry the planner once — a transient empty/garbled body shouldn't leave the
    # company permanently goal-less.
    title, tasks = "", []
    for _attempt in range(2):
        try:
            from backend.tools._llm import generate
            data = _parse_obj(generate(prompt, max_tokens=900, model="large"))
        except Exception as e:
            logger.warning("plan_next_goal LLM failed for %s (attempt %d): %s", founder_id, _attempt + 1, e)
            data = {}
        title = str(data.get("title") or "").strip()
        raw_tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        tasks = []
        for t in raw_tasks[:5]:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            ws = str(t.get("workstream") or "").lower().strip()
            owners = WORKSTREAMS.get(ws, {}).get("dispatch") or ["ops"]
            tasks.append({"title": str(t["title"])[:200], "owner_agents": list(owners)})
        if title and tasks:
            break

    # Deterministic fallback — if the planner keeps failing, the company must STILL get
    # a next goal (never silently stuck with no goal). A generic growth objective routed
    # across the core workstreams; the founder reviews/edits it like any proposal.
    if not title or not tasks:
        logger.warning("plan_next_goal: planner produced nothing for %s — using fallback goal", founder_id)
        title = "Grow traction: sharpen the product and reach more of the target customer"
        tasks = [
            {"title": "Talk to users and ship the highest-impact product improvements", "owner_agents": list(WORKSTREAMS["product"]["dispatch"])},
            {"title": "Run go-to-market experiments to grow qualified demand", "owner_agents": list(WORKSTREAMS["marketing"]["dispatch"])},
            {"title": "Build and work the sales pipeline from inbound interest", "owner_agents": list(WORKSTREAMS["sales"]["dispatch"])},
        ]
    # Planner goals are PROPOSED, not active — the founder must approve before the
    # team works them. (The launch goal is the only auto-active one.)
    return start_goal(
        founder_id,
        title=title,
        tasks=tasks,
        kind="planner",
        status="proposed",
        company_id=company_id,
    )


# ── Dispatch the current goal (run the agents that own its tasks) ────────────────

async def dispatch_current_goal(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Run the whole company on the current goal: continue_run with exactly the agents
    that own its open tasks, in a child session linked to the launch session."""
    from backend.core.session_ids import new_session_id
    from backend.missions.company_goal import (
        current_goal, get_company_goal, add_operating_session, update_operating_session, budget_allows,
    )

    goal = get_company_goal(founder_id, company_id)
    company_id = str((goal or {}).get("company_id") or company_id or founder_id)
    cg = current_goal(founder_id, company_id)
    if not goal or not cg:
        return {"ok": False, "reason": "no current goal"}
    # A proposed (not-yet-approved) goal must NOT run — the founder approves it first.
    if cg.get("status") != "active":
        return {"ok": True, "skipped": f"goal status {cg.get('status')!r} — needs approval"}
    if not budget_allows(goal):
        return {"ok": False, "reason": "operating budget exhausted"}
    all_tasks = [t for t in cg.get("tasks") or [] if not t.get("postponed")]
    open_tasks = [t for t in all_tasks if t.get("status") != "done"]
    if not open_tasks:
        return {"ok": True, "skipped": "no open tasks"}

    # A follow-up run = some of this goal's tasks are already done, so this dispatch is
    # finishing only the LEFTOVERS an earlier run didn't complete (e.g. an agent that
    # didn't deliver). Label it so the sub-run isn't mistaken for a duplicate of the goal.
    done_count = sum(1 for t in all_tasks if t.get("status") == "done")
    is_followup = done_count > 0 and done_count < len(all_tasks)
    title = cg.get("title", "")
    owners = sorted({a for t in open_tasks for a in (t.get("owner_agents") or [])})
    root = goal.get("root_session_id") or goal.get("source_session_id") or ""
    session_id = new_session_id()
    if is_followup:
        header = (
            f"FOLLOW-UP RUN for GOAL: {title}\n\n"
            f"An earlier run already completed {done_count} of {len(all_tasks)} tasks for this goal. "
            f"Finish ONLY the {len(open_tasks)} remaining task(s) below:\n"
        )
    else:
        header = f"GOAL: {title}\n\nWork together to complete these major tasks:\n"
    instruction = (
        header
        + "\n".join(f"- {t.get('title')}" for t in open_tasks)
        + "\n\nEach agent: deliver real outputs for the task(s) you own; end with a clear summary."
    )
    # Summary that distinguishes runs in the sub-run list: task count + follow-up marker.
    run_summary = (
        f"Follow-up · {len(open_tasks)} remaining task(s): {title}" if is_followup
        else f"{len(open_tasks)} task(s): {title}"
    )
    try:
        from backend.core.session_store import register_session
        from backend.core.session_store import get_session_meta
        root_meta = get_session_meta(root) or {}
        register_session(session_id=session_id, founder_id=founder_id, goal=instruction,
                         workspace_id=str(root_meta.get("workspace_id") or ""),
                         company_id=str(root_meta.get("company_id") or company_id),
                         parent_session_id=root, kind="operating")
    except Exception:
        pass
    add_operating_session(
        founder_id,
        session_id,
        summary=run_summary,
        goal_id=cg.get("id", ""),
        company_id=company_id,
    )

    try:
        from backend.core.factory import get_orchestrator
        orch = get_orchestrator()
        await orch.continue_run(
            instruction=instruction, founder_id=founder_id,
            prior_session_id=root or session_id, agents=owners or None, session_id=session_id,
        )
        update_operating_session(
            founder_id,
            session_id,
            company_id=company_id,
            status="done",
            summary=run_summary,
        )
        return {"ok": True, "session_id": session_id}
    except Exception as e:
        logger.error("dispatch_current_goal failed for %s: %s", founder_id, e, exc_info=True)
        update_operating_session(
            founder_id,
            session_id,
            company_id=company_id,
            status="error",
            summary=str(e)[:200],
        )
        return {"ok": False, "session_id": session_id, "error": str(e)}


# ── End of a run: finalize + auto-chain to the next goal ─────────────────────────

async def after_run(founder_id: str, session_id: str, state: dict[str, Any]) -> None:
    """Called at goal_done. Upgrades the north star from the launch contract, then —
    if the current goal is now complete — plans the next goal and dispatches it
    (event-driven auto-chain; budget-gated to avoid runaway)."""
    if not founder_id:
        return
    from backend.missions.company_goal import (
        get_company_goal, upsert_company_goal, current_goal, chain_allowed, _goal_is_complete,
    )
    try:
        company_id = _company_for_session(session_id, founder_id)
        goal = get_company_goal(founder_id, company_id)
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
                company_id=company_id,
            )
        if company and goal is not None:
            cg = current_goal(founder_id, company_id)
            if cg and cg.get("kind") == "launch" and "company" in (cg.get("title", "").lower()):
                from backend.missions.company_goal import _lock, _read, _save
                with _lock:
                    g = _read(founder_id, company_id)
                    for go in g.get("goals") or []:
                        if go.get("id") == cg.get("id"):
                            go["title"] = f"Launch {company}"
                    _save(g)

        # Mirror to Notion (best-effort).
        try:
            from backend.tools.notion_sync import sync_founder_operating_system
            import asyncio
            if company_id == founder_id:
                await asyncio.to_thread(sync_founder_operating_system, founder_id)
            else:
                await asyncio.to_thread(
                    sync_founder_operating_system,
                    founder_id,
                    company_id,
                )
        except Exception:
            pass

        # Goal complete → PROPOSE the next goal (do NOT auto-run it). Goals need human
        # sign-off: the planner writes the next objective, the founder approves it in the
        # /goals view, then it dispatches. This stops the runaway full-auto chain that
        # produced a pile of confusing back-to-back goals + sub-runs.
        goal = get_company_goal(founder_id, company_id)
        cur = current_goal(founder_id, company_id)
        # Propose the next goal when the current goal is complete. A completed goal's
        # status is already "done" (complete_agent_workstream flips it during ticking),
        # so guard on != "proposed" (don't stack a second proposal on an unapproved one)
        # — NOT == "active", which is never true by the time a goal finishes.
        if goal and goal.get("status") != "paused" and cur and cur.get("status") != "proposed" and _goal_is_complete(cur):
            if not chain_allowed(goal):
                logger.info("goal_engine: founder=%s goal complete but daily new-goal cap hit — not proposing", founder_id)
                return
            nxt = plan_next_goal(founder_id, company_id)
            if nxt:
                logger.info("goal_engine: founder=%s proposed next goal %r (awaiting approval)", founder_id, nxt.get("title"))
                try:
                    from backend.core.events import publish
                    await publish(session_id, {
                        "type": "goal_proposed",
                        "goal_id": nxt.get("id"),
                        "title": nxt.get("title"),
                        "tasks": [t.get("title") for t in nxt.get("tasks") or []],
                    })
                except Exception:
                    pass
    except Exception as e:
        logger.warning("goal_engine.after_run failed for %s: %s", founder_id, e)

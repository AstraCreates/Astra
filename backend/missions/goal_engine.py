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
        cid = str(meta.get("company_id") or founder_id or meta.get("founder_id") or "")
        # If the session's company_id is a workspace ID (ws_*) but no goal exists
        # under it, fall back to the founder-level goal file (company_id == founder_id).
        # This happens when child sessions inherit a workspace company_id but the
        # goal was created at the founder level.
        if cid and cid != founder_id and founder_id:
            from backend.missions.company_goal import get_company_goal
            if not get_company_goal(founder_id, cid):
                return founder_id
        return cid
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


# ── Business stage progression ───────────────────────────────────────────────────
# Stages gate what the planner proposes next. Advancement requires verified evidence,
# not self-reported claims.
BUSINESS_STAGES = ["pre_launch", "launched", "first_traction", "early_revenue", "growth"]

_STAGE_CONTEXT: dict[str, str] = {
    "pre_launch": (
        "Pre-launch: product not yet deployed. Focus: validate the idea with 5-10 real "
        "customer interviews, build and ship the MVP, set up legal/payments."
    ),
    "launched": (
        "Launched but no verified users yet. Focus: acquire the FIRST 10 real users "
        "(evidence: signup URL + count, onboarding call notes), collect qualitative "
        "feedback, fix the top 3 onboarding friction points."
    ),
    "first_traction": (
        "Has real users. Focus: convert the most engaged users to paying customers "
        "(evidence: Stripe payment, subscription ID), understand WHY they pay, "
        "reduce churn, grow to 25 paying customers."
    ),
    "early_revenue": (
        "Has paying customers. Focus: scale the acquisition channel that's working "
        "(evidence: CAC, conversion rate by channel), improve retention "
        "(evidence: cohort data), reach $1k MRR."
    ),
    "growth": (
        "Working revenue engine. Focus: double down on the highest-ROI channel, "
        "build team/systems to scale, hit the next revenue milestone."
    ),
}

# Tasks/outputs that claim real-world outcomes must carry verifiable evidence.
# Self-reported milestone completions are the primary hallucination vector.
_MILESTONE_PHRASES = frozenset((
    "first user", "first customer", "first sale", "first revenue",
    "first paying", "first sign", "100 users", "1000 users",
    "100 customer", "users signed", "paying customer", "monthly revenue",
    "mrr", "arr", "first dollar", "acquisition channel", "conversion rate",
    "go live", "launched the", "deployed to", "live on", "published to",
    "shipped to production", "on app store", "submitted to", "verified user",
    "active user", "returning user", "email list", "subscriber", "waitlist",
    "beta user", "get users", "acquire users", "onboard users", "sign up",
    "get signups", "get customers", "get paying",
))


def _task_requires_evidence(task_title: str) -> bool:
    """Tasks claiming real-world outcomes can't be self-reported — need URL/screenshot/payment."""
    t = (task_title or "").lower()
    return any(phrase in t for phrase in _MILESTONE_PHRASES)


def _infer_stage(goal: dict) -> str:
    """Infer current business stage from verified (evidence-backed) task notes."""
    notes_blob = " ".join(
        t.get("notes", "")
        for g in (goal.get("goals") or [])
        for t in (g.get("tasks") or [])
        if t.get("status") == "done"
    ).lower()
    completed_titles = " ".join(
        (g.get("title") or "").lower()
        for g in (goal.get("goals") or [])
        if g.get("status") == "done"
    )
    if any(w in notes_blob for w in ("revenue", "paying", "sale", "mrr", "first dollar", "stripe", "subscription")):
        return "early_revenue"
    if any(w in notes_blob for w in ("user", "signup", "subscriber", "waitlist", "beta", "onboard")):
        return "first_traction"
    if any(w in completed_titles for w in ("launch", "build", "deploy", "ship", "product")):
        return "launched"
    return "pre_launch"


# An agent_done event does NOT prove the agent delivered. The forced-synthesis
# path (MAX_ITERATIONS) emits status="partial", and a hollow/empty output means
# the agent ran but produced nothing real. Refuse to check off a task in those
# cases — otherwise agents "complete" work they never actually did.
_NON_DELIVERY_STATUSES = {"partial", "error", "failed", "blocked", "incomplete", "timeout"}
_HOLLOW_PHRASES = (
    "placeholder", "lorem ipsum", "coming soon", "to be determined",
    "not provided", "unable to", "could not", "no output", "tbd",
    "i was unable", "i could not", "no evidence", "could not verify",
    "hypothetical", "simulated", "as if", "pretend", "imagined",
)


def _agent_delivered(output: Any, task: dict | None = None) -> bool:
    """Best-effort check that an agent_done payload represents real delivered work.

    For tasks that claim real-world outcomes (users, revenue, deployments), the agent
    MUST include an evidence field (url, deploy_url, proof, etc.) — otherwise the task
    stays open. This is the primary guard against milestone hallucination.
    """
    task_title = str((task or {}).get("title", ""))
    requires_evidence = _task_requires_evidence(task_title)

    if output is None:
        if requires_evidence:
            logger.info(
                "goal_engine: task '%s' requires evidence but output is None — NOT completing task",
                task_title,
            )
            return False
        # Non-milestone tasks: no payload = older caller path, preserve prior behavior.
        return True

    if isinstance(output, str):
        text = output.strip()
        if len(text) < 12:
            return False
        if requires_evidence:
            # Plain string output cannot carry structured evidence — reject.
            logger.info(
                "goal_engine: task '%s' requires evidence but output is plain text — NOT completing",
                task_title,
            )
            return False
        return not any(p in text.lower() for p in _HOLLOW_PHRASES)

    if isinstance(output, dict):
        status = str(output.get("status") or "").lower().strip()
        if status in _NON_DELIVERY_STATUSES:
            return False
        if requires_evidence:
            evidence = (
                output.get("evidence")
                or output.get("proof")
                or output.get("url")
                or output.get("deploy_url")
                or output.get("live_url")
                or output.get("repo_url")
                or output.get("source")
                or output.get("signup_url")
                or output.get("payment_id")
                or output.get("stripe_id")
            )
            if not evidence:
                logger.info(
                    "goal_engine: task '%s' requires evidence — agent must include "
                    "url/deploy_url/evidence/proof in done output. NOT completing task.",
                    task_title,
                )
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
        agent_tasks = [t for t in cg.get("tasks") or [] if agent in (t.get("owner_agents") or [])]
        if not agent_tasks:
            return
        # Pass the task so _agent_delivered can enforce evidence requirements for
        # milestone tasks — e.g. "get first users" can't be self-reported.
        owning_task = agent_tasks[0]
        if not _agent_delivered(output, owning_task):
            logger.info(
                "goal_engine: %s emitted agent_done without real delivery for task '%s' — NOT completing",
                agent, owning_task.get("title", ""),
            )
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
    """Ask the planner LLM for the next company goal. Stage-aware: proposes goals
    appropriate to where the company actually is, with verifiable success criteria."""
    from backend.missions.company_goal import get_company_goal, start_goal

    goal = get_company_goal(founder_id, company_id)
    if goal is None:
        return None
    north_star = goal.get("north_star") or goal.get("company_goal") or ""
    done_goals = [g.get("title") for g in (goal.get("goals") or []) if g.get("status") == "done"][-6:]
    stage = _infer_stage(goal)
    stage_ctx = _STAGE_CONTEXT.get(stage, _STAGE_CONTEXT["pre_launch"])
    ws_keys = ", ".join(WORKSTREAMS.keys())

    # Build a summary of VERIFIED accomplishments (tasks marked done with notes/evidence)
    proven: list[str] = []
    for g in (goal.get("goals") or []):
        for t in (g.get("tasks") or []):
            if t.get("status") == "done":
                notes = (t.get("notes") or "").strip()
                proven.append(f"- {t.get('title', '')}" + (f": {notes[:180]}" if notes else " (completed)"))
    proven_text = "\n".join(proven[:10]) or "Nothing verified yet."

    prompt = (
        "You are the operating planner for an early-stage startup. "
        "Write the company's NEXT concrete goal based on its current stage.\n\n"
        f"North star: {north_star}\n"
        f"Current stage: {stage}\n"
        f"Stage guidance: {stage_ctx}\n\n"
        f"Verified accomplishments:\n{proven_text}\n\n"
        f"Already-completed goals (do NOT repeat): {json.dumps(done_goals)}\n\n"
        "RULES — follow exactly:\n"
        "1. Goals must be achievable by the specialist agents.\n"
        "2. Goals or tasks claiming users/customers/revenue MUST specify HOW the agent "
        "will provide evidence (e.g. 'deploy signup page and return live URL', "
        "'close 3 Stripe subscriptions and return payment IDs').\n"
        "3. Tasks must be concrete and verifiable — not vague ('run 10 outreach calls and log replies' "
        "not 'improve outreach').\n"
        "4. Each task has ONE workstream owner.\n"
        f"5. Propose 2-5 tasks. Workstreams: {ws_keys}\n\n"
        'Respond with ONLY valid JSON (no markdown, no explanation):\n'
        '{"title": "specific goal", "tasks": ['
        '{"title": "concrete verifiable task", "workstream": "<workstream>"}]}'
    )
    title, tasks = "", []
    for _attempt in range(2):
        try:
            from backend.tools._llm import generate
            data = _parse_obj(generate(prompt, max_tokens=1200, model="large"))
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

    # Stage-appropriate deterministic fallback — never leave the company goal-less.
    if not title or not tasks:
        logger.warning("plan_next_goal: planner produced nothing for %s (stage=%s) — using stage fallback", founder_id, stage)
        if stage == "pre_launch":
            title = "Validate and build: deploy the MVP and collect first real feedback"
            tasks = [
                {"title": "Interview 5 target customers and document key pain points with quotes", "owner_agents": list(WORKSTREAMS["research"]["dispatch"])},
                {"title": "Build and deploy the MVP — return live URL as evidence", "owner_agents": list(WORKSTREAMS["product"]["dispatch"])},
                {"title": "Set up waitlist landing page with email capture — return URL", "owner_agents": list(WORKSTREAMS["marketing"]["dispatch"])},
            ]
        elif stage == "launched":
            title = "Get first 10 real users: direct outreach, onboarding, and feedback"
            tasks = [
                {"title": "Run direct outreach to 50 ICP prospects, book 5 onboarding calls — log reply count and call URLs", "owner_agents": list(WORKSTREAMS["sales"]["dispatch"])},
                {"title": "Fix top onboarding friction so 10 users complete the core action — return session recordings or feedback doc URL", "owner_agents": list(WORKSTREAMS["product"]["dispatch"])},
                {"title": "Publish 3 pieces of content targeting ICP search intent — return published URLs", "owner_agents": list(WORKSTREAMS["marketing"]["dispatch"])},
            ]
        elif stage == "first_traction":
            title = "Convert active users to paying customers — first revenue milestone"
            tasks = [
                {"title": "Launch paid plan via Stripe, convert 3 active users — return Stripe payment IDs as evidence", "owner_agents": list(WORKSTREAMS["ops"]["dispatch"])},
                {"title": "Run 10 sales calls with engaged users, document willingness-to-pay and objections", "owner_agents": list(WORKSTREAMS["sales"]["dispatch"])},
                {"title": "Ship the #1 feature blocking paid conversion based on user feedback — return deploy URL", "owner_agents": list(WORKSTREAMS["product"]["dispatch"])},
            ]
        else:
            title = "Scale the acquisition channel that is working — grow MRR"
            tasks = [
                {"title": "Identify top-converting channel from data and double effort there — return channel metrics", "owner_agents": list(WORKSTREAMS["marketing"]["dispatch"])},
                {"title": "Build and work pipeline from inbound interest — log qualified leads and close rate", "owner_agents": list(WORKSTREAMS["sales"]["dispatch"])},
                {"title": "Ship retention improvement: reduce churn by addressing top exit reason — return before/after data", "owner_agents": list(WORKSTREAMS["product"]["dispatch"])},
            ]

    # Planner goals are PROPOSED — founder must approve before agents work them.
    return start_goal(
        founder_id, title=title, tasks=tasks, kind="planner", status="proposed",
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

    # Tasks requiring external evidence get an explicit callout — agents must include
    # url/deploy_url/evidence/proof in their done output or the task won't be marked done.
    evidence_tasks = [t for t in open_tasks if _task_requires_evidence(t.get("title", ""))]
    evidence_note = ""
    if evidence_tasks:
        evidence_note = (
            "\n\nEVIDENCE REQUIRED for the following tasks — include url/deploy_url/"
            "evidence/proof/payment_id in your done output. Do NOT claim completion "
            "without real verifiable proof; if blocked, state exactly what stops you:\n"
            + "\n".join(f"  * {t.get('title')}" for t in evidence_tasks)
        )
    instruction = (
        header
        + "\n".join(f"- {t.get('title')}" for t in open_tasks)
        + evidence_note
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

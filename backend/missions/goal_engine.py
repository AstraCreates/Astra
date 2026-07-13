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
import calendar
import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


def _running_session_is_fresh(session_id: str, fallback_started_at: str = "") -> bool:
    """True when session metadata says a run is active inside the stale window."""
    if not session_id:
        return False
    from backend.core.session_store import get_session_meta

    meta = get_session_meta(session_id) or {}
    if meta.get("status") != "running":
        return False
    ts = meta.get("created_at") or fallback_started_at or ""
    try:
        epoch = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return True
    stale_seconds = int(os.environ.get("ASTRA_RUN_STALE_SECONDS", "14400"))
    return (time.time() - epoch) < stale_seconds

# Workstream key → (task title, default specialist agents to dispatch for it).
# Default (SaaS/idea-to-revenue).
WORKSTREAMS: dict[str, dict[str, Any]] = {
    "research":  {"title": "Validate market & ICP", "dispatch": ["research"]},
    "product":   {"title": "Build product & landing", "dispatch": ["web", "technical"]},
    "marketing": {"title": "Go-to-market assets", "dispatch": ["marketing"]},
    "sales":     {"title": "Sales pipeline", "dispatch": ["sales"]},
    "legal":     {"title": "Legal foundation", "dispatch": ["legal"]},
    "ops":       {"title": "Operating plan", "dispatch": ["ops"]},
}

# Business-type-specific workstream titles — same keys, different names/dispatch per model.
WORKSTREAMS_BY_TYPE: dict[str, dict[str, dict[str, Any]]] = {
    "ecomm": {
        "research":  {"title": "Market & competitor research (ecomm)", "dispatch": ["research"]},
        "product":   {"title": "Build ecomm store (Medusa.js)", "dispatch": ["web", "technical"]},
        "marketing": {"title": "Email flows & paid acquisition (Klaviyo)", "dispatch": ["marketing"]},
        "sales":     {"title": "Product catalog & pricing strategy", "dispatch": ["sales"]},
        "legal":     {"title": "Store legal docs (returns, privacy, ToS)", "dispatch": ["legal"]},
        "ops":       {"title": "Fulfillment & ops setup (Printful/Square)", "dispatch": ["ops"]},
    },
    "local": {
        "research":  {"title": "Local market & competitor analysis", "dispatch": ["research"]},
        "product":   {"title": "Build booking site (Cal.com embed)", "dispatch": ["web"]},
        "marketing": {"title": "Google Business, social & local ads", "dispatch": ["marketing"]},
        "sales":     {"title": "Service menu, memberships & retention", "dispatch": ["sales"]},
        "legal":     {"title": "Service agreements, waivers & compliance", "dispatch": ["legal"]},
        "ops":       {"title": "Booking & payments (Square/Cal.com)", "dispatch": ["ops"]},
    },
    "agency": {
        "research":  {"title": "Niche, ICP & competitor research", "dispatch": ["research"]},
        "product":   {"title": "Service packages, case study page & proposal templates", "dispatch": ["web"]},
        "marketing": {"title": "Outbound campaigns & case study content", "dispatch": ["marketing"]},
        "sales":     {"title": "Proposal pipeline, pricing & close playbook", "dispatch": ["sales"]},
        "legal":     {"title": "Client agreements, SOW & NDA templates", "dispatch": ["legal"]},
        "ops":       {"title": "Client onboarding, delivery & retainer ops", "dispatch": ["ops"]},
    },
    "content": {
        "research":  {"title": "Audience, topic & monetization research", "dispatch": ["research"]},
        "product":   {"title": "Newsletter / content platform setup", "dispatch": ["web"]},
        "marketing": {"title": "Content calendar, SEO & distribution", "dispatch": ["marketing"]},
        "sales":     {"title": "Sponsorship, affiliate & paid tiers strategy", "dispatch": ["sales"]},
        "legal":     {"title": "Content IP, creator agreements & DMCA", "dispatch": ["legal"]},
        "ops":       {"title": "Digital product setup & payments (Lemon Squeezy)", "dispatch": ["ops"]},
    },
}


def _extract_business_type(text: str) -> str:
    """Extract business type slug from quiz context block or instruction text.
    Returns: 'ecomm' | 'local' | 'agency' | 'content' | 'saas'"""
    t = (text or "").lower()
    # Quiz contextBlock always starts "Business type: <label>"
    m = re.search(r"business type:\s*([^\n—–]+)", t)
    if m:
        raw = m.group(1).strip()
        if any(w in raw for w in ("ecomm", "store", "shop", "print-on-demand", "digital product", "subscription box")):
            return "ecomm"
        if any(w in raw for w in ("local", "salon", "gym", "restaurant", "cleaning", "tutoring", "fitness", "beauty", "food")):
            return "local"
        if any(w in raw for w in ("agency", "consult", "freelance")):
            return "agency"
        if any(w in raw for w in ("content", "creator", "newsletter", "media", "community")):
            return "content"
    # Fallback: scan the whole instruction for strong signals
    if "medusa" in t or "printful" in t or "shopify" in t or "ecommerce" in t or "online store" in t:
        return "ecomm"
    if "booking site" in t or "cal.com" in t or "square appointments" in t or "local service" in t:
        return "local"
    if "agency" in t or "consulting" in t or "client work" in t or "freelance" in t:
        return "agency"
    if "newsletter" in t or "substack" in t or "content creator" in t:
        return "content"
    return "saas"


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
        m = re.search(r"[Cc]ompany(?:[ /](?:project|product))?\s+name\s*:\s*\"?([^\n\"]{1,80})", text)
        if m:
            name = m.group(1).strip().rstrip('"').strip()
        # Description = everything after the name line (the founder's own pitch).
        desc = re.sub(r"^[^\n]*[Cc]ompany(?:[ /](?:project|product))?\s+name[:\s][^\n]*\n+", "", text).strip() or text
        title = f"Company identity: {name}" if name else "Company identity"
        # No local cap — this becomes the canonical (most-trusted) identity record
        # every agent grounds against; _record()'s 50k ceiling is the only limit
        # that should apply, not a second, tighter one truncating the founder's
        # own pitch before it's even stored.
        content = (f"{name} — " if name else "") + desc
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
        # Determine business type from quiz context block in goal_text.
        biz_type = _extract_business_type(goal_text or "")
        ws_map = WORKSTREAMS_BY_TYPE.get(biz_type, WORKSTREAMS)
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
        for key in ws_map:
            if key in by_ws:
                tasks.append({"title": ws_map[key]["title"], "owner_agents": by_ws[key]})
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
        # Detect whether this is a continuation of an existing business (has GitHub/live URL).
        existing_context = bool(
            re.search(r"existing business context:", goal_text or "", re.IGNORECASE)
            or re.search(r"github repo:\s*https?://", goal_text or "", re.IGNORECASE)
        )
        launch_title = (
            "Continue growing the business" if existing_context
            else "Launch the company"
        )
        reset_for_new_launch(
            founder_id, session_id,
            north_star=(goal_text or "Get the company on its feet")[:400],
            company_goal=(
                "Extend the existing business — pick up from current state and drive growth."
                if existing_context
                else "Get the company launched and operating — all departments working together."
            ),
            company_id=company_id,
        )
        # Persist business type so planner can use it for all future goals.
        try:
            from backend.missions.company_goal import get_company_goal, _goal_lock, _read, _save
            with _goal_lock(founder_id, company_id):
                g = _read(founder_id, company_id)
                if g is not None:
                    g["business_type"] = biz_type
                    g["is_existing_business"] = existing_context
                    _save(g)
        except Exception:
            pass
        # Pre-pin GitHub repo from existing business context so technical/web agents
        # build on top of it rather than creating a new repo from scratch.
        try:
            m_repo = re.search(r"github repo:\s*(https?://\S+)", goal_text or "", re.IGNORECASE)
            if m_repo:
                from backend.missions.company_goal import set_company_repo
                set_company_repo(founder_id, company_id, repo_url=m_repo.group(1).strip())
        except Exception:
            pass
        start_goal(
            founder_id,
            title=launch_title,
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
        "feedback after the live product is in users' hands, fix the top 3 onboarding friction points. "
        "This is a post-launch stage, not a time-based waiting period."
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
# Document/plan tasks: agent must return actual content, not just a summary blurb.
# Without this, agents can check off "Draft a hiring plan" by saying "I drafted a plan."
_DOCUMENT_STEMS = (
    "draft ", "write ", "create ", "generate ", "produce ", "build ",
    "develop ", "prepare ", "design ", "outline ", "compose ",
)
_DOCUMENT_NOUNS = (
    "plan", "doc", "document", "report", "proposal", "strategy",
    "roadmap", "policy", "agreement", "template", "playbook",
    "brief", "spec", "framework", "analysis", "assessment", "guide",
)

# Self-reported milestone completions are the primary hallucination vector.
# Use word stems/prefixes so variants like "signups", "signed up", "users" all match.
_MILESTONE_STEMS = (
    "first user", "first customer", "first sale", "first revenue",
    "first paying", "first sign", "100 user", "1000 user",
    "100 customer", "users signed", "paying customer", "monthly revenue",
    "mrr", "arr", "first dollar", "acquisition channel", "conversion rate",
    "go live", "launched the", "deployed to", "live on", "published to",
    "shipped to production", "on app store", "submitted to", "verified user",
    "active user", "returning user", "email list", "subscrib", "waitlist",
    "beta user", "get user", "acquire user", "onboard user", "sign up",
    "signup", "signups", "signed up", "new signup", "real user",
    "get signup", "get customer", "get paying", "send survey", "survey to",
    "collect feedback from", "onboarding feedback", "real signup",
)


def _task_requires_evidence(task_title: str) -> bool:
    """Tasks claiming real-world outcomes can't be self-reported — need URL/screenshot/payment."""
    t = (task_title or "").lower()
    return any(stem in t for stem in _MILESTONE_STEMS)


def _task_requires_document(task_title: str) -> bool:
    """Tasks that say 'draft/write/create a plan/doc' require actual content, not just a summary."""
    t = (task_title or "").lower()
    has_action = any(stem in t for stem in _DOCUMENT_STEMS)
    has_noun = any(noun in t for noun in _DOCUMENT_NOUNS)
    return has_action and has_noun


def _max_content_length(output: dict) -> int:
    """Longest text value in the output dict (excluding agent/status/session metadata)."""
    _SKIP = {"status", "agent", "session_id", "task_id", "founder_id", "company_id"}
    best = 0
    for k, v in output.items():
        if k in _SKIP:
            continue
        if isinstance(v, str):
            best = max(best, len(v.strip()))
        elif isinstance(v, (dict, list)):
            best = max(best, len(str(v)))
    return best


def _infer_stage(goal: dict) -> str:
    """Infer current business stage conservatively — only advance on verified external evidence.

    Words like 'signup' and 'user' are freely written by agents in outreach plans and
    email templates. Stage must NOT advance on notes alone; it needs a completed goal
    whose title itself is a real-world milestone (not just prep work)."""
    completed_titles = " ".join(
        (g.get("title") or "").lower()
        for g in (goal.get("goals") or [])
        if g.get("status") == "done"
    )
    launched = any(w in completed_titles for w in ("launch", "build", "deploy", "ship", "product"))
    # Revenue milestone: completed goal mentions revenue/paying/stripe in title
    revenue_words = ("revenue", "paying customer", "mrr", "first sale", "stripe", "first dollar")
    if any(w in completed_titles for w in revenue_words):
        return "early_revenue"
    # Traction milestone: only after the product is actually launched/built.
    # Waiting for outreach replies is a post-launch phase, not a clock-based one.
    traction_title_words = ("first user", "first signup", "real user", "real signup",
                            "10 real", "10 user", "10 signup", "user signup")
    if any(w in completed_titles for w in traction_title_words):
        return "first_traction" if launched else "pre_launch"
    # Launched: a build/deploy/launch goal completed
    if launched:
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
            t_lower = task_title.lower()
            _is_user_task = any(w in t_lower for w in (
                "signup", "signups", "sign up", "user signup", "real user", "real signup",
                "10 real", "onboard", "survey to", "collect feedback from", "first user",
                "acquire user", "get user", "get signup",
            ))
            if _is_user_task:
                # User-acquisition outcomes: plain text can't carry verifiable proof.
                logger.info(
                    "goal_engine: task '%s' requires user evidence but output is plain text — NOT completing",
                    task_title,
                )
                return False
            # Non-user milestone tasks (deploys, content, etc.): accept a substantial
            # string that contains a URL or evidence marker.
            import re as _re
            has_url = bool(_re.search(r'https?://\S+', text))
            if len(text) >= 60 or has_url:
                return not any(p in text.lower() for p in _HOLLOW_PHRASES)
            logger.info(
                "goal_engine: task '%s' requires evidence — string too short/no URL — NOT completing",
                task_title,
            )
            return False
        return not any(p in text.lower() for p in _HOLLOW_PHRASES)

    if isinstance(output, dict):
        status = str(output.get("status") or "").lower().strip()
        if status in _NON_DELIVERY_STATUSES:
            return False
        if requires_evidence:
            # User-acquisition tasks need signup/payment proof, NOT just a repo/deploy URL.
            # repo_url and deploy_url are build artifacts that agents always have — accepting
            # them as evidence for "acquire users" lets agents hallucinate traction.
            t_lower = task_title.lower()
            _is_user_task = any(w in t_lower for w in (
                "signup", "signups", "sign up", "user signup", "real user", "real signup",
                "10 real", "onboard", "survey to", "collect feedback from", "first user",
                "acquire user", "get user", "get signup",
            ))
            if _is_user_task:
                # Only strong real-world proof accepted.
                # signup_count/user_count alone are hallucination-prone;
                # require them paired with a verifiable URL or payment ID.
                _has_url = output.get("signup_url") or output.get("payment_id") or output.get("stripe_id")
                _has_count = output.get("signup_count") or output.get("user_count")
                evidence = (
                    output.get("evidence")
                    or output.get("proof")
                    or _has_url
                    or (_has_count and _has_url)
                )
            else:
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
        # Document tasks ("draft a plan", "write a report") require actual content in output,
        # not just a short summary blurb. Without this gate, agents check off "Draft a hiring
        # plan" by returning {"summary": "I created a hiring plan."} — no document anywhere.
        requires_doc = _task_requires_document(task_title)
        if requires_doc:
            max_len = _max_content_length(output)
            if max_len < 300:
                logger.info(
                    "goal_engine: task '%s' requires document content but longest field is only %d chars"
                    " — NOT completing task",
                    task_title, max_len,
                )
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
        # Per-task evidence gate: complete tasks where evidence is present, skip the rest.
        # (Previously all-or-nothing — one blocked task prevented all others from completing.)
        deliverable_ids: set[str] = set()
        for t in agent_tasks:
            if _agent_delivered(output, t):
                deliverable_ids.add(str(t.get("id", "")))
            else:
                logger.info(
                    "goal_engine: %s emitted agent_done without real delivery for task '%s' — NOT completing",
                    agent, t.get("title", ""),
                )
        if not deliverable_ids:
            return
        complete_agent_workstream(
            founder_id,
            agent,
            run_id=session_id,
            company_id=company_id,
            task_ids=deliverable_ids if len(deliverable_ids) < len(agent_tasks) else None,
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
    biz_type = str(goal.get("business_type") or "saas")
    ws_map = WORKSTREAMS_BY_TYPE.get(biz_type, WORKSTREAMS)
    ws_keys = ", ".join(ws_map.keys())
    biz_label = {"ecomm": "Ecommerce", "local": "Local service", "agency": "Agency/consulting",
                 "content": "Content/creator", "saas": "SaaS/app"}.get(biz_type, "SaaS/app")
    is_existing = bool(goal.get("is_existing_business"))

    # Build a summary of VERIFIED accomplishments (tasks marked done with notes/evidence)
    proven: list[str] = []
    for g in (goal.get("goals") or []):
        for t in (g.get("tasks") or []):
            if t.get("status") == "done":
                notes = (t.get("notes") or "").strip()
                proven.append(f"- {t.get('title', '')}" + (f": {notes[:180]}" if notes else " (completed)"))
    proven_text = "\n".join(proven[:10]) or "Nothing verified yet."

    existing_note = (
        "This is a CONTINUATION of an existing business (not a fresh start). "
        "The company already has some infrastructure (code, site, customers). "
        "Focus on building on what exists, not rebuilding from scratch.\n"
        if is_existing else ""
    )
    prompt = (
        "You are the operating planner for an early-stage startup. "
        "Write the company's NEXT concrete goal based on its current stage and business model.\n\n"
        f"North star: {north_star}\n"
        f"Business type: {biz_label}\n"
        f"Current stage: {stage}\n"
        f"Stage guidance: {stage_ctx}\n"
        f"{existing_note}"
        f"\nVerified accomplishments:\n{proven_text}\n\n"
        f"Already-completed goals (do NOT repeat): {json.dumps(done_goals)}\n\n"
        "AGENT CAPABILITIES (hard limits — do NOT propose goals outside these boundaries):\n"
        "- Sales agent CAN: find real lead prospects via web search, build email sequences, send emails if Gmail is connected.\n"
        "  Sales agent CANNOT: verify anyone became a paying client, sign contracts, confirm onboarding, collect payment.\n"
        "  → Valid goal: 'Build outreach pipeline for 20 qualified leads with personalized email sequences'\n"
        "  → INVALID goal: 'Acquire 10 verified clients' or 'Close retainer agreements' (requires human action)\n"
        "- Web/Technical agent CAN: build and deploy a real product with a live URL.\n"
        "  → Valid goal: 'Build and deploy MVP — return live URL'\n"
        "  → INVALID goal: 'Get 10 users on the product' before a product exists\n"
        "- Marketing agent CAN: create content, send campaigns if email tool connected, run ads if API connected.\n"
        "  → INVALID goal: 'Retain 10 users' (retention requires a product + human interaction)\n"
        "- Goals about revenue, clients, users, bookings are ONLY valid if a product is already deployed (live URL confirmed).\n\n"
        "RULES — follow exactly:\n"
        "1. Goals must be within agent capabilities above — no goals requiring human confirmation.\n"
        "2. Goals claiming users/orders/bookings/revenue MUST specify HOW the agent provides evidence "
        "(e.g. 'return live store URL', 'return Stripe payment ID', 'return signup count from analytics').\n"
        "   Outreach replies, onboarding feedback, and other traction work only happen AFTER a verified live product exists.\n"
        "3. Tasks must be concrete and verifiable for THIS business type — "
        f"for {biz_label}: focus on what matters (e.g. for ecomm: store, SKUs, email flows; "
        "for local: bookings, reviews, local SEO; for agency: proposals, retainers; "
        "for content: subscriber count, monetization).\n"
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
            owners = ws_map.get(ws, WORKSTREAMS.get(ws, {})).get("dispatch") or ["ops"]
            tasks.append({"title": str(t["title"])[:200], "owner_agents": list(owners)})
        if title and tasks:
            break

    # Stage + biz-type-appropriate deterministic fallback — never leave the company goal-less.
    if not title or not tasks:
        logger.warning("plan_next_goal: planner produced nothing for %s (stage=%s biz=%s) — using fallback", founder_id, stage, biz_type)
        _prod = list(ws_map.get("product", WORKSTREAMS["product"])["dispatch"])
        _mkt  = list(ws_map.get("marketing", WORKSTREAMS["marketing"])["dispatch"])
        _sales = list(ws_map.get("sales", WORKSTREAMS["sales"])["dispatch"])
        _ops  = list(ws_map.get("ops", WORKSTREAMS["ops"])["dispatch"])
        _res  = list(ws_map.get("research", WORKSTREAMS["research"])["dispatch"])

        if biz_type == "ecomm":
            if stage in ("pre_launch", "launched"):
                title = "Set up ecomm store and get first 5 orders"
                tasks = [
                    {"title": "Build and deploy Medusa.js store with product catalog — return live store URL", "owner_agents": _prod},
                    {"title": "Set up Klaviyo welcome flow and abandoned-cart email — return flow URL", "owner_agents": _mkt},
                    {"title": "Run 30 DM outreach on Instagram/TikTok, drive 5 first orders — return order IDs", "owner_agents": _sales},
                ]
            elif stage == "first_traction":
                title = "Drive first 50 orders and set up repeat-purchase flows"
                tasks = [
                    {"title": "Launch paid Meta/TikTok ad campaign for best-selling product — return ad URL + spend", "owner_agents": _mkt},
                    {"title": "Set up post-purchase email flow (review ask + cross-sell) — return flow URL", "owner_agents": _ops},
                    {"title": "Add 10 new SKUs based on top-selling category research", "owner_agents": _res},
                ]
            else:
                title = "Scale ecomm: double best-performing channel and hit $10k MRR"
                tasks = [
                    {"title": "Scale winning ad creative: increase budget on top ad — return ROAS improvement", "owner_agents": _mkt},
                    {"title": "Set up subscription / bundle upsell flow — return AOV before/after", "owner_agents": _ops},
                    {"title": "Negotiate better fulfillment terms with Printful — return cost reduction", "owner_agents": _res},
                ]
        elif biz_type == "local":
            if stage in ("pre_launch", "launched"):
                title = "Launch booking site and get first 10 appointments booked"
                tasks = [
                    {"title": "Build and deploy Cal.com booking site — return live booking URL", "owner_agents": _prod},
                    {"title": "Optimise Google Business Profile and request 10 reviews from past clients — return GBP URL", "owner_agents": _mkt},
                    {"title": "Run local Instagram promotion and DM 50 local accounts — return booking count", "owner_agents": _sales},
                ]
            elif stage == "first_traction":
                title = "Grow to 40 monthly bookings and launch membership tier"
                tasks = [
                    {"title": "Launch monthly membership package via Square — return subscription activation link", "owner_agents": _ops},
                    {"title": "Set up SMS reminder + review-ask flow via Twilio — return flow and first send proof", "owner_agents": _mkt},
                    {"title": "Run Google Local Services Ad campaign — return ad URL and click data", "owner_agents": _sales},
                ]
            else:
                title = "Scale bookings and launch referral program"
                tasks = [
                    {"title": "Build refer-a-friend program (gift card reward) — return program URL", "owner_agents": _ops},
                    {"title": "Increase paid local ad budget on best-performing campaign — return revenue uplift", "owner_agents": _mkt},
                    {"title": "Add new service tier / premium package — return updated pricing page URL", "owner_agents": _sales},
                ]
        elif biz_type == "agency":
            if stage in ("pre_launch", "launched"):
                title = "Land first 3 paying clients"
                tasks = [
                    {"title": "Create service packages page and proposal template — return live URL", "owner_agents": _prod},
                    {"title": "Run 50-prospect LinkedIn outreach campaign, book 5 discovery calls — log reply rate and call links", "owner_agents": _sales},
                    {"title": "Publish 2 case studies / before-after pieces — return published URLs", "owner_agents": _mkt},
                ]
            elif stage == "first_traction":
                title = "Convert project clients to monthly retainers — hit $5k MRR"
                tasks = [
                    {"title": "Build retainer proposal and present to top 3 active clients — return signed doc", "owner_agents": _sales},
                    {"title": "Set up monthly reporting template and client dashboard — return Notion/doc URL", "owner_agents": _ops},
                    {"title": "Launch referral program for existing clients — return program doc", "owner_agents": _mkt},
                ]
            else:
                title = "Scale agency: systematise delivery and hire first subcontractor"
                tasks = [
                    {"title": "Build delivery SOPs for top 2 service lines — return doc URLs", "owner_agents": _ops},
                    {"title": "Create subcontractor onboarding guide and rate card — return doc", "owner_agents": _res},
                    {"title": "Run targeted LinkedIn + content campaign to fill next 3 slots — log leads", "owner_agents": _mkt},
                ]
        elif biz_type == "content":
            if stage in ("pre_launch", "launched"):
                title = "Launch newsletter and hit 500 subscribers"
                tasks = [
                    {"title": "Set up newsletter platform (Beehiiv/Ghost) and landing page — return subscribe URL", "owner_agents": _prod},
                    {"title": "Publish 4 cornerstone pieces and promote to target audience — return URLs + subscriber count", "owner_agents": _mkt},
                    {"title": "Set up digital product storefront (Lemon Squeezy) — return store URL", "owner_agents": _ops},
                ]
            elif stage == "first_traction":
                title = "Monetise audience: first paid product or sponsorship deal"
                tasks = [
                    {"title": "Launch first paid digital product (template, course, or guide) — return Lemon Squeezy product URL", "owner_agents": _ops},
                    {"title": "Outreach to 10 potential sponsors in the niche — log reply rate and first deal terms", "owner_agents": _sales},
                    {"title": "Publish 6 SEO-targeted pieces to grow organic subscribers — return published URLs", "owner_agents": _mkt},
                ]
            else:
                title = "Scale revenue: grow paid tiers and increase sponsorship rates"
                tasks = [
                    {"title": "Launch premium subscriber tier with exclusive content — return tier URL + conversion rate", "owner_agents": _ops},
                    {"title": "Increase sponsorship rates based on audience growth — return new rate card and 2 signed deals", "owner_agents": _sales},
                    {"title": "Build SEO content cluster around top-traffic topic — return traffic growth data", "owner_agents": _mkt},
                ]
        # SaaS default
        elif stage == "pre_launch":
            title = "Validate and build: deploy the MVP and collect first real feedback"
            tasks = [
                {"title": "Interview 5 target customers and document key pain points with quotes", "owner_agents": _res},
                {"title": "Build and deploy the MVP — return live URL as evidence", "owner_agents": _prod},
                {"title": "Set up waitlist landing page with email capture — return URL", "owner_agents": _mkt},
            ]
        elif stage == "launched":
            title = "Get first 10 real users: direct outreach, onboarding, and feedback"
            tasks = [
                {"title": "Run direct outreach to 50 ICP prospects, book 5 onboarding calls — log reply count", "owner_agents": _sales},
                {"title": "Fix top onboarding friction so 10 users complete core action — return feedback doc URL", "owner_agents": _prod},
                {"title": "Publish 3 pieces of content targeting ICP search intent — return published URLs", "owner_agents": _mkt},
            ]
        elif stage == "first_traction":
            title = "Convert active users to paying customers — first revenue milestone"
            tasks = [
                {"title": "Launch paid plan via Stripe, convert 3 active users — return Stripe payment IDs", "owner_agents": _ops},
                {"title": "Run 10 sales calls with engaged users, document willingness-to-pay and objections", "owner_agents": _sales},
                {"title": "Ship the #1 feature blocking paid conversion — return deploy URL", "owner_agents": _prod},
            ]
        else:
            title = "Scale the acquisition channel that is working — grow MRR"
            tasks = [
                {"title": "Identify top-converting channel and double effort there — return channel metrics", "owner_agents": _mkt},
                {"title": "Build and work pipeline from inbound interest — log qualified leads and close rate", "owner_agents": _sales},
                {"title": "Ship retention improvement: reduce churn by addressing top exit reason — return before/after data", "owner_agents": _prod},
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
    _pre_session_id: str = "",
) -> dict[str, Any]:
    """Run the whole company on the current goal: continue_run with exactly the agents
    that own its open tasks, in a child session linked to the launch session."""
    from backend.core.session_ids import new_session_id
    from backend.missions.company_goal import (
        _goal_lock, _read, _save, current_goal, get_company_goal, update_operating_session, budget_allows,
    )

    goal = get_company_goal(founder_id, company_id)
    company_id = str((goal or {}).get("company_id") or company_id or founder_id)
    session_id = _pre_session_id or new_session_id()
    try:
        with _goal_lock(founder_id, company_id):
            goal = _read(founder_id, company_id)
            cg = current_goal(founder_id, company_id)
            if not goal or not cg:
                return {"ok": False, "reason": "no current goal"}
            if cg.get("status") != "active":
                return {"ok": True, "skipped": f"goal status {cg.get('status')!r} — needs approval"}
            if not budget_allows(goal):
                return {"ok": False, "reason": "operating budget exhausted"}
            all_tasks = [t for t in cg.get("tasks") or [] if not t.get("postponed")]
            open_tasks = [t for t in all_tasks if t.get("status") != "done"]
            if not open_tasks:
                return {"ok": True, "skipped": "no open tasks"}

            current_goal_id = cg.get("id", "")
            root_sid = str(goal.get("root_session_id") or goal.get("source_session_id") or "")
            if root_sid and _running_session_is_fresh(root_sid):
                logger.info("dispatch_current_goal: root session %s still running — skipping dispatch to avoid duplicate agent runs", root_sid)
                return {"ok": True, "skipped": "root_session_running", "session_id": root_sid}

            for rec in (goal.get("operating_sessions") or []):
                if rec.get("goal_id") != current_goal_id or rec.get("status") != "running":
                    continue
                existing_sid = rec.get("session_id", "")
                if _running_session_is_fresh(existing_sid, str(rec.get("started_at") or "")):
                    logger.info("dispatch_current_goal: session %s already running for goal %s — skipping duplicate", existing_sid, current_goal_id)
                    return {"ok": True, "skipped": "already_running", "session_id": existing_sid}

            run_summary_seed = f"{len(open_tasks)} task(s): {cg.get('title', '')}"
            runs = goal.setdefault("operating_sessions", [])
            runs.append({
                "session_id": session_id,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "status": "running",
                "summary": run_summary_seed,
                "goal_id": current_goal_id,
            })
            goal["operating_sessions"] = runs[-50:]
            _save(goal)
    except Exception as exc:
        logger.warning("dispatch_current_goal duplicate-check failed: %s", exc)
        return {"ok": False, "reason": "dispatch reservation failed", "error": str(exc)}

    # Register this dispatch's own task so /sessions/{id}/kill can actually stop it.
    # Callers fire this via asyncio.create_task(dispatch_current_goal(...)) with no
    # registration afterward, so auto-chained continue_run dispatches were previously
    # unkillable through the exposed kill switch (cancellation._tasks had no entry for
    # them). asyncio.current_task() from inside the coroutine is that task.
    try:
        _current_task = asyncio.current_task()
        if _current_task:
            from backend.core import cancellation
            cancellation.register_task(session_id, _current_task)
    except Exception:
        pass

    # A follow-up run = some of this goal's tasks are already done, so this dispatch is
    # finishing only the LEFTOVERS an earlier run didn't complete (e.g. an agent that
    # didn't deliver). Label it so the sub-run isn't mistaken for a duplicate of the goal.
    done_count = sum(1 for t in all_tasks if t.get("status") == "done")
    is_followup = done_count > 0 and done_count < len(all_tasks)
    title = cg.get("title", "")
    owners = sorted({a for t in open_tasks for a in (t.get("owner_agents") or [])})
    root = goal.get("root_session_id") or goal.get("source_session_id") or ""
    # Use the most recent completed sub-run as prior context so agents see intermediate
    # progress, not just the original launch session (which has no follow-up outputs).
    done_ops = [
        r for r in (goal.get("operating_sessions") or [])
        if r.get("goal_id") == cg.get("id") and r.get("status") == "done" and r.get("session_id")
    ]
    prior_sid = done_ops[-1]["session_id"] if done_ops else (root or session_id)
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
        from backend.core.session_store import register_session, get_session_meta
        root_meta = get_session_meta(root) or {}
        if not _pre_session_id:
            register_session(session_id=session_id, founder_id=founder_id, goal=instruction,
                             workspace_id=str(root_meta.get("workspace_id") or ""),
                             company_id=str(root_meta.get("company_id") or company_id),
                             parent_session_id=root, kind="scheduled")
    except Exception:
        pass
    update_operating_session(founder_id, session_id, company_id=company_id, summary=run_summary)

    try:
        from backend.control_plane.start_run import start_continue_run
        from backend.core.events import register_parent_session

        if root and session_id != root:
            register_parent_session(session_id, root)
        result = await start_continue_run(
            founder_id=founder_id,
            instruction=instruction,
            prior_session_id=prior_sid,
            run_id=session_id,
            agents=owners or None,
            company_id=company_id,
            kind="scheduled",
            schedule_task=False,
            validate_prior=False,
        )
        update_operating_session(
            founder_id,
            result.session_id,
            company_id=company_id,
            status="done",
            summary=run_summary,
        )
        return {"ok": True, "session_id": result.session_id}
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
    finally:
        try:
            from backend.core import cancellation
            cancellation.clear(session_id)
        except Exception:
            pass


def launch_current_goal_dispatch(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    """Thin background launcher for company-goal dispatch.

    Reserves the visible session ID once, then schedules the real dispatch
    coroutine. Routes should call this instead of open-coding session creation
    and asyncio kickoff.
    """
    from backend.core.session_ids import new_session_id

    session_id = new_session_id()
    task = asyncio.create_task(dispatch_current_goal(founder_id, company_id, _pre_session_id=session_id))
    try:
        from backend.core import cancellation

        cancellation.register_task(session_id, task)
    except Exception:
        pass
    return {"ok": True, "session_id": session_id}


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
                from backend.missions.company_goal import _goal_lock, _read, _save
                with _goal_lock(founder_id, company_id):
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
        # so guard on != "proposed" (don't stack a second proposal on an unapproved one).
        # Also accept cur.status=="done" directly: tick_from_agent runs in executor threads
        # that may finish after after_run starts, so _goal_is_complete may return False
        # even though complete_agent_workstream already flipped the goal to "done".
        _goal_done = (cur is not None) and (cur.get("status") == "done" or _goal_is_complete(cur))
        if goal and goal.get("status") != "paused" and cur and cur.get("status") != "proposed" and _goal_done:
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

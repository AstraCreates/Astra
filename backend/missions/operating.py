"""Company operating cycle — the streamlined, session-level goal loop.

One company has ONE goal (the north star) and ONE unified milestone list. Each
cycle runs the WHOLE agent system (via Orchestrator.continue_run — all agents
collaborate) toward the north star, as a CHILD session linked to the parent launch
session, instead of spawning one isolated specialist run per department.

  parent (launch session)
    └─ operating run #1 (child session, kind="operating")
    └─ operating run #2 ...

A run advances the unified milestones: finished milestones go to "awaiting_approval"
(founder signs off in the UI to mark them done), then the planner assigns the next
ones. require_approval gates COMPLETION, not execution.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_OPEN = {"pending", "in_progress", "blocked"}


def _extract_summary(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)[:600]
    for key in ("summary", "output_summary", "headline", "formatted_text", "report", "text"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:800]
    return "Operating run completed."


def _parse_json_array(raw: str) -> list[Any]:
    s = (raw or "").strip()
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if m:
        s = m.group(0)
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def assign_next_milestones(founder_id: str, max_new: int = 3) -> list[dict[str, Any]]:
    """When the company has no open milestones, ask the planner for the next ones
    toward the north star and add them as pending. Company-level (all departments)."""
    from backend.missions.company_goal import get_company_goal, has_open_work, upsert_tasks

    goal = get_company_goal(founder_id)
    if goal is None or goal.get("status") == "paused":
        return []
    if has_open_work(founder_id):
        return []

    north_star = goal.get("north_star") or goal.get("company_goal") or ""
    done_titles = [t.get("title") for t in (goal.get("tasks") or []) if t.get("status") == "done"][-12:]
    prompt = (
        "You are the continuous operating planner for a startup. The company always has a "
        "north star it works toward — there is no 'finished'. ALL departments (research, "
        "product/technical, marketing, sales, legal, ops, finance) work TOGETHER toward it.\n\n"
        f"North star: {north_star}\n"
        f"Already-completed milestones (do NOT repeat): {json.dumps(done_titles)}\n\n"
        f"Assign the next {max_new} highest-leverage company milestones — each a concrete, "
        "verifiable step the whole team can push in one work cycle, spanning whatever "
        "departments are needed. Respond with ONLY a JSON array: "
        '[{"title": "short milestone", "notes": "why it matters + how to verify"}].'
    )
    try:
        from backend.tools._llm import generate
        items = _parse_json_array(generate(prompt, max_tokens=900, model="large"))
    except Exception as e:
        logger.warning("assign_next_milestones (company) failed for %s: %s", founder_id, e)
        items = []

    new_tasks = [
        {"title": str(it["title"])[:200], "notes": str(it.get("notes", ""))[:600], "status": "pending"}
        for it in items[:max_new]
        if isinstance(it, dict) and it.get("title")
    ]
    if not new_tasks:
        return []
    upsert_tasks(founder_id, new_tasks)
    logger.info("operating: assigned %d next company milestones for %s", len(new_tasks), founder_id)
    return new_tasks


def _build_instruction(goal: dict[str, Any], open_tasks: list[dict[str, Any]]) -> str:
    north_star = goal.get("north_star") or goal.get("company_goal") or ""
    parts = [
        "Continue operating the company toward its north star. This is an ongoing "
        "operating cycle — all departments work together; there is no 'done'.",
        f"\nNORTH STAR:\n{north_star}",
    ]
    if goal.get("kpis"):
        kpis = "\n".join(
            f"  - {k.get('label') or k.get('key')}: {k.get('target', '')}" for k in goal["kpis"]
        )
        parts.append(f"\nKEY KPIS:\n{kpis}")
    if open_tasks:
        lines = "\n".join(f"  - [{t.get('status')}] {t.get('title')} :: {t.get('notes', '')}".strip() for t in open_tasks[:10])
        parts.append(f"\nOPEN MILESTONES TO ADVANCE THIS CYCLE:\n{lines}")
    parts.append(
        "\nMake concrete progress on the open milestones. Produce real outputs (analysis, "
        "code, copy, outreach, docs). End with a clear summary of what advanced."
    )
    return "\n".join(parts)


def _reconcile(founder_id: str, open_tasks: list[dict[str, Any]], result: Any, session_id: str, approval_policy: str) -> None:
    """Advance the unified milestone list after a cycle. Best-effort."""
    from backend.missions.company_goal import upsert_tasks

    summary = _extract_summary(result)
    done_status = "done" if approval_policy == "auto" else "awaiting_approval"
    updates: list[dict[str, Any]] = []

    # Mark the first open milestone as advanced this cycle.
    if open_tasks:
        first = dict(open_tasks[0])
        first["status"] = done_status
        first["notes"] = (first.get("notes", "") + f"\nAdvanced in run {session_id[:8]}: {summary}").strip()[:1000]
        first["last_run_id"] = session_id
        updates.append(first)

    # Add follow-up milestones the run surfaced (if the result carries any).
    next_tasks = result.get("next_tasks") if isinstance(result, dict) else None
    if isinstance(next_tasks, list):
        for nt in next_tasks[:3]:
            if isinstance(nt, dict) and nt.get("title"):
                updates.append({"title": str(nt["title"])[:200], "notes": str(nt.get("notes", ""))[:600], "status": "pending"})

    if updates:
        try:
            upsert_tasks(founder_id, updates)
        except Exception as e:
            logger.warning("operating reconcile upsert failed for %s: %s", founder_id, e)


async def run_operating_cycle(founder_id: str, session_id: str | None = None) -> dict[str, Any]:
    """Run one company operating cycle: continue the whole agent system toward the
    north star in a child session linked to the parent launch session."""
    import asyncio
    from backend.core.session_ids import new_session_id
    from backend.missions.company_goal import (
        get_company_goal, set_root_session, add_operating_session, update_operating_session,
    )

    goal = get_company_goal(founder_id)
    if goal is None:
        return {"ok": False, "reason": "no company goal"}
    if goal.get("status") == "paused":
        return {"ok": False, "reason": "paused"}

    open_tasks = [t for t in (goal.get("tasks") or []) if str(t.get("status")) in _OPEN]
    if not open_tasks:
        # Nothing open — ask the planner for the next milestones, then reload.
        assign_next_milestones(founder_id)
        goal = get_company_goal(founder_id) or goal
        open_tasks = [t for t in (goal.get("tasks") or []) if str(t.get("status")) in _OPEN]
        if not open_tasks:
            return {"ok": True, "skipped": "no open milestones"}

    root = goal.get("root_session_id") or goal.get("source_session_id") or ""
    session_id = session_id or new_session_id()
    approval_policy = goal.get("approval_policy", "require_approval")
    instruction = _build_instruction(goal, open_tasks)

    # Register the child session up front so it's traceable to the parent immediately.
    try:
        from backend.core.session_store import register_session
        register_session(
            session_id=session_id, founder_id=founder_id, goal=instruction,
            stack_id=goal.get("stack_id", ""), parent_session_id=root, kind="operating",
        )
    except Exception as e:
        logger.warning("operating: child session registration failed: %s", e)
    if not goal.get("root_session_id") and root:
        set_root_session(founder_id, root)
    add_operating_session(founder_id, session_id)

    logger.info("operating: START founder=%s session=%s parent=%s open=%d", founder_id, session_id, root, len(open_tasks))

    result: Any = None
    try:
        from backend.core.factory import get_orchestrator
        orch = get_orchestrator()
        result = await orch.continue_run(
            instruction=instruction,
            founder_id=founder_id,
            prior_session_id=root or session_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.error("operating: cycle failed founder=%s session=%s: %s", founder_id, session_id, exc, exc_info=True)
        update_operating_session(founder_id, session_id, status="error", summary=str(exc)[:300])
        return {"ok": False, "session_id": session_id, "error": str(exc)}

    summary = _extract_summary(result if isinstance(result, dict) else {})
    try:
        _reconcile(founder_id, open_tasks, result, session_id, approval_policy)
    except Exception as e:
        logger.warning("operating: reconcile failed for %s: %s", founder_id, e)
    update_operating_session(founder_id, session_id, status="done", summary=summary)

    # Mirror to Notion (best-effort).
    try:
        from backend.tools.notion_sync import sync_founder_operating_system
        await asyncio.to_thread(sync_founder_operating_system, founder_id)
    except Exception:
        pass

    logger.info("operating: END founder=%s session=%s summary=%r", founder_id, session_id, summary[:120])
    return {"ok": True, "session_id": session_id, "summary": summary, "parent_session_id": root}

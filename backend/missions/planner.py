"""Continuous milestone planner.

When every milestone in a mission is human-approved (done), the planner assigns the
next highest-leverage milestones toward the company north star — so the company
never stops working. This is the "/goal the planner keeps assigning" loop.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


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


def has_open_work(mission: dict[str, Any]) -> bool:
    """True if the mission still has pending/in-progress/awaiting milestones."""
    for t in mission.get("tasks") or []:
        if str(t.get("status")) in ("pending", "in_progress", "awaiting_approval"):
            return True
    return False


def assign_next_milestones(
    founder_id: str,
    mission_id: str,
    max_new: int = 3,
    company_id: str | None = None,
) -> list[dict[str, Any]]:
    """If the mission has no open work, ask the planner LLM for the next milestones
    toward the north star and add them as pending tasks. Returns the new tasks."""
    from backend.missions.store import get_mission, add_task
    from backend.missions.company_goal import get_company_goal

    mission = get_mission(mission_id)
    if mission is None or mission.get("status") not in (None, "active"):
        return []
    if has_open_work(mission):
        return []  # still work to do — don't pile on
    company_id = company_id or str(mission.get("company_id") or founder_id)

    goal = {}
    try:
        goal = get_company_goal(founder_id, company_id) or {}
    except Exception:
        pass
    north_star = goal.get("north_star") or mission.get("goal") or mission.get("name") or ""
    done_titles = [t.get("title") for t in (mission.get("tasks") or []) if t.get("status") == "done"][-10:]

    prompt = (
        "You are the continuous operating planner for a startup. The company always has a "
        "north star it is working toward — there is no 'finished'.\n\n"
        f"North star: {north_star}\n"
        f"Department: {mission.get('department')}\n"
        f"Mission: {mission.get('name')} — {mission.get('goal')}\n"
        f"Primary metric: {mission.get('primary_metric')}\n"
        f"Already-completed milestones (do NOT repeat): {json.dumps(done_titles)}\n\n"
        f"Assign the next {max_new} highest-leverage milestones for THIS department to push the "
        "north star forward. Each must be concrete, verifiable in one work cycle, and a clear step "
        "beyond what's already done. Respond with ONLY a JSON array: "
        '[{"title": "short milestone", "notes": "why it matters + how to verify it"}].'
    )
    try:
        from backend.tools._llm import generate
        raw = generate(prompt, max_tokens=900, model="large")
        items = _parse_json_array(raw)
    except Exception as e:
        logger.warning("assign_next_milestones LLM failed for %s: %s", mission_id, e)
        items = []

    created: list[dict[str, Any]] = []
    for it in items[:max_new]:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        try:
            task = add_task(mission_id, {
                "title": str(it["title"])[:200],
                "notes": str(it.get("notes", ""))[:600],
                "status": "pending",
                "owner_agent": mission.get("department"),
            })
            created.append(task)
        except Exception as e:
            logger.warning("assign_next_milestones add_task failed: %s", e)
    if created:
        logger.info("planner: assigned %d next milestones to mission %s", len(created), mission_id)
    return created

"""Bootstrap a completed launch run into continuous company operating state."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _department_for_agent(agent: str) -> str:
    name = (agent or "").lower()
    if name.startswith("research"):
        return "research"
    if name.startswith("marketing"):
        return "marketing"
    if name.startswith("sales"):
        return "sales"
    if name.startswith("legal"):
        return "legal"
    if name.startswith("ops"):
        return "ops"
    if name.startswith("finance"):
        return "finance"
    return "technical"


def _task_status_from_item(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "").lower()
    if status in {"done", "completed"}:
        return "done"
    if status in {"running", "in_progress"}:
        return "in_progress"
    if item.get("blockers"):
        return "blocked"
    return "pending"


def _mission_status_from_items(items: list[dict[str, Any]]) -> str:
    if any(task.get("status") == "blocked" for task in items):
        return "paused"
    if items and all(task.get("status") == "done" for task in items):
        return "completed"
    return "active"


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return cleaned[:80] or fallback


def _mission_task_tree(mission_id: str, session_id: str, item: dict[str, Any], digest: dict[str, Any]) -> list[dict[str, Any]]:
    agent = item.get("agent", "agent")
    root_id = f"{mission_id}:main"
    tasks: list[dict[str, Any]] = [
        {
            "id": root_id,
            "title": item.get("title") or agent.replace("_", " ").title(),
            "status": _task_status_from_item(item),
            "parent_id": None,
            "notes": item.get("mission") or item.get("summary") or "",
            "owner_agent": agent,
            "last_run_id": session_id,
        }
    ]
    for idx, artifact in enumerate(item.get("ready_artifacts") or []):
        artifact_key = _slug(str(artifact.get("key") or artifact.get("title") or f"artifact_{idx + 1}"), f"artifact_{idx + 1}")
        tasks.append(
            {
                "id": f"{mission_id}:artifact:{artifact_key}",
                "title": artifact.get("title") or artifact.get("key") or f"Artifact {idx + 1}",
                "status": "done",
                "parent_id": root_id,
                "notes": artifact.get("description") or artifact.get("acceptance") or "",
                "owner_agent": agent,
                "last_run_id": session_id,
            }
        )
    for idx, blocker in enumerate(item.get("blockers") or []):
        tasks.append(
            {
                "id": f"{mission_id}:blocker:{idx + 1}",
                "title": f"Resolve blocker {idx + 1}",
                "status": "blocked",
                "parent_id": root_id,
                "notes": str(blocker),
                "owner_agent": agent,
                "last_run_id": session_id,
            }
        )
    # Seed open milestones from THIS mission's own steps (department-scoped and
    # concrete) so the scheduler has real forward work to do. Previously every
    # mission was sprayed with the same global digest.next_actions — e.g. the
    # research mission got "Decide approval gate: Send outbound email" — which is the
    # wrong department and just stale launch-gate decisions, not operating milestones.
    done_titles = {str(t.get("title", "")).strip().lower() for t in tasks}
    for idx, step in enumerate((item.get("steps") or [])[:5]):
        title = str(step).strip()
        if not title or title.lower() in done_titles:
            continue
        step_slug = _slug(title, f"step_{idx + 1}")
        tasks.append(
            {
                "id": f"{mission_id}:milestone:{step_slug}",
                "title": title[:160],
                "status": "pending",
                "parent_id": root_id,
                "notes": "Operating milestone for this department.",
                "owner_agent": agent,
                "last_run_id": session_id,
            }
        )
    return tasks


def bootstrap_company_operating_system(
    session_id: str,
    founder_id: str,
    *,
    goal: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    from backend.missions.company_goal import (
        upsert_company_goal, set_root_session, set_tasks, get_tasks,
    )
    from backend.tools.notion_sync import sync_founder_operating_system

    if not founder_id:
        raise ValueError("founder_id is required")

    operating_plan = state.get("operating_plan") or {}
    execution_contract = state.get("execution_contract") or (operating_plan.get("execution_contract") or {})
    workboard = state.get("workboard") or {}
    digest = state.get("digest") or {}
    company_name = ((state.get("company_genome") or {}).get("company_name") or "").strip()
    north_star = execution_contract.get("north_star") or operating_plan.get("outcome") or goal
    company_goal_text = (
        f"Operate {company_name or 'the company'} continuously toward the north star — all "
        f"departments work together to expand and launch the product, advancing the next "
        f"highest-leverage milestones each cycle."
    )
    goal_record = upsert_company_goal(
        founder_id,
        north_star=north_star,
        company_goal=company_goal_text,
        source_session_id=session_id,
        status="operating",
        kpis=list(execution_contract.get("kpis") or []),
    )
    # The launch session is the durable parent every operating run continues from.
    set_root_session(founder_id, session_id)

    # Build ONE unified, company-level milestone list (not per-department missions).
    # Launch work that's already complete is recorded as done; open steps + the
    # digest's prioritized next actions become the forward operating milestones the
    # whole team advances together.
    unified: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(title: str, status: str, notes: str = "") -> None:
        t = (title or "").strip()
        key = t.lower()
        if not t or key in seen:
            return
        seen.add(key)
        tid = _slug(t, f"task_{len(unified) + 1}")
        unified.append({"id": tid, "title": t[:200], "status": status, "notes": notes[:600], "last_run_id": session_id})

    for item in workboard.get("items") or []:
        item_status = _task_status_from_item(item)
        title = item.get("title") or (item.get("agent") or "Workstream").replace("_", " ").title()
        _add(title, "done" if item_status == "done" else "pending",
             item.get("mission") or item.get("summary") or "")
        for step in (item.get("steps") or [])[:3]:
            _add(str(step), "pending", "Operating step from the launch plan.")

    for action in (digest.get("next_actions") or [])[:6]:
        title = str(action)
        # Strip stale launch-gate phrasing so milestones read as forward work.
        title = re.sub(r"^(decide approval gate:|approve:)\s*", "", title, flags=re.I).strip()
        _add(title, "pending", "Prioritized next action from the launch run.")

    # Keep existing open milestones if we're re-bootstrapping (idempotent), else seed.
    if get_tasks(founder_id):
        from backend.missions.company_goal import upsert_tasks
        upsert_tasks(founder_id, [t for t in unified if t["status"] == "pending"][:14])
    else:
        set_tasks(founder_id, unified[:16])

    open_count = sum(1 for t in get_tasks(founder_id) if str(t.get("status")) in ("pending", "in_progress", "blocked"))
    notion = sync_founder_operating_system(founder_id)
    return {
        "ok": True,
        "company_goal": goal_record,
        "summary": f"Company operating toward the north star — {open_count} open milestone(s) for the team to advance.",
        "mission_count": 1,
        "open_milestones": open_count,
        "missions": [],
        "notion": notion,
    }

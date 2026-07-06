"""Session workboard.

Turns Astra's event stream into a durable operator view: assigned work,
owners, blockers, next actor, and expected artifacts.
"""

from __future__ import annotations

from typing import Any

from backend.session_event_reducer import clip_text, fold_session_events


def _clip(value: Any, limit: int = 220) -> str:
    return clip_text(value, limit)


def build_session_workboard(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    folded = fold_session_events(
        events,
        clip_limit=220,
        decision_creates_approval=True,
        trigger_missing_approval=True,
    )
    operating_plan = folded.operating_plan
    execution_blueprint = folded.execution_blueprint
    stack = folded.stack
    latest_plan = folded.latest_plan

    lane_by_agent: dict[str, dict[str, Any]] = {
        lane.get("agent", ""): lane
        for lane in operating_plan.get("lanes", [])
        if lane.get("agent")
    }
    blueprint_lane_by_agent: dict[str, dict[str, Any]] = {
        lane.get("agent", ""): lane
        for lane in execution_blueprint.get("lanes", [])
        if lane.get("agent")
    }
    for agent, lane in blueprint_lane_by_agent.items():
        lane_by_agent.setdefault(agent, lane)
    task_by_agent: dict[str, dict[str, Any]] = {
        task.get("agent", ""): task
        for task in latest_plan
        if task.get("agent")
    }
    all_agents = list(dict.fromkeys([*lane_by_agent.keys(), *task_by_agent.keys()]))

    state = folded.agent_state
    artifacts_by_agent = folded.artifacts_by_agent
    outcomes_by_agent = folded.outcomes_by_agent
    approvals_by_gate = folded.approvals_by_gate
    saferun_by_agent = folded.saferun_by_agent
    lane_status_by_agent = folded.lane_status_by_agent
    verification_by_agent = folded.verification_by_agent

    items: list[dict[str, Any]] = []
    for agent in all_agents:
        lane = lane_by_agent.get(agent, {})
        blueprint_lane = blueprint_lane_by_agent.get(agent, {})
        task = task_by_agent.get(agent, {})
        current = state.get(agent, {})
        lane_status = lane_status_by_agent.get(agent, {})
        verification = verification_by_agent.get(agent) or lane_status.get("artifact_verification") or {}
        status = lane_status.get("status") or current.get("status") or "queued"
        blockers: list[str] = []
        pending_approvals = [
            approval for approval in approvals_by_gate.values()
            if approval.get("status") == "triggered"
        ]
        for action in saferun_by_agent.get(agent, []):
            gate = action.get("approval_gate")
            approval = approvals_by_gate.get(gate, {})
            if approval.get("status") == "triggered":
                blockers.append(f"Approval needed: {approval.get('title') or gate}")
        if status == "error":
            blockers.append(_clip(current.get("summary") or "Agent lane failed."))
        if status == "blocked":
            blockers.extend(_clip(blocker) for blocker in lane_status.get("blockers", []) if blocker)
        if verification.get("status") == "blocked":
            blockers.extend(f"Missing artifact: {key}" for key in verification.get("required_missing", []))

        if blockers:
            next_actor = "founder"
        elif status in {"queued", "running"}:
            next_actor = "agent"
        else:
            next_actor = "founder_review"

        items.append({
            "id": lane.get("id") or task.get("id") or agent,
            "agent": agent,
            "owner_type": "agent",
            "owner": agent,
            "title": lane.get("title") or task.get("stack_task_title") or agent.replace("_", " ").title(),
            "mission": lane.get("mission") or task.get("instruction") or "",
            "status": status,
            "next_actor": next_actor,
            "depends_on": lane.get("depends_on") or task.get("depends_on") or [],
            "phase": lane_status.get("phase") or blueprint_lane.get("phase") or lane.get("phase", ""),
            "steps": blueprint_lane.get("steps", []),
            "approval_triggers": blueprint_lane.get("approval_triggers", []),
            "connector_dependencies": blueprint_lane.get("connector_dependencies", []),
            "expected_artifacts": lane.get("artifacts") or blueprint_lane.get("deliverables") or [],
            "ready_artifacts": artifacts_by_agent.get(agent, [])[-6:],
            "artifact_verification": verification,
            "outcomes": outcomes_by_agent.get(agent, [])[-6:],
            "blockers": blockers,
            "summary": _clip(lane_status.get("summary") or current.get("summary")),
        })

    counts = {
        "total": len(items),
        "queued": len([item for item in items if item["status"] == "queued"]),
        "running": len([item for item in items if item["status"] == "running"]),
        "done": len([item for item in items if item["status"] == "done"]),
        "blocked": len([item for item in items if item["blockers"]]),
        "founder_next": len([item for item in items if item["next_actor"] in {"founder", "founder_review"}]),
        "agent_next": len([item for item in items if item["next_actor"] == "agent"]),
    }
    return {
        "session_id": session_id,
        "stack_name": operating_plan.get("stack_name") or stack.get("name", ""),
        "outcome": operating_plan.get("outcome") or stack.get("primary_outcome", ""),
        "counts": counts,
        "items": items,
        "execution_blueprint": {
            "stack_id": execution_blueprint.get("stack_id"),
            "blueprint_version": execution_blueprint.get("blueprint_version"),
            "calendar": execution_blueprint.get("calendar", []),
            "completion_audit": execution_blueprint.get("completion_audit", []),
        },
        "pending_approvals": [approval for approval in approvals_by_gate.values() if approval.get("status") == "triggered"],
        "summary": (
            f"{counts['done']} operating lanes complete, {counts['running']} active, {counts['queued']} queued for next work, "
            f"{counts['blocked']} blocked, {counts['founder_next']} waiting on founder review/action."
        ),
    }

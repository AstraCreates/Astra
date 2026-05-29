"""Session workboard.

Turns Astra's event stream into a durable operator view: assigned work,
owners, blockers, next actor, and expected artifacts.
"""

from __future__ import annotations

from typing import Any


def _clip(value: Any, limit: int = 220) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def build_session_workboard(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    event_dicts = [event for _, event in events]
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    ) or {}
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None) or {}
    latest_plan = next(
        (event.get("tasks") for event in reversed(event_dicts) if event.get("type") == "plan_done"),
        [],
    )

    lane_by_agent: dict[str, dict[str, Any]] = {
        lane.get("agent", ""): lane
        for lane in operating_plan.get("lanes", [])
        if lane.get("agent")
    }
    task_by_agent: dict[str, dict[str, Any]] = {
        task.get("agent", ""): task
        for task in latest_plan
        if task.get("agent")
    }
    all_agents = list(dict.fromkeys([*lane_by_agent.keys(), *task_by_agent.keys()]))

    state: dict[str, dict[str, Any]] = {}
    artifacts_by_agent: dict[str, list[dict[str, Any]]] = {}
    outcomes_by_agent: dict[str, list[dict[str, Any]]] = {}
    approvals_by_gate: dict[str, dict[str, Any]] = {}
    saferun_by_agent: dict[str, list[dict[str, Any]]] = {}

    for event in event_dicts:
        event_type = event.get("type")
        agent = event.get("agent")
        if event_type == "agent_start" and agent:
            state.setdefault(agent, {})["status"] = "running"
            state[agent]["instruction"] = event.get("instruction", "")
        elif event_type == "agent_done" and agent:
            result = event.get("result") or event.get("output") or {}
            state.setdefault(agent, {})["status"] = "done"
            state[agent]["summary"] = result.get("summary") if isinstance(result, dict) else _clip(result)
        elif event_type == "agent_error" and agent:
            state.setdefault(agent, {})["status"] = "error"
            state[agent]["summary"] = event.get("error", "")
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            artifacts_by_agent.setdefault(artifact.get("owner_agent", ""), []).append(artifact)
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcome = event["outcome"]
            outcomes_by_agent.setdefault(outcome.get("agent", ""), []).append(outcome)
        elif event_type == "stack_approval_queue":
            for approval in event.get("approval_queue", []):
                approvals_by_gate[approval.get("key", "")] = approval
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            if key:
                approvals_by_gate[key] = {
                    **approvals_by_gate.get(key, {}),
                    "key": key,
                    "status": event.get("decision"),
                    "note": event.get("note"),
                }
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            saferun_by_agent.setdefault(action.get("agent", ""), []).append(action)
            gate = action.get("approval_gate")
            if gate:
                approvals_by_gate[gate] = {
                    **approvals_by_gate.get(gate, {"key": gate}),
                    "status": "triggered",
                    "triggered_by": action.get("id"),
                }

    items: list[dict[str, Any]] = []
    for agent in all_agents:
        lane = lane_by_agent.get(agent, {})
        task = task_by_agent.get(agent, {})
        current = state.get(agent, {})
        status = current.get("status") or "queued"
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
            "expected_artifacts": lane.get("artifacts") or [],
            "ready_artifacts": artifacts_by_agent.get(agent, [])[-6:],
            "outcomes": outcomes_by_agent.get(agent, [])[-6:],
            "blockers": blockers,
            "summary": _clip(current.get("summary")),
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
        "pending_approvals": [approval for approval in approvals_by_gate.values() if approval.get("status") == "triggered"],
        "summary": (
            f"{counts['done']} done, {counts['running']} running, {counts['queued']} queued, "
            f"{counts['blocked']} blocked, {counts['founder_next']} waiting on founder review/action."
        ),
    }

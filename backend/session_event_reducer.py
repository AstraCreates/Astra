"""Small shared folds over session event streams for reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def clip_text(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


@dataclass
class SessionEventSummary:
    event_dicts: list[dict[str, Any]]
    stack: dict[str, Any] = field(default_factory=dict)
    genome: dict[str, Any] = field(default_factory=dict)
    operating_plan: dict[str, Any] = field(default_factory=dict)
    execution_blueprint: dict[str, Any] = field(default_factory=dict)
    latest_plan: list[dict[str, Any]] = field(default_factory=list)
    agent_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    artifacts_by_agent: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    verification_by_agent: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    outcomes_by_agent: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    approvals_by_gate: dict[str, dict[str, Any]] = field(default_factory=dict)
    saferun_actions: list[dict[str, Any]] = field(default_factory=list)
    saferun_by_agent: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    lane_status_by_agent: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def event_dicts_from(events: list[tuple[int, dict[str, Any]]] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []
    first = events[0]
    if isinstance(first, tuple):
        return [event for _, event in events]  # type: ignore[misc]
    return list(events)  # type: ignore[arg-type]


def fold_session_events(
    events: list[tuple[int, dict[str, Any]]] | list[dict[str, Any]],
    *,
    clip_limit: int = 180,
    include_approval_requests: bool = False,
    decision_creates_approval: bool = False,
    trigger_missing_approval: bool = False,
) -> SessionEventSummary:
    """Fold common session events without imposing a report-specific shape."""
    event_dicts = event_dicts_from(events)
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    ) or {}
    execution_blueprint = next(
        (event.get("execution_blueprint") for event in reversed(event_dicts) if event.get("type") == "stack_execution_blueprint"),
        None,
    ) or (operating_plan.get("execution_blueprint") or {})
    summary = SessionEventSummary(
        event_dicts=event_dicts,
        stack=next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None) or {},
        genome=next((event.get("genome") for event in event_dicts if event.get("type") == "company_genome"), None) or {},
        operating_plan=operating_plan,
        execution_blueprint=execution_blueprint,
        latest_plan=next((event.get("tasks") for event in reversed(event_dicts) if event.get("type") == "plan_done"), []) or [],
    )

    for event in event_dicts:
        event_type = event.get("type")
        agent = event.get("agent")
        if event_type == "agent_start" and agent:
            summary.agent_state.setdefault(agent, {})["status"] = "running"
            summary.agent_state[agent]["instruction"] = event.get("instruction", "")
        elif event_type == "agent_done" and agent:
            result = event.get("result") or event.get("output") or {}
            summary.agent_state.setdefault(agent, {})["status"] = "done"
            summary.agent_state[agent]["summary"] = result.get("summary") if isinstance(result, dict) else clip_text(result, clip_limit)
        elif event_type == "agent_error" and agent:
            summary.agent_state.setdefault(agent, {})["status"] = "error"
            summary.agent_state[agent]["summary"] = event.get("error", "")
            summary.errors.append(f"{agent}: {clip_text(event.get('error'), clip_limit)}")
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            summary.artifacts.append(artifact)
            summary.artifacts_by_agent.setdefault(artifact.get("owner_agent", ""), []).append(artifact)
        elif event_type == "stack_artifact_verification" and event.get("verification"):
            verification = event["verification"]
            if verification.get("agent"):
                summary.verification_by_agent[verification["agent"]] = verification
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcome = event["outcome"]
            summary.outcomes.append(outcome)
            summary.outcomes_by_agent.setdefault(outcome.get("agent", ""), []).append(outcome)
        elif event_type == "stack_approval_queue":
            for approval in event.get("approval_queue", []):
                summary.approvals_by_gate[approval.get("key", "")] = approval
        elif event_type == "approval_request" and include_approval_requests:
            request = event.get("request") or {}
            key = request.get("gate_key", "")
            if key:
                summary.approvals_by_gate[key] = {**request, "status": request.get("status", "armed")}
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            if key and (decision_creates_approval or key in summary.approvals_by_gate):
                summary.approvals_by_gate[key] = {
                    **summary.approvals_by_gate.get(key, {"key": key}),
                    "status": event.get("decision", summary.approvals_by_gate.get(key, {}).get("status")),
                    "note": event.get("note"),
                }
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            summary.saferun_actions.append(action)
            summary.saferun_by_agent.setdefault(action.get("agent", ""), []).append(action)
            gate = action.get("approval_gate")
            should_trigger = gate in summary.approvals_by_gate or (trigger_missing_approval and gate)
            if should_trigger and summary.approvals_by_gate.get(gate, {}).get("status") not in {"approved", "skipped"}:
                summary.approvals_by_gate[gate] = {
                    **summary.approvals_by_gate.get(gate, {"key": gate}),
                    "status": "triggered",
                    "triggered_by": action.get("id"),
                }
        elif event_type == "stack_lane_status" and agent:
            summary.lane_status_by_agent[agent] = {**summary.lane_status_by_agent.get(agent, {}), **event}

    return summary

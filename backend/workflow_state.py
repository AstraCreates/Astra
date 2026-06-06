"""Durable workflow state snapshots.

The event stream is the source of truth while a run is active. This module
condenses that stream into a compact state document that can be persisted and
restored after completion or backend restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.session_digest import build_session_digest
from backend.workboard import build_session_workboard


def _state_root() -> Path:
    root = Path(".astra/workflows")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-", "."})[:120] or "session"
    return _state_root() / f"{safe}.json"


def build_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    event_dicts = [event for _, event in events]
    founder_id = next((str(event.get("founder_id")) for event in event_dicts if event.get("founder_id")), "")
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None)
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    )
    manifest = next(
        (event.get("manifest") for event in reversed(event_dicts) if event.get("type") == "stack_manifest"),
        None,
    )
    execution_contract = next(
        (event.get("execution_contract") for event in reversed(event_dicts) if event.get("type") == "stack_execution_contract"),
        None,
    )
    execution_blueprint = next(
        (event.get("execution_blueprint") for event in reversed(event_dicts) if event.get("type") == "stack_execution_blueprint"),
        None,
    )
    genome = next((event.get("genome") for event in reversed(event_dicts) if event.get("type") == "company_genome"), None)
    approval_workflow = _approval_workflow_snapshot(session_id)
    approvals: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_verifications: dict[str, dict[str, Any]] = {}
    lane_status: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    saferun: dict[str, dict[str, Any]] = {}
    final_status = "running"
    agent_status: dict[str, str] = {}

    for event in event_dicts:
        event_type = event.get("type")
        if event_type == "approval_request" and event.get("request"):
            request = event["request"]
            item = _approval_request_state(request)
            approvals[item.get("key", "")] = item
        elif event_type == "stack_approval_queue":
            for item in event.get("approval_queue", []):
                approvals[item.get("key", "")] = item
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            approvals[key] = {**approvals.get(key, {"key": key}), "status": event.get("decision"), "note": event.get("note")}
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            artifacts[artifact.get("key", "")] = artifact
        elif event_type == "stack_artifact_verification" and event.get("verification"):
            verification = event["verification"]
            artifact_verifications[verification.get("lane_id") or verification.get("task_id") or verification.get("agent", "")] = verification
        elif event_type == "stack_lane_status":
            lane_id = event.get("lane_id") or event.get("agent") or ""
            lane_status[lane_id] = {**lane_status.get(lane_id, {}), **event}
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcomes.append(event["outcome"])
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            saferun[action.get("id", "")] = action
        elif event_type == "saferun_result":
            action_id = event.get("action_id", "")
            saferun[action_id] = {**saferun.get(action_id, {"id": action_id}), **event}
        elif event_type == "agent_start" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "running"
        elif event_type == "agent_done" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "done"
        elif event_type == "agent_error" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "error"
        elif event_type == "goal_done":
            final_status = "done"
        elif event_type == "goal_error":
            final_status = "error"

    if final_status == "running":
        ledger = _run_ledger_snapshot(session_id)
        if isinstance(ledger, dict) and ledger.get("status") == "stalled":
            final_status = "stalled"
        elif agent_status and "running" not in set(agent_status.values()):
            last_type = event_dicts[-1].get("type") if event_dicts else ""
            if last_type in {"agent_done", "agent_error", "stack_artifact_verification", "stack_lane_status"}:
                final_status = "stalled"

    for request in approval_workflow.get("requests", []) if isinstance(approval_workflow, dict) else []:
        item = _approval_request_state(request)
        key = item.get("key", "")
        approvals[key] = {**approvals.get(key, {}), **item}

    state = {
        "session_id": session_id,
        "founder_id": founder_id,
        "status": final_status,
        "event_count": len(events),
        "last_event_id": events[-1][0] if events else 0,
        "stack": stack,
        "operating_plan": operating_plan,
        "manifest": manifest,
        "execution_contract": execution_contract,
        "execution_blueprint": execution_blueprint,
        "lane_status": list(lane_status.values()),
        "company_genome": genome,
        "digest": build_session_digest(session_id, events) if events else None,
        "workboard": build_session_workboard(session_id, events) if events else None,
        "approval_workflow": approval_workflow,
        "approvals": list(approvals.values()),
        "artifacts": list(artifacts.values()),
        "artifact_verifications": list(artifact_verifications.values()),
        "outcomes": outcomes[-50:],
        "saferun_actions": list(saferun.values())[-50:],
        "run_ledger": _run_ledger_snapshot(session_id),
    }
    try:
        from backend.run_completion_audit import build_run_completion_audit
        state["completion_audit"] = build_run_completion_audit(session_id, state)
        if state["status"] == "done" and state["completion_audit"].get("ok") is False:
            state["status"] = "stalled"
    except Exception as exc:
        state["completion_audit"] = {"ok": False, "status": "error", "summary": str(exc), "checks": [], "failed": []}
    return state


def save_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    state = build_session_state(session_id, events)
    _state_path(session_id).write_text(json.dumps(state, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("workflow_states", session_id, state)
    except Exception:
        pass
    return state


def load_session_state(session_id: str) -> dict[str, Any] | None:
    path = _state_path(session_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    try:
        from backend.storage_adapter import load_document
        return load_document("workflow_states", session_id)
    except Exception:
        return None


def _run_ledger_snapshot(session_id: str) -> dict[str, Any] | None:
    try:
        from backend.run_ledger import get_run
        return get_run(session_id)
    except Exception:
        return None


def _approval_workflow_snapshot(session_id: str) -> dict[str, Any]:
    try:
        from backend.approval_workflows import get_approval_workflow
        return get_approval_workflow(session_id)
    except Exception:
        return {"session_id": session_id, "requests": []}


def _approval_request_state(request: dict[str, Any]) -> dict[str, Any]:
    gate_key = str(request.get("gate_key") or request.get("key") or request.get("id") or "")
    required_before = request.get("required_before") or request.get("tool") or request.get("action_id") or "sensitive action"
    return {
        "key": gate_key,
        "id": request.get("id") or gate_key,
        "gate_key": gate_key,
        "title": request.get("title") or gate_key.replace("_", " ").title(),
        "trigger": request.get("trigger") or request.get("tool") or request.get("action_id") or "",
        "required_before": required_before,
        "reason": request.get("reason") or f"Approval required before {required_before}.",
        "status": request.get("status") or "pending",
        "triggered_by": request.get("action_id") or None,
        "required_role": request.get("required_role") or "owner",
        "risk_level": request.get("risk_level") or "medium",
        "note": request.get("note") or "",
        "decided_by": request.get("decided_by"),
        "decided_at": request.get("decided_at"),
        "history": request.get("history") or [],
    }

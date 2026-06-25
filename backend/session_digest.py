"""Run digest builder.

Condenses a session event log into an operator-readable update: what ran,
what shipped, what is blocked, and what should happen next.
"""
from __future__ import annotations

from typing import Any


_TEAM_AGENT_ALIASES: dict[str, set[str]] = {
    "engineering": {"technical", "web", "design"},
    "product": {"technical", "design", "research", "ops"},
    "growth": {"marketing", "sales", "web", "research"},
    "sales": {"sales", "research", "marketing"},
    "marketing": {"marketing", "design", "web", "research"},
    "support": {"ops", "technical", "research"},
    "ops": {"ops", "legal", "research"},
    "legal": {"legal", "ops"},
}


def _clip(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _team_agents(team: str) -> set[str]:
    normalized = team.lower().strip().replace(" team", "").replace(" subteam", "")
    return _TEAM_AGENT_ALIASES.get(normalized, {normalized})


def build_session_digest(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    event_dicts = [event for _, event in events]
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None) or {}
    genome = next((event.get("genome") for event in event_dicts if event.get("type") == "company_genome"), None) or {}
    plan_events = [event for event in event_dicts if event.get("type") == "plan_done"]
    latest_plan = plan_events[-1].get("tasks", []) if plan_events else []
    agent_state: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    approvals: dict[str, dict[str, Any]] = {}
    saferun: list[dict[str, Any]] = []
    errors: list[str] = []

    for event in event_dicts:
        event_type = event.get("type")
        agent = event.get("agent")
        if event_type == "agent_start" and agent:
            agent_state.setdefault(agent, {})["status"] = "running"
            agent_state[agent]["instruction"] = event.get("instruction", "")
        elif event_type == "agent_done" and agent:
            agent_state.setdefault(agent, {})["status"] = "done"
            result = event.get("result") or event.get("output") or {}
            agent_state[agent]["summary"] = (
                result.get("summary") if isinstance(result, dict) else _clip(result)
            )
        elif event_type == "agent_error" and agent:
            agent_state.setdefault(agent, {})["status"] = "error"
            agent_state[agent]["summary"] = event.get("error", "")
            errors.append(f"{agent}: {_clip(event.get('error'))}")
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifacts.append(event["artifact"])
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcomes.append(event["outcome"])
        elif event_type == "stack_approval_queue":
            for item in event.get("approval_queue", []):
                approvals[item.get("key", "")] = item
        elif event_type == "approval_request":
            req = event.get("request") or {}
            key = req.get("gate_key", "")
            if key:
                approvals[key] = {**req, "status": req.get("status", "armed")}
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            if key in approvals:
                approvals[key] = {**approvals[key], "status": event.get("decision", approvals[key].get("status")), "note": event.get("note")}
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            saferun.append(action)
            gate = action.get("approval_gate")
            if gate in approvals and approvals[gate].get("status") not in {"approved", "skipped"}:
                approvals[gate] = {**approvals[gate], "status": "triggered", "triggered_by": action.get("id")}

    planned_agents = [task.get("agent") for task in latest_plan if task.get("agent")]
    done_agents = [agent for agent, state in agent_state.items() if state.get("status") == "done"]
    running_agents = [agent for agent, state in agent_state.items() if state.get("status") == "running"]
    blocked_approvals = [item for item in approvals.values() if item.get("status") == "triggered"]
    pending_approvals = [item for item in approvals.values() if item.get("status") == "armed"]
    phase_gates = [item for item in approvals.values() if item.get("is_phase_gate")]
    phases_done = len([g for g in phase_gates if g.get("status") == "approved"])
    phases_pending = len([g for g in phase_gates if g.get("status") == "armed"])
    ready_artifacts = [item for item in artifacts if item.get("status") == "ready"]
    outcome_units = sum(int(item.get("value") or 0) for item in outcomes if isinstance(item.get("value"), int))

    next_actions: list[str] = []
    for approval in blocked_approvals[:3]:
        next_actions.append(f"Decide approval gate: {approval.get('title')}")
    if errors:
        next_actions.append("Review failed agent lanes and rerun or steer them.")
    for agent in planned_agents:
        if agent not in agent_state:
            next_actions.append(f"Start pending lane: {agent}")
            if len(next_actions) >= 5:
                break
    if not next_actions and running_agents:
        next_actions.append("Wait for active agent lanes to finish, then review generated artifacts.")
    if not next_actions and ready_artifacts:
        next_actions.append("Review ready artifacts and convert them into founder next actions.")

    summary = (
        f"{stack.get('name', 'Astra stack')} is running for {genome.get('company_name', 'this company')}. "
        f"{len(done_agents)} lanes done, {len(running_agents)} running, "
        f"{len(ready_artifacts)} artifacts ready, {len(outcomes)} outcome events recorded."
    )
    return {
        "session_id": session_id,
        "company_name": genome.get("company_name", ""),
        "stack_name": stack.get("name", ""),
        "summary": summary,
        "counts": {
            "planned_agents": len(planned_agents),
            "done_agents": len(done_agents),
            "running_agents": len(running_agents),
            "ready_artifacts": len(ready_artifacts),
            "outcome_events": len(outcomes),
            "outcome_units": outcome_units,
            "triggered_approvals": len(blocked_approvals),
            "pending_approvals": len(pending_approvals),
            "saferun_actions": len(saferun),
            "errors": len(errors),
            "phases_done": phases_done,
            "phases_pending": phases_pending,
            "phases_total": len(phase_gates),
        },
        "done_agents": done_agents,
        "running_agents": running_agents,
        "ready_artifacts": ready_artifacts[-6:],
        "recent_outcomes": outcomes[-6:],
        "approval_focus": blocked_approvals[:5],
        "errors": errors[:5],
        "next_actions": next_actions[:6],
    }


def build_subteam_report(session_id: str, events: list[tuple[int, dict]], team: str = "engineering") -> dict[str, Any]:
    """Answer the operator question: what did this subteam do and what is next?"""
    agents = _team_agents(team)
    event_dicts = [event for _, event in events]
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None) or {}
    plan_events = [event for event in event_dicts if event.get("type") == "plan_done"]
    latest_plan = plan_events[-1].get("tasks", []) if plan_events else []
    relevant_tasks = [task for task in latest_plan if task.get("agent") in agents]
    state: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    blockers: list[str] = []
    approvals: list[dict[str, Any]] = []

    for event in event_dicts:
        agent = event.get("agent")
        event_type = event.get("type")
        if event_type == "agent_start" and agent in agents:
            state.setdefault(agent, {})["status"] = "running"
            state[agent]["instruction"] = event.get("instruction", "")
        elif event_type == "agent_done" and agent in agents:
            result = event.get("result") or event.get("output") or {}
            state.setdefault(agent, {})["status"] = "done"
            state[agent]["summary"] = result.get("summary") if isinstance(result, dict) else _clip(result)
        elif event_type == "agent_error" and agent in agents:
            state.setdefault(agent, {})["status"] = "error"
            state[agent]["summary"] = event.get("error", "")
            blockers.append(f"{agent}: {_clip(event.get('error'))}")
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            if artifact.get("owner_agent") in agents:
                artifacts.append(artifact)
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcome = event["outcome"]
            if outcome.get("agent") in agents:
                outcomes.append(outcome)
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            if action.get("agent") in agents and action.get("approval_required"):
                approvals.append(action)
                blockers.append(f"Approval needed for {action.get('approval_gate')}: {action.get('reason')}")

    completed = [
        {"agent": agent, "summary": _clip(data.get("summary") or "Completed assigned lane.")}
        for agent, data in state.items()
        if data.get("status") == "done"
    ]
    active = [
        {"agent": agent, "instruction": _clip(data.get("instruction") or "Working on assigned lane.")}
        for agent, data in state.items()
        if data.get("status") == "running"
    ]
    pending = [
        {"agent": task.get("agent"), "instruction": _clip(task.get("instruction"))}
        for task in relevant_tasks
        if task.get("agent") not in state
    ]
    next_actions: list[str] = []
    if blockers:
        next_actions.append("Resolve approval or error blockers before this subteam can safely continue.")
    next_actions.extend([f"Start pending {item['agent']} lane." for item in pending[:3]])
    if active:
        next_actions.append("Wait for active work to finish, then review generated artifacts.")
    if artifacts and not next_actions:
        next_actions.append("Review artifacts and decide which outputs should become company operating records.")

    summary = (
        f"{team.title()} report for {stack.get('name', 'Astra stack')}: "
        f"{len(completed)} completed, {len(active)} active, {len(pending)} pending, "
        f"{len(artifacts)} artifacts, {len(outcomes)} outcomes."
    )
    return {
        "session_id": session_id,
        "team": team,
        "agents": sorted(agents),
        "summary": summary,
        "completed": completed,
        "active": active,
        "pending": pending,
        "artifacts": artifacts[-6:],
        "outcomes": outcomes[-6:],
        "approvals": approvals[-6:],
        "blockers": blockers[:6],
        "next_actions": next_actions[:6],
    }


def answer_session_question(session_id: str, events: list[tuple[int, dict]], question: str) -> dict[str, Any]:
    """Route a run question to the best deterministic operating report."""
    q = question.lower().strip()
    event_dicts = [event for _, event in events]
    manifest = next(
        (event.get("manifest") for event in reversed(event_dicts) if event.get("type") == "stack_manifest"),
        None,
    ) or {}
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    ) or {}

    if manifest and any(term in q for term in ("department", "manifest", "operating system", "workflow", "dashboard", "human", "collaboration")):
        workflow = manifest.get("workflow") or {}
        connectors = manifest.get("connectors") or {}
        lines = [
            f"{manifest.get('department_name', manifest.get('stack_name', 'Astra department'))}: {manifest.get('primary_outcome', '')}",
            _clip(manifest.get("positioning"), 320),
            f"Workflow: {len(workflow.get('nodes') or [])} lanes, {len(workflow.get('edges') or [])} handoffs.",
        ]
        required = connectors.get("required") or []
        if required:
            lines.append("Required connectors: " + ", ".join(connector.get("label", connector.get("key", "")) for connector in required[:6]))
        dashboards = manifest.get("dashboards") or []
        if dashboards:
            lines.append("Dashboards: " + "; ".join(section.get("title", "") for section in dashboards[:5]))
        outputs = manifest.get("outputs") or []
        if outputs:
            lines.append("Outputs: " + ", ".join(output.get("title", "") for output in outputs[:8]))
        collaboration = manifest.get("human_collaboration") or {}
        if collaboration.get("default_mode"):
            lines.append("Collaboration: " + collaboration["default_mode"])
        return {
            "session_id": session_id,
            "question": question,
            "answer_type": "department_manifest",
            "answer": "\n".join(line for line in lines if line),
            "manifest": manifest,
            "confidence": 0.92,
        }

    if operating_plan and any(term in q for term in ("plan", "stack", "connector", "approval", "artifact", "cadence", "department", "workflow")):
        lines = [
            f"{operating_plan.get('stack_name', 'Astra stack')}: {operating_plan.get('outcome', '')}",
            _clip(operating_plan.get("operator_contract"), 320),
        ]
        phases = operating_plan.get("phases") or []
        if phases:
            lines.append("Phases: " + "; ".join(f"{phase.get('name')}: {_clip(phase.get('objective'), 90)}" for phase in phases[:4]))
        connectors = (operating_plan.get("connector_plan") or {}).get("required") or []
        if connectors:
            lines.append("Required connectors: " + ", ".join(connector.get("label", connector.get("key", "")) for connector in connectors[:6]))
        approvals = operating_plan.get("approval_policy") or []
        if approvals:
            lines.append("Approval gates: " + "; ".join(gate.get("title", "") for gate in approvals[:4]))
        artifacts = operating_plan.get("artifact_contract") or []
        if artifacts:
            lines.append("Expected artifacts: " + ", ".join(artifact.get("title", "") for artifact in artifacts[:8]))
        return {
            "session_id": session_id,
            "question": question,
            "answer_type": "stack_operating_plan",
            "answer": "\n".join(line for line in lines if line),
            "operating_plan": operating_plan,
            "confidence": 0.9,
        }

    if any(term in q for term in ("assigned", "assignment", "task", "tasks", "worker", "workers", "next actor", "next action", "blocked", "blocker")):
        from backend.workboard import build_session_workboard
        workboard = build_session_workboard(session_id, events)
        lines = [f"Workboard: {workboard['summary']}"]
        blocked = [item for item in workboard["items"] if item.get("blockers")]
        founder_next = [item for item in workboard["items"] if item.get("next_actor") in {"founder", "founder_review"}]
        agent_next = [item for item in workboard["items"] if item.get("next_actor") == "agent"]
        if blocked:
            lines.append("Blocked: " + "; ".join(f"{item['agent']} - {', '.join(item['blockers'][:2])}" for item in blocked[:3]))
        if founder_next:
            lines.append("Founder next: " + "; ".join(f"{item['agent']} review/action" for item in founder_next[:4]))
        if agent_next:
            lines.append("Agent next: " + "; ".join(f"{item['agent']} - {item['status']}" for item in agent_next[:4]))
        return {
            "session_id": session_id,
            "question": question,
            "answer_type": "workboard",
            "answer": "\n".join(lines),
            "workboard": workboard,
            "confidence": 0.88,
        }

    requested_team = ""
    for team in _TEAM_AGENT_ALIASES:
        if team in q:
            requested_team = team
            break
    if "engineering" in q or "engineer" in q:
        requested_team = "engineering"
    elif "growth" in q:
        requested_team = "growth"

    if requested_team:
        report = build_subteam_report(session_id, events, requested_team)
        lines = [report["summary"]]
        if report["completed"]:
            lines.append("Completed: " + "; ".join(f"{item['agent']} - {item['summary']}" for item in report["completed"][:3]))
        if report["active"]:
            lines.append("Active: " + "; ".join(f"{item['agent']} - {item['instruction']}" for item in report["active"][:3]))
        if report["blockers"]:
            lines.append("Blockers: " + "; ".join(report["blockers"][:3]))
        if report["next_actions"]:
            lines.append("Next: " + "; ".join(report["next_actions"][:3]))
        return {
            "session_id": session_id,
            "question": question,
            "answer_type": "subteam_report",
            "answer": "\n".join(lines),
            "report": report,
            "confidence": 0.86,
        }

    digest = build_session_digest(session_id, events)
    lines = [digest["summary"]]
    if digest["next_actions"]:
        lines.append("Next: " + "; ".join(digest["next_actions"][:4]))
    if digest["approval_focus"]:
        lines.append("Needs approval: " + "; ".join(_clip(item.get("title")) for item in digest["approval_focus"][:3]))
    if digest["errors"]:
        lines.append("Errors: " + "; ".join(digest["errors"][:3]))
    return {
        "session_id": session_id,
        "question": question,
        "answer_type": "run_digest",
        "answer": "\n".join(lines),
        "digest": digest,
        "confidence": 0.72,
    }

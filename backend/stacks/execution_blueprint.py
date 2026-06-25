"""Executable blueprints for Agent Stack templates.

The blueprint turns a product template into lane-level work packets. It is
deterministic so the UI, orchestrator, and tests can agree on what the deployed
AI department is supposed to do before any LLM output exists.
"""

from __future__ import annotations

from typing import Any

from backend.stacks.execution_contracts import build_stack_execution_contract
from backend.stacks.templates import AgentStackTemplate, StackTaskTemplate


_AGENT_VERBS: dict[str, tuple[str, str, str, str]] = {
    "research": ("Collect evidence", "Analyze market/customer truth", "Produce sourced brief", "Declare confidence and gaps"),
    "design": ("Read research context", "Define creative system", "Produce UI/brand guidance", "Hand off production constraints"),
    "web": ("Read strategy and design", "Build conversion surface", "Prepare deployment handoff", "Queue public approval"),
    "technical": ("Map requirements", "Design architecture and data model", "Sequence implementation", "Expose delivery risks"),
    "marketing": ("Translate positioning", "Create campaign assets", "Define measurement loop", "Queue public/spend approval"),
    "sales": ("Define target accounts", "Build pipeline workflow", "Draft outreach assets", "Queue prospect/contact approval"),
    "legal": ("Identify regulated actions", "Draft safe starter docs", "Flag risks and caveats", "Queue legal/publication approval"),
    "ops": ("Synthesize lane outputs", "Build operating cadence", "Assign owners and dates", "Lock final handoff"),
}


def build_stack_execution_blueprint(
    stack: AgentStackTemplate,
    goal: str,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Build a work-executable plan for a deployed Agent Stack."""
    artifact_by_key = {artifact.key: artifact for artifact in stack.artifacts}
    contract = build_stack_execution_contract(stack)
    connector_map = _connector_map(stack)
    lane_packets = [
        _lane_packet(stack, task, index, artifact_by_key, connector_map)
        for index, task in enumerate(stack.tasks)
    ]
    approval_map = _approval_map(stack, lane_packets)
    calendar = _calendar(stack, lane_packets, contract)

    return {
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "company_name": company_name or "",
        "goal": goal,
        "blueprint_version": 1,
        "execution_mode": "agent_department",
        "outcome": stack.primary_outcome,
        "north_star": contract.get("north_star", stack.primary_outcome),
        "lanes": lane_packets,
        "approvals": approval_map,
        "calendar": calendar,
        "connector_dependencies": [
            {
                "key": connector.key,
                "label": connector.label,
                "required": connector.required,
                "used_by_lanes": [
                    lane["id"]
                    for lane in lane_packets
                    if connector.key in lane.get("connector_dependencies", [])
                ],
                "purpose": connector.purpose,
                "blocking_rule": "Required for hands-off execution" if connector.required else "Improves context or output quality",
            }
            for connector in stack.connector_requirements
        ],
        "artifact_acceptance_matrix": _artifact_acceptance_matrix(stack, lane_packets),
        "operating_controls": {
            "memory": "Every lane writes final artifacts, blockers, and decisions into Company Brain.",
            "permissions": "Private or sensitive records inherit founder/team visibility controls.",
            "approvals": "Public, financial, legal, outbound, or customer-impacting actions wait on durable approval decisions.",
            "handoff": "Each lane publishes consumed context, produced outputs, unresolved risks, and next actor.",
        },
        "completion_audit": [
            "All required lane packets are complete or marked blocked with a specific missing dependency.",
            "All required artifacts pass their acceptance checks.",
            "Every required approval is approved, skipped, or recorded as a founder next action.",
            "Company Brain contains the final stack summary, artifact ledger, decisions, and next actions.",
        ],
    }


def _lane_packet(
    stack: AgentStackTemplate,
    task: StackTaskTemplate,
    index: int,
    artifact_by_key: dict[str, Any],
    connector_map: dict[str, list[str]],
) -> dict[str, Any]:
    verbs = _AGENT_VERBS.get(task.agent, ("Load context", "Execute lane work", "Publish artifacts", "Hand off next actions"))
    deliverables = [
        {
            "artifact_key": key,
            "title": artifact_by_key[key].title,
            "required": artifact_by_key[key].required,
            "acceptance_checks": _artifact_checks(task, artifact_by_key[key].title),
        }
        for key in task.artifacts
        if key in artifact_by_key
    ]
    return {
        "id": task.id,
        "agent": task.agent,
        "title": task.title,
        "phase": getattr(task, "phase", "") or _phase(index, task),
        "mission": task.instruction,
        "depends_on": list(task.depends_on),
        "connector_dependencies": sorted(connector_map.get(task.agent, [])),
        "steps": [
            {"order": i + 1, "title": verb, "definition_of_done": _step_done(task, verb)}
            for i, verb in enumerate(verbs)
        ],
        "deliverables": deliverables,
        "approval_triggers": _lane_approval_triggers(stack, task),
        "handoff_packet": {
            "must_include": [
                "input context used",
                "artifact links or structured output",
                "decisions made",
                "open blockers",
                "recommended next owner",
            ],
            "downstream_lanes": [
                downstream.id
                for downstream in stack.tasks
                if task.id in downstream.depends_on
            ],
        },
        "status_model": ["waiting", "running", "blocked", "ready_for_review", "done"],
    }


def _connector_map(stack: AgentStackTemplate) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {task.agent: [] for task in stack.tasks}
    for connector in stack.connector_requirements:
        category = connector.category.lower()
        key = connector.key.lower()
        for agent in mapping:
            if _connector_matches_agent(key, category, agent):
                mapping[agent].append(connector.key)
    return mapping


def _connector_matches_agent(key: str, category: str, agent: str) -> bool:
    agent_terms = {
        "research": ("knowledge", "team_context", "documents", "data", "company_brain", "analytics"),
        "design": ("design", "publishing", "website", "figma"),
        "web": ("code", "deployment", "publishing", "website", "auth", "data"),
        "technical": ("code", "deployment", "data", "auth", "task_tracking", "product_data"),
        "marketing": ("outreach", "email", "social", "paid_media", "measurement", "publishing", "analytics"),
        "sales": ("sales", "sales_system", "outreach", "crm", "data"),
        "legal": ("documents", "knowledge", "company_brain"),
        "ops": ("knowledge", "documents", "cadence", "notifications", "team_context", "company_brain", "task_tracking"),
    }
    terms = agent_terms.get(agent, ())
    return category in terms or key in terms or any(term in category for term in terms)


def _approval_map(stack: AgentStackTemplate, lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": gate.key,
            "title": gate.title,
            "trigger": gate.trigger,
            "required_before": gate.required_before,
            "reason": gate.reason,
            "watch_lanes": [
                lane["id"]
                for lane in lanes
                if gate.key in lane.get("approval_triggers", []) or _gate_matches_lane(gate.key, lane)
            ],
            "state": "pending_until_triggered",
        }
        for gate in stack.approval_gates
    ]


def _calendar(stack: AgentStackTemplate, lanes: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    milestones = contract.get("milestones") or []
    calendar = []
    for index, milestone in enumerate(milestones):
        phase_lanes = [
            lane["id"]
            for lane in lanes
            if index == 0 or lane["phase"] in _milestone_phase_names(index)
        ]
        calendar.append({
            "day": milestone.get("day", index * 3),
            "title": milestone.get("title", f"Milestone {index + 1}"),
            "evidence": milestone.get("evidence", ""),
            "lane_ids": phase_lanes[: max(1, len(phase_lanes))],
        })
    if not calendar:
        calendar = [
            {"day": 0, "title": "Stack initialized", "evidence": "Goal, lanes, connectors, and approvals are known.", "lane_ids": [lane["id"] for lane in lanes[:1]]},
            {"day": 7, "title": "First outputs ready", "evidence": "Core lane artifacts are ready for review.", "lane_ids": [lane["id"] for lane in lanes]},
        ]
    return calendar


def _artifact_acceptance_matrix(stack: AgentStackTemplate, lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    owner_by_artifact = {
        deliverable["artifact_key"]: lane
        for lane in lanes
        for deliverable in lane["deliverables"]
    }
    return [
        {
            "artifact_key": artifact.key,
            "title": artifact.title,
            "owner_lane": owner_by_artifact.get(artifact.key, {}).get("id", ""),
            "owner_agent": artifact.owner_agent,
            "required": artifact.required,
            "checks": _artifact_checks(owner_by_artifact.get(artifact.key, {}).get("id", artifact.owner_agent), artifact.title),
        }
        for artifact in stack.artifacts
    ]


def _artifact_checks(task_or_agent: Any, title: str) -> list[str]:
    agent = getattr(task_or_agent, "agent", str(task_or_agent))
    checks = [
        f"{title} is specific to the founder goal and not generic filler.",
        "Includes evidence, assumptions, and open questions.",
        "Names the next owner or dependent lane.",
        "Is saved into the artifact ledger and available to Company Brain.",
    ]
    if agent in {"sales", "marketing", "web", "legal"}:
        checks.append("Flags any public, legal, financial, outbound, or brand-risk approval before action.")
    if agent in {"technical", "web"}:
        checks.append("Includes implementation or deployment handoff details.")
    return checks


def _lane_approval_triggers(stack: AgentStackTemplate, task: StackTaskTemplate) -> list[str]:
    text = f"{task.agent} {task.title} {task.instruction} {' '.join(task.artifacts)}".lower()
    triggers = []
    for gate in stack.approval_gates:
        gate_text = f"{gate.key} {gate.title} {gate.trigger} {gate.required_before}".lower()
        if any(term in text for term in ("outbound", "email", "prospect", "customer", "public", "deploy", "legal", "investor", "paid")):
            if any(term in gate_text for term in text.split()):
                triggers.append(gate.key)
        elif any(term in gate_text for term in (task.agent, task.title.lower())):
            triggers.append(gate.key)
    return sorted(set(triggers))


def _gate_matches_lane(gate_key: str, lane: dict[str, Any]) -> bool:
    text = f"{lane.get('agent', '')} {lane.get('title', '')} {lane.get('mission', '')}".lower()
    if "outbound" in gate_key or "prospect" in gate_key:
        return any(term in text for term in ("sales", "outbound", "prospect", "email"))
    if "deploy" in gate_key or "publish" in gate_key or "campaign" in gate_key:
        return any(term in text for term in ("web", "landing", "campaign", "public", "launch"))
    if "legal" in gate_key:
        return "legal" in text or "compliance" in text
    if "investor" in gate_key:
        return "investor" in text
    return False


_AGENT_PHASE: dict[str, str] = {
    "research": "diagnose",
    "design": "design",
    "web": "deploy",
    "technical": "deploy",
    "marketing": "deploy",
    "sales": "deploy",
    "legal": "govern",
    "finance": "govern",
    "ops": "operate",
}


def _phase(index: int, task: StackTaskTemplate) -> str:
    # Map by agent base name (most reliable signal)
    agent_base = task.agent.split("_")[0]
    if agent_base in _AGENT_PHASE:
        return _AGENT_PHASE[agent_base]
    # First task is always diagnose
    if index == 0:
        return "diagnose"
    return "deploy"


def _milestone_phase_names(index: int) -> set[str]:
    if index <= 1:
        return {"diagnose"}
    if index == 2:
        return {"design", "deploy"}
    if index == 3:
        return {"deploy", "govern"}
    return {"operate", "govern", "deploy"}


def _step_done(task: StackTaskTemplate, verb: str) -> str:
    return (
        f"{verb} is done when {task.title.lower()} has concrete evidence, "
        "explicit assumptions, and a handoff-ready note for downstream lanes."
    )

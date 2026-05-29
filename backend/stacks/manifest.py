"""Agent Department Manifest.

The manifest is the deployable contract for an Agent Stack: it describes the
AI department Astra creates around a business outcome, including lanes,
workflow edges, connector needs, dashboards, approvals, outputs, and the
founder/agent collaboration model.
"""

from __future__ import annotations

from typing import Any

from backend.stacks.operating_plan import build_stack_operating_plan
from backend.stacks.templates import AgentStackTemplate


def build_stack_manifest(
    stack: AgentStackTemplate,
    goal: str,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Build the full deployable department contract for a stack."""
    operating_plan = build_stack_operating_plan(stack, goal, company_name)
    task_by_id = {task.id: task for task in stack.tasks}
    artifact_by_key = {artifact.key: artifact for artifact in stack.artifacts}

    workflow_nodes = [
        {
            "id": task.id,
            "agent": task.agent,
            "title": task.title,
            "mission": task.instruction,
            "expected_outputs": [
                {
                    "key": key,
                    "title": artifact_by_key[key].title,
                    "required": artifact_by_key[key].required,
                }
                for key in task.artifacts
                if key in artifact_by_key
            ],
            "depends_on": list(task.depends_on),
        }
        for task in stack.tasks
    ]
    workflow_edges = [
        {
            "from": dependency,
            "to": task.id,
            "handoff": (
                f"{task_by_id.get(dependency).title if dependency in task_by_id else dependency} "
                f"feeds {task.title}"
            ),
        }
        for task in stack.tasks
        for dependency in task.depends_on
    ]

    dashboard_sections = [
        {
            "key": section.lower().replace(" ", "_").replace("-", "_"),
            "title": section,
            "purpose": _dashboard_purpose(section),
        }
        for section in stack.dashboard_sections
    ]

    return {
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "company_name": company_name or "",
        "goal": goal,
        "department_name": f"{stack.name} Department",
        "positioning": (
            "Astra deploys a coordinated AI department around the outcome, not a bag of "
            "individual agents. The manifest is the operating system each lane follows."
        ),
        "target_user": stack.target_user,
        "primary_outcome": stack.primary_outcome,
        "workflow": {
            "nodes": workflow_nodes,
            "edges": workflow_edges,
            "critical_path": _critical_path(stack),
        },
        "connectors": {
            "required": [
                _connector_to_manifest(connector)
                for connector in stack.connector_requirements
                if connector.required
            ],
            "optional": [
                _connector_to_manifest(connector)
                for connector in stack.connector_requirements
                if not connector.required
            ],
            "rule": "Required connectors must be connected or explicitly waived before hands-off execution.",
        },
        "dashboards": dashboard_sections,
        "approvals": [
            {
                "key": gate.key,
                "title": gate.title,
                "trigger": gate.trigger,
                "required_before": gate.required_before,
                "founder_control": gate.reason,
            }
            for gate in stack.approval_gates
        ],
        "outputs": [
            {
                "key": artifact.key,
                "title": artifact.title,
                "owner_agent": artifact.owner_agent,
                "description": artifact.description,
                "required": artifact.required,
                "acceptance": (
                    "Output is usable when it is specific to the goal, saved to the run, "
                    "available to dependent lanes, and captured by Company Brain."
                ),
            }
            for artifact in stack.artifacts
        ],
        "human_collaboration": {
            "founder_role": [
                "Set the outcome and constraints.",
                "Connect or waive required tools.",
                "Approve public, legal, financial, or reputation-impacting actions.",
                "Review final artifacts and decide what becomes canonical company memory.",
            ],
            "agent_role": [
                "Break the outcome into lane-owned work.",
                "Execute lane tasks with shared context.",
                "Publish artifacts, blockers, outcomes, and handoffs.",
                "Answer operational questions from the run and Company Brain.",
            ],
            "default_mode": "Agents execute routine work; founder approves sensitive actions and final direction.",
        },
        "memory_policy": {
            "canonical_records": [
                "stack decision",
                "company genome",
                "operating plan",
                "artifact ledger",
                "approval decisions",
                "outcomes and next actions",
            ],
            "retrieval_promises": [
                "What did a subteam do last week?",
                "What is blocked and who owns it?",
                "Which connectors are missing?",
                "What outputs are ready to use?",
            ],
        },
        "operating_plan": operating_plan,
    }


def _connector_to_manifest(connector: Any) -> dict[str, Any]:
    return {
        "key": connector.key,
        "label": connector.label,
        "category": connector.category,
        "purpose": connector.purpose,
        "required": connector.required,
    }


def _dashboard_purpose(section: str) -> str:
    key = section.lower()
    if "approval" in key:
        return "Show founder-controlled decisions before any sensitive action executes."
    if "artifact" in key:
        return "Track outputs, owners, status, and handoff readiness."
    if "brain" in key or "knowledge" in key:
        return "Expose company memory, source coverage, and retrievable operating context."
    if "agent" in key or "lane" in key:
        return "Show each agent lane, status, blockers, and next actor."
    if "plan" in key:
        return "Show milestones, dependencies, and next actions for execution."
    return "Provide an operator view of this stack's execution state."


def _critical_path(stack: AgentStackTemplate) -> list[str]:
    if not stack.tasks:
        return []
    downstream_count = {task.id: 0 for task in stack.tasks}
    for task in stack.tasks:
        for dependency in task.depends_on:
            if dependency in downstream_count:
                downstream_count[dependency] += 1
    ordered = sorted(
        stack.tasks,
        key=lambda task: (len(task.depends_on), -downstream_count.get(task.id, 0)),
    )
    return [task.id for task in ordered]

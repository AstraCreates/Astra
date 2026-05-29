"""Deterministic operating plans for Agent Stacks.

This is the deployable "AI department" contract: what lanes exist, what they
own, which approvals protect the founder, and what the stack should deliver.
"""

from __future__ import annotations

from typing import Any

from backend.stacks.templates import AgentStackTemplate


def _phase_for_task(task_id: str, index: int) -> str:
    key = task_id.lower()
    if any(term in key for term in ("research", "intel", "market")) or index == 0:
        return "Diagnose"
    if any(term in key for term in ("design", "technical", "product", "roadmap", "strategy")):
        return "Design"
    if any(term in key for term in ("web", "marketing", "sales", "support", "ops")):
        return "Deploy"
    if any(term in key for term in ("legal", "compliance")):
        return "Govern"
    return "Operate"


def build_stack_operating_plan(
    stack: AgentStackTemplate,
    goal: str,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Build the productized execution contract for a selected stack."""
    artifact_by_key = {artifact.key: artifact for artifact in stack.artifacts}
    lanes: list[dict[str, Any]] = []
    phases: dict[str, list[dict[str, str]]] = {}

    for index, task in enumerate(stack.tasks):
        owned_artifacts = [artifact_by_key[key] for key in task.artifacts if key in artifact_by_key]
        lane = {
            "id": task.id,
            "agent": task.agent,
            "title": task.title,
            "mission": task.instruction,
            "depends_on": list(task.depends_on),
            "artifact_keys": list(task.artifacts),
            "artifacts": [
                {
                    "key": artifact.key,
                    "title": artifact.title,
                    "description": artifact.description,
                    "required": artifact.required,
                }
                for artifact in owned_artifacts
            ],
            "handoff": (
                f"{task.title} hands off "
                f"{', '.join(artifact.title for artifact in owned_artifacts) or 'lane findings'} "
                "to dependent lanes and the final operating record."
            ),
        }
        lanes.append(lane)
        phase = _phase_for_task(task.id, index)
        phases.setdefault(phase, []).append({
            "lane_id": task.id,
            "agent": task.agent,
            "title": task.title,
        })

    required_connectors = [c for c in stack.connector_requirements if c.required]
    optional_connectors = [c for c in stack.connector_requirements if not c.required]
    required_artifacts = [a for a in stack.artifacts if a.required]

    return {
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "company_name": company_name or "",
        "goal": goal,
        "outcome": stack.primary_outcome,
        "operator_contract": (
            f"Astra converts the founder outcome into a deployed {stack.name}: "
            "specialized lanes, connector requirements, approval gates, dashboards, "
            "artifact ownership, and a completion definition."
        ),
        "phases": [
            {
                "name": name,
                "objective": {
                    "Diagnose": "Establish market, company, customer, and execution truth before building.",
                    "Design": "Translate findings into product, brand, system, and workflow decisions.",
                    "Deploy": "Produce shippable surfaces, workflows, campaigns, and operating assets.",
                    "Govern": "Keep public, legal, financial, and reputation-impacting actions founder-approved.",
                    "Operate": "Maintain cadence, memory, reporting, and next actions after the run.",
                }.get(name, "Move the company outcome forward with a specialized agent lane."),
                "lanes": lanes_for_phase,
            }
            for name, lanes_for_phase in phases.items()
        ],
        "lanes": lanes,
        "connector_plan": {
            "required": [
                {
                    "key": c.key,
                    "label": c.label,
                    "category": c.category,
                    "purpose": c.purpose,
                }
                for c in required_connectors
            ],
            "optional": [
                {
                    "key": c.key,
                    "label": c.label,
                    "category": c.category,
                    "purpose": c.purpose,
                }
                for c in optional_connectors
            ],
            "setup_rule": "Required connectors block hands-off execution; optional connectors improve context or distribution.",
        },
        "approval_policy": [
            {
                "key": gate.key,
                "title": gate.title,
                "trigger": gate.trigger,
                "required_before": gate.required_before,
                "reason": gate.reason,
            }
            for gate in stack.approval_gates
        ],
        "artifact_contract": [
            {
                "key": artifact.key,
                "title": artifact.title,
                "owner_agent": artifact.owner_agent,
                "description": artifact.description,
                "required": artifact.required,
                "acceptance": (
                    "Ready when it is specific to the founder goal, usable by the next lane, "
                    "and captured in the session artifact ledger."
                ),
            }
            for artifact in stack.artifacts
        ],
        "cadence": {
            "day_0": "Capture company genome, choose stack, check connector readiness, and arm approval gates.",
            "week_1": "Complete diagnosis and first shippable drafts.",
            "week_2": "Connect tools, refine outputs, and execute approved actions.",
            "week_3": "Measure outcomes, fill gaps, and prepare handoff materials.",
            "week_4": "Lock the operating record, next actions, and recurring subteam reporting.",
        },
        "completion_definition": list(stack.completion_rules) + [
            f"{len(required_artifacts)} required artifacts are either ready or explicitly blocked.",
            "Company Brain has the stack decision, company genome, artifact ledger, and next actions.",
        ],
    }

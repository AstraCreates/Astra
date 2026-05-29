"""Company Genome snapshot builder.

The genome is the run-level operating context Astra should remember: what the
company is trying to become, which stack is deployed, what artifacts matter,
which connectors are required, and where approvals are needed.
"""
from __future__ import annotations

import re
from typing import Any


def _keywords(text: str, limit: int = 12) -> list[str]:
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your",
        "you", "are", "build", "create", "launch", "astra", "company",
        "using", "need", "will", "should", "their", "them", "have",
    }
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        if word in stop or word in seen:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= limit:
            break
    return out


def build_company_genome(
    *,
    session_id: str,
    founder_id: str,
    company_name: str,
    goal: str,
    stack_template: Any,
    brain_context: str = "",
) -> dict[str, Any]:
    connectors = list(getattr(stack_template, "connector_requirements", []))
    artifacts = list(getattr(stack_template, "artifacts", []))
    approval_gates = list(getattr(stack_template, "approval_gates", []))
    tasks = list(getattr(stack_template, "tasks", []))
    genome = {
        "session_id": session_id,
        "founder_id": founder_id,
        "company_name": company_name,
        "goal": goal,
        "keywords": _keywords(goal),
        "stack": {
            "id": getattr(stack_template, "stack_id", ""),
            "name": getattr(stack_template, "name", ""),
            "target_user": getattr(stack_template, "target_user", ""),
            "primary_outcome": getattr(stack_template, "primary_outcome", ""),
            "dashboard_sections": list(getattr(stack_template, "dashboard_sections", [])),
        },
        "operating_model": {
            "agent_lanes": [
                {
                    "id": getattr(task, "id", ""),
                    "agent": getattr(task, "agent", ""),
                    "title": getattr(task, "title", ""),
                    "artifacts": list(getattr(task, "artifacts", [])),
                }
                for task in tasks
            ],
            "required_connectors": [
                {
                    "key": getattr(connector, "key", ""),
                    "label": getattr(connector, "label", ""),
                    "category": getattr(connector, "category", ""),
                    "purpose": getattr(connector, "purpose", ""),
                }
                for connector in connectors
                if getattr(connector, "required", False)
            ],
            "optional_connectors": [
                {
                    "key": getattr(connector, "key", ""),
                    "label": getattr(connector, "label", ""),
                    "category": getattr(connector, "category", ""),
                }
                for connector in connectors
                if not getattr(connector, "required", False)
            ],
            "approval_gates": [
                {
                    "key": getattr(gate, "key", ""),
                    "title": getattr(gate, "title", ""),
                    "required_before": getattr(gate, "required_before", ""),
                    "reason": getattr(gate, "reason", ""),
                }
                for gate in approval_gates
            ],
            "expected_artifacts": [
                {
                    "key": getattr(artifact, "key", ""),
                    "title": getattr(artifact, "title", ""),
                    "owner_agent": getattr(artifact, "owner_agent", ""),
                    "required": getattr(artifact, "required", True),
                }
                for artifact in artifacts
            ],
        },
        "memory": {
            "prior_context_available": bool(brain_context.strip()),
            "context_preview": brain_context.strip().replace("\n", " ")[:420],
        },
    }
    return genome

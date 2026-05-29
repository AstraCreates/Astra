"""Approval queue construction for stack runs."""
from __future__ import annotations

from typing import Any

from backend.stacks.templates import AgentStackTemplate


def build_approval_queue(stack_template: AgentStackTemplate) -> list[dict[str, Any]]:
    """Create the initial founder approval queue for a selected stack."""
    return [
        {
            "key": gate.key,
            "title": gate.title,
            "trigger": gate.trigger,
            "required_before": gate.required_before,
            "reason": gate.reason,
            "status": "armed",
            "triggered_by": None,
        }
        for gate in stack_template.approval_gates
    ]

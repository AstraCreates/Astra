"""Project n8n-style automation flows onto Company Operations work.

The canvas remains a useful authoring surface, but its execution is no longer
an untracked run: each graph node is represented by a Company OS task and all
external effects are stopped at the Company OS approval boundary.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.company_os import create_mission, create_task, ensure_company_operations, get_company_os, list_company_os, update_task
from backend.company_os_dispatch import _create_approval_card, _record_policy, enforce_dispatch_policy


_EXTERNAL_NODE_TYPES = {"action", "slack", "email", "gmail", "slack_bot", "github_issue", "github_pr", "linear_issue", "notion_page", "stripe_payment_link", "integration"}


def prepare_flow_run(founder_id: str, flow: Mapping[str, Any], run_id: str) -> dict[str, Any] | None:
    """Create a Company Operations mission and preflight every automation node."""
    company = next(iter(list_company_os(founder_id)), None)
    if not company:
        return None
    company_id = company["company_id"]
    operations = ensure_company_operations(company_id)
    state = get_company_os(company_id) or company
    squad = next((item for item in state.get("squads", []) if item.get("initiative_id") == operations["initiative_id"] and item.get("state") != "archived"), None)
    if not squad:
        return None
    mission = create_mission(company_id, operations["initiative_id"], squad["squad_id"], f"Automation: {flow.get('name') or flow.get('id')}", department="operations", state="active", automation_run_id=run_id, flow_id=flow.get("id"))
    tasks: dict[str, dict[str, Any]] = {}
    requires_approval = False
    for node in flow.get("nodes") or []:
        node_type = str(node.get("type") or "unknown")
        cfg = node.get("config") or {}
        title = str(node.get("label") or cfg.get("name") or f"{node_type.replace('_', ' ').title()} node")
        operation = "external_automation" if node_type in _EXTERNAL_NODE_TYPES else "internal_analysis"
        policy = enforce_dispatch_policy({"title": title, "description": str(cfg.get("instruction") or cfg.get("message") or ""), "operation": operation, "external": node_type in _EXTERNAL_NODE_TYPES}, company=state)
        task = create_task(company_id, operations["initiative_id"], squad["squad_id"], title, mission_id=mission["mission_id"], department="operations", operation=operation, state="awaiting_approval" if policy["decision"] != "auto" else "pending", policy_decision=policy, automation_node_id=node.get("id"), automation_run_id=run_id)
        _record_policy(company_id, task, policy)
        if policy["decision"] != "auto":
            _create_approval_card(company_id, task, policy)
        tasks[str(node.get("id"))] = task
        requires_approval = requires_approval or policy["decision"] != "auto"
    return {"company_id": company_id, "mission_id": mission["mission_id"], "tasks": tasks, "requires_approval": requires_approval}


def update_node_task(context: Mapping[str, Any] | None, node_id: str, state: str, *, error: str | None = None) -> None:
    if not context or node_id not in context.get("tasks", {}):
        return
    task = context["tasks"][node_id]
    update_task(context["company_id"], task["task_id"], state=state, **({"blocked_reason": error} if error else {}))

"""Permanent Company Copilot turn coordinator.

The coordinator deliberately has a short, inspectable tool loop: retrieve
Company Brain context through MCP, inspect credits through MCP, then delegate
the scoped work to a department head.  The department head's tasks also invoke
MCP through ``company_os_mcp``.  No legacy session is created.
"""
from __future__ import annotations

import asyncio
from typing import Any

from backend.company_os import append_message
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_mcp import invoke
from backend.company_os_runner import launch_mission


async def coordinate_turn(company_id: str, message: str, *, proposed_spend: float = 0.0) -> dict[str, Any]:
    """Run one permanent Copilot turn using the MCP tool contract."""
    brain, credits = await asyncio.gather(
        asyncio.to_thread(invoke, company_id, "astra_search_brain", {"query": message, "limit": 6}),
        asyncio.to_thread(invoke, company_id, "astra_credits", {}),
        return_exceptions=True,
    )
    dispatch = await asyncio.to_thread(dispatch_intent, company_id, message, proposed_spend=proposed_spend)
    squad = dispatch["squad"]
    initiative = dispatch["initiative"]
    department = dispatch["department"].replace("_", " ").title()
    grounding = _grounding_summary(brain)
    budget = _budget_summary(credits)
    acknowledgement = (
        f"I formed the {squad['name'].title()} Squad within {initiative['name']}. "
        f"The {department} Lead is coordinating the mission through Astra tools."
        f"{grounding}{budget} I will return with a decision-ready update or an approval card."
    )
    append_message(company_id, acknowledgement, author="copilot", role="assistant", scope="initiative", scope_id=initiative["initiative_id"], kind="chat")
    launch_mission(company_id, dispatch["mission"]["mission_id"])
    return {"message": acknowledgement, "dispatch": dispatch}


def _grounding_summary(result: Any) -> str:
    if isinstance(result, Exception) or not isinstance(result, dict) or result.get("error"):
        return " I could not retrieve matching Company Brain context, so this mission will establish fresh evidence."
    records = result.get("records") or result.get("results") or []
    return f" I checked {len(records)} relevant Company Brain record{'s' if len(records) != 1 else ''}."


def _budget_summary(result: Any) -> str:
    if isinstance(result, Exception) or not isinstance(result, dict) or result.get("error"):
        return ""
    return " I also checked the current tool budget before dispatching."

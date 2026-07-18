"""Isolated, observable delegated-agent execution."""
from __future__ import annotations

import asyncio
import hashlib
import threading
import time
import uuid
from typing import Any

from backend.core.agent import Agent, AgentContext
from backend.runtime.budget import RunBudget
from backend.runtime.tool_registry import registry

BLOCKED_TOOLSETS = frozenset({
    "company_brain_write", "outreach_send", "deployment", "billing", "provisioning",
})
BLOCKED_TOOLS = frozenset({
    "delegate_task", "send_email_campaign", "composio_gmail_send",
    "composio_linkedin_post", "vercel_deploy", "vercel_deploy_from_github",
    "create_stripe_product", "create_stripe_price", "create_stripe_payment_link",
    "company_brain_add_record", "company_brain_ingest_records",
})

_active: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_semaphores: dict[str, asyncio.Semaphore] = {}
_MAX_SUBAGENTS_PER_SESSION = 3
_MAX_QUEUED_SUBAGENTS_PER_PARENT = 2
_MAX_TASK_CHARS = 4000


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _delegation_fingerprint(parent_name: str, parent_task_id: str, role: str, task: str) -> str:
    normalized = f"{parent_name}|{parent_task_id}|{_normalize_text(role).lower()}|{_normalize_text(task).lower()}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _snapshot_session_records(session_id: str) -> list[dict[str, Any]]:
    with _lock:
        return [record.copy() for record in _active.values() if record.get("session_id") == session_id]


def list_active_subagents(session_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        records = list(_active.values())
    return [
        {key: value for key, value in record.items() if key != "agent"}
        for record in records
        if session_id is None or record.get("session_id") == session_id
    ]


def interrupt_session_subagents(session_id: str) -> int:
    interrupted = 0
    with _lock:
        records = [record for record in _active.values() if record.get("session_id") == session_id]
    for record in records:
        task = record.get("task_handle")
        if task is not None and not task.done():
            task.cancel()
            interrupted += 1
    return interrupted


def _find_restricted_requests(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("restricted_action_requested") and value.get("tool"):
            found.append(value)
        for nested in value.values():
            found.extend(_find_restricted_requests(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_find_restricted_requests(nested))
    return found


async def run_delegated_task(
    *,
    parent: Agent,
    ctx: AgentContext,
    role: str,
    task: str,
    toolsets: list[str] | None = None,
    expected_output_schema: dict[str, Any] | None = None,
    max_iterations: int = 20,
) -> dict[str, Any]:
    from backend.core.events import publish

    role = _normalize_text(role)
    task = (task or "").strip()
    if not role:
        return {"error": "Delegated subagent role is required"}
    if not task:
        return {"error": "Delegated subagent task is required"}
    if len(task) > _MAX_TASK_CHARS:
        task = task[:_MAX_TASK_CHARS]
    if ctx.delegation_depth >= 1:
        return {"error": "Delegation depth limit reached", "restricted_action": "delegate_task"}
    requested_sets = [name for name in (toolsets or []) if name not in BLOCKED_TOOLSETS]
    entries = registry.resolve(toolsets=requested_sets)
    tools = {}
    for name, entry in entries.items():
        if name in BLOCKED_TOOLS or entry.mutability == "external":
            continue

        # Child agents must use the same schema validation, context injection,
        # coercion, result bounds, and accounting path as top-level agents.
        # Passing raw handlers here silently bypassed the runtime registry.
        async def _dispatch_child_tool(_entry=entry, **args):
            return await registry.dispatch(
                _entry,
                args,
                {"founder_id": ctx.founder_id, "session_id": ctx.session_id},
            )

        _dispatch_child_tool.__name__ = name
        _dispatch_child_tool.__doc__ = entry.description or name
        tools[name] = _dispatch_child_tool
    restricted_entries = {
        name: entry for name, entry in registry.snapshot().items()
        if name in BLOCKED_TOOLS or entry.mutability == "external"
    }

    fingerprint = _delegation_fingerprint(parent.name, ctx.task_id, role, task)
    session_records = _snapshot_session_records(ctx.session_id)
    session_active = len(session_records)
    parent_active = [
        record for record in session_records
        if record.get("parent_agent") == parent.name and record.get("parent_task_id") == ctx.task_id
    ]
    duplicate = next((record for record in parent_active if record.get("fingerprint") == fingerprint), None)
    if duplicate:
        await publish(ctx.session_id, {
            "type": "subagent_rejected",
            "reason": "duplicate",
            "parent_agent": parent.name,
            "parent_task_id": ctx.task_id,
            "existing_subagent_id": duplicate.get("subagent_id"),
            "role": role,
        })
        return {
            "error": "Duplicate delegated task already active",
            "reason": "duplicate",
            "existing_subagent_id": duplicate.get("subagent_id"),
        }
    if session_active >= _MAX_SUBAGENTS_PER_SESSION:
        await publish(ctx.session_id, {
            "type": "subagent_rejected",
            "reason": "session_limit",
            "parent_agent": parent.name,
            "parent_task_id": ctx.task_id,
            "limit": _MAX_SUBAGENTS_PER_SESSION,
            "active": session_active,
            "role": role,
        })
        return {
            "error": f"Subagent session limit reached ({_MAX_SUBAGENTS_PER_SESSION})",
            "reason": "session_limit",
            "active": session_active,
        }
    if len(parent_active) >= _MAX_QUEUED_SUBAGENTS_PER_PARENT:
        await publish(ctx.session_id, {
            "type": "subagent_rejected",
            "reason": "parent_limit",
            "parent_agent": parent.name,
            "parent_task_id": ctx.task_id,
            "limit": _MAX_QUEUED_SUBAGENTS_PER_PARENT,
            "active": len(parent_active),
            "role": role,
        })
        return {
            "error": f"Parent subagent limit reached ({_MAX_QUEUED_SUBAGENTS_PER_PARENT})",
            "reason": "parent_limit",
            "active": len(parent_active),
        }

    def request_action(tool_name: str):
        def handler(**args):
            from backend.core.events import publish_sync
            publish_sync(ctx.session_id, {
                "type": "subagent_action_requested",
                "subagent_id": subagent_id,
                "parent_agent": parent.name,
                "tool": tool_name,
                "args": args,
            })
            return {
                "restricted_action_requested": True,
                "tool": tool_name,
                "args": args,
                "message": "The parent agent must approve and execute this action.",
            }
        return handler

    for name in restricted_entries:
        if name != "delegate_task":
            tools[name] = request_action(name)
    subagent_id = f"sub_{uuid.uuid4().hex[:12]}"
    child = Agent(
        name=f"{parent.name}:{role}",
        role=role,
        tools=tools,
        max_iterations=min(max_iterations, 50),
    )
    budget = ctx.budget.child(max_iterations=min(max_iterations, 50)) if ctx.budget else RunBudget(max_iterations)
    record = {
        "subagent_id": subagent_id,
        "session_id": ctx.session_id,
        "parent_agent": parent.name,
        "parent_task_id": ctx.task_id,
        "role": role,
        "task": task[:500],
        "fingerprint": fingerprint,
        "status": "spawned",
        "started_at": time.time(),
        "agent": child,
    }
    with _lock:
        _active[subagent_id] = record
    await publish(ctx.session_id, {"type": "subagent_spawned", **{k: v for k, v in record.items() if k != "agent"}})
    semaphore = _semaphores.setdefault(ctx.session_id, asyncio.Semaphore(_MAX_SUBAGENTS_PER_SESSION))
    try:
        async with semaphore:
            record["task_handle"] = asyncio.current_task()
            record["status"] = "running"
            await publish(ctx.session_id, {"type": "subagent_started", "subagent_id": subagent_id, "role": role})
            child_ctx = AgentContext(
                goal=task,
                founder_id=ctx.founder_id,
                session_id=ctx.session_id,
                task_id=subagent_id,
                shared={
                    "company_brain_context": ctx.shared.get("company_brain_context", ""),
                    "current_company_goal": ctx.shared.get("current_company_goal", {}),
                    "delegation": {"parent_agent": parent.name, "expected_output_schema": expected_output_schema or {}},
                },
                budget=budget,
                delegation_depth=ctx.delegation_depth + 1,
                parent_agent=parent.name,
                parent_task_id=ctx.task_id,
            )
            result = await child.run(child_ctx)
            action_requests = _find_restricted_requests(result)
            record["status"] = "completed"
            await publish(ctx.session_id, {
                "type": "subagent_completed", "subagent_id": subagent_id,
                "role": role, "result": result,
            })
            return {
                "subagent_id": subagent_id,
                "role": role,
                "result": result,
                "restricted_action_requests": action_requests,
                "parent_action_results": [],
            }
    except asyncio.CancelledError:
        record["status"] = "interrupted"
        await publish(ctx.session_id, {"type": "subagent_interrupted", "subagent_id": subagent_id})
        raise
    except Exception as exc:
        record["status"] = "failed"
        await publish(ctx.session_id, {"type": "subagent_failed", "subagent_id": subagent_id, "error": str(exc)[:400]})
        return {"error": str(exc), "subagent_id": subagent_id}
    finally:
        with _lock:
            _active.pop(subagent_id, None)
            if not any(record.get("session_id") == ctx.session_id for record in _active.values()):
                _semaphores.pop(ctx.session_id, None)

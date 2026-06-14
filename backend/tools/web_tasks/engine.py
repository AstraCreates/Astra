from __future__ import annotations

import asyncio
import uuid
from typing import Any

from backend.core.events import publish_sync
from backend.tools.web_tasks.adapters import resolve_adapter
from backend.tools.web_tasks.base import WebTaskContext
from backend.tools.web_tasks.models import (
    WebTaskBlocker,
    WebTaskRequest,
    WebTaskResult,
    WebTaskSnapshot,
)
from backend.tools.web_tasks.state_machine import run_generic_web_task
from backend.tools.web_tasks.store import (
    close_task_session,
    create_task_session,
    get_task_session,
    load_snapshot,
    save_snapshot,
    set_task_status,
)


def _normalize_request(
    task_type: str,
    service: str,
    goal: str,
    success_criteria: list[str] | str | None = None,
    credentials: dict[str, Any] | None = None,
    founder_id: str = "",
    session_id: str = "",
    task_id: str = "",
    agent: str = "",
    start_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> WebTaskRequest:
    criteria = success_criteria or []
    if isinstance(criteria, str):
        criteria = [criteria]
    normalized_task_id = task_id or uuid.uuid4().hex
    return WebTaskRequest(
        task_type=task_type,
        service=service,
        goal=goal,
        success_criteria=[str(item) for item in criteria if str(item).strip()],
        credentials=dict(credentials or {}),
        founder_id=founder_id,
        session_id=session_id or normalized_task_id,
        task_id=normalized_task_id,
        agent=agent,
        start_url=start_url,
        metadata=dict(metadata or {}),
    )


def _build_snapshot(request: WebTaskRequest) -> WebTaskSnapshot:
    existing = load_snapshot(request.session_id, request.task_id)
    if existing is not None:
        existing.request = request
        return existing
    snapshot = WebTaskSnapshot(
        task_id=request.task_id,
        request=request,
        credentials=dict(request.credentials),
    )
    save_snapshot(snapshot)
    return snapshot


async def _run_single_task(ctx: WebTaskContext) -> WebTaskResult:
    adapter = resolve_adapter(ctx.request.service, ctx.request.task_type)
    if adapter is not None:
        return await adapter.run(ctx)
    return await run_generic_web_task(ctx)


async def _run_composite_saas_task(ctx: WebTaskContext) -> WebTaskResult:
    substeps = [
        ("github", "login_or_signup", ["github_authenticated"]),
        ("vercel", "retrieve_deploy_token", ["deploy_token_extracted"]),
        ("supabase", "create_project", ["project_created", "project_keys_extracted"]),
    ]
    combined: dict[str, Any] = {}
    for service, task_type, criteria in substeps:
        sub_result = await run_web_task(
            task_type=task_type,
            service=service,
            goal=f"{ctx.request.goal} [{service}]",
            success_criteria=criteria,
            credentials=dict(ctx.snapshot.credentials),
            founder_id=ctx.request.founder_id,
            session_id=ctx.request.session_id,
            task_id=f"{ctx.task_id}-{service}",
            agent=ctx.request.agent,
            metadata=dict(ctx.request.metadata),
        )
        if sub_result.get("status") != "completed":
            return WebTaskResult(
                status=sub_result.get("status", "failed"),
                service=ctx.request.service,
                task_type=ctx.request.task_type,
                artifacts={"completed_steps": combined, "current_step": service},
                evidence=ctx.snapshot.evidence,
                blocker=WebTaskBlocker.from_dict(sub_result.get("blocker")),
                resume_token=sub_result.get("resume_token", ctx.task_id),
            )
        combined[service] = sub_result.get("artifacts", {}).get(service) or sub_result.get("artifacts", {})
    await ctx.add_check("github_authenticated")
    await ctx.add_check("deploy_token_extracted")
    await ctx.add_check("project_keys_extracted")
    return await ctx.complete({"github": combined.get("github", {}), "vercel": combined.get("vercel", {}), "supabase": combined.get("supabase", {})})


async def run_web_task(
    task_type: str,
    service: str,
    goal: str,
    success_criteria: list[str] | str | None = None,
    credentials: dict[str, Any] | None = None,
    founder_id: str = "",
    session_id: str = "",
    task_id: str = "",
    agent: str = "",
    start_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = _normalize_request(
        task_type=task_type,
        service=service,
        goal=goal,
        success_criteria=success_criteria,
        credentials=credentials,
        founder_id=founder_id,
        session_id=session_id,
        task_id=task_id,
        agent=agent,
        start_url=start_url,
        metadata=metadata,
    )
    snapshot = _build_snapshot(request)
    snapshot.input_data = dict(snapshot.input_data or {})
    snapshot.credentials.update(request.credentials)
    ctx = WebTaskContext(request=request, snapshot=snapshot)
    ctx.merge_credentials()
    save_snapshot(snapshot)
    await ctx.emit("web_task_started", goal=goal, service=service, task_type=task_type)
    try:
        if request.service == "saas_build_stack" and request.task_type == "provision_saas_build_stack":
            result = await _run_composite_saas_task(ctx)
        else:
            result = await _run_single_task(ctx)
    except Exception as exc:
        result = await ctx.fail(str(exc))
    finally:
        await ctx.close()
    return result.to_dict()


def create_web_task_session(task_id: str) -> dict:
    return create_task_session(task_id)


def get_web_task_session(task_id: str) -> dict | None:
    return get_task_session(task_id)


async def _background_run(request: WebTaskRequest) -> None:
    session = create_task_session(request.task_id)
    session["request"] = request
    session["status"] = "running"
    result = await run_web_task(
        task_type=request.task_type,
        service=request.service,
        goal=request.goal,
        success_criteria=request.success_criteria,
        credentials=request.credentials,
        founder_id=request.founder_id,
        session_id=request.session_id,
        task_id=request.task_id,
        agent=request.agent,
        start_url=request.start_url,
        metadata=request.metadata,
    )
    set_task_status(request.task_id, result.get("status", "done"), result)
    if result.get("status") in {"completed", "blocked", "failed"}:
        await close_task_session(request.task_id, result)


def start_web_task_background(
    *,
    task_type: str,
    service: str,
    goal: str,
    success_criteria: list[str] | str | None = None,
    credentials: dict[str, Any] | None = None,
    founder_id: str = "",
    session_id: str = "",
    task_id: str = "",
    agent: str = "",
    start_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> WebTaskRequest:
    request = _normalize_request(
        task_type=task_type,
        service=service,
        goal=goal,
        success_criteria=success_criteria,
        credentials=credentials,
        founder_id=founder_id,
        session_id=session_id,
        task_id=task_id,
        agent=agent,
        start_url=start_url,
        metadata=metadata,
    )
    session = create_task_session(request.task_id)
    existing_task = session.get("task")
    if existing_task and not existing_task.done():
        return request
    session["task"] = asyncio.create_task(_background_run(request))
    return request


def resume_web_task_session(task_id: str, input_data: dict[str, Any]) -> bool:
    session = get_task_session(task_id)
    if not session:
        return False
    result = session.get("last_result") or {}
    if session.get("status") != "needs_user" and result.get("status") != "needs_user":
        return False
    request = session.get("request")
    session_id = getattr(request, "session_id", "") or task_id
    snapshot = load_snapshot(session_id, task_id)
    if snapshot is None:
        return False
    snapshot.input_data.update(input_data or {})
    snapshot.credentials.update(input_data or {})
    save_snapshot(snapshot)
    request = snapshot.request
    session["status"] = "running"
    try:
        session["event_queue"].put_nowait({
            "type": "web_task_resumed",
            "task_id": task_id,
            "service": request.service,
            "task_type": request.task_type,
            "agent": request.agent,
        })
    except Exception:
        pass
    if request.session_id:
        try:
            publish_sync(request.session_id, {
                "type": "web_task_resumed",
                "task_id": task_id,
                "service": request.service,
                "task_type": request.task_type,
                "agent": request.agent,
            })
        except Exception:
            pass
    session["task"] = asyncio.create_task(_background_run(request))
    return True

"""Company OS API: the permanent Copilot thread and its durable work graph."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, model_validator

from backend.company_os import append_message, create_company_os, create_thread, ensure_company_operations, ensure_default_chat_thread, get_company_os, on_mutation, reconcile_initiatives, update_artifact, update_approval, update_initiative, update_message, update_mission, update_squad, update_task, update_thread
from backend.company_os_copilot import coordinate_turn
from backend.company_os_dispatch import scheduler_tick
from backend.core.lt_cache import ttl_cache, bump as cache_bump
from backend.tenant_auth import require_founder_access

logger = logging.getLogger(__name__)
router = APIRouter(tags=["company-os"])
_HOSTED_PREVIEW_ROOT = Path(os.environ.get("ASTRA_HOSTED_SITE_ROOT", "/tmp/astra_sites"))


class CompanyOSCreateBody(BaseModel):
    founder_id: str
    name: str = Field(min_length=1, max_length=160)
    company_id: str | None = None


class CopilotAttachmentBody(BaseModel):
    name: str
    content: str = Field(default="", max_length=20_000)


class CopilotMessageBody(BaseModel):
    founder_id: str
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: str = Field(default="default", max_length=64)
    proposed_spend: float = Field(default=0, ge=0)
    attachments: list[CopilotAttachmentBody] = Field(default_factory=list)


class ChatThreadCreateBody(BaseModel):
    founder_id: str
    title: str = Field(default="New chat", min_length=1, max_length=160)


class ChatThreadRenameBody(BaseModel):
    founder_id: str
    title: str = Field(min_length=1, max_length=160)


class MessageEditBody(BaseModel):
    founder_id: str
    message: str = Field(min_length=1, max_length=20_000)


class InitiativeEditBody(BaseModel):
    founder_id: str
    name: str | None = Field(default=None, min_length=1, max_length=160)
    objective: str | None = Field(default=None, max_length=10_000)
    success_criteria: list[str] | None = None
    priority: str | None = Field(default=None, max_length=40)
    owner: str | None = Field(default=None, max_length=160)
    budget: dict[str, Any] | str | None = None
    due_date: str | None = Field(default=None, max_length=64)
    state: str | None = Field(default=None, max_length=32)
    roadmap: list[dict[str, Any]] | None = None
    dependencies: list[dict[str, Any]] | None = None
    decisions: list[dict[str, Any]] | None = None
    acceptance_confirmed: bool | None = None


class ApprovalDecisionBody(BaseModel):
    founder_id: str
    approved: bool = True
    note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="before")
    @classmethod
    def accept_json_string_envelope(cls, value: Any) -> Any:
        """Tolerate proxy layers that forward a JSON body as a JSON string."""
        if isinstance(value, str):
            try:
                import json
                decoded = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Approval body must be a JSON object") from exc
            if isinstance(decoded, dict):
                return decoded
        return value


class SquadControlBody(BaseModel):
    founder_id: str
    action: str = Field(pattern="^(pause|resume|cancel)$")


@router.get("/hosted-preview/{project_slug}/{asset_path:path}")
@router.get("/hosted-preview/{project_slug}")
async def hosted_company_preview(project_slug: str, asset_path: str = ""):
    """Serve a published server fallback without exposing arbitrary files."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", project_slug):
        raise HTTPException(status_code=404, detail="Preview not found")
    root = (_HOSTED_PREVIEW_ROOT / project_slug).resolve()
    candidate = (root / (asset_path or "index.html")).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=404, detail="Preview not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(candidate)


def _message(company_id: str, message_id: str) -> dict[str, Any]:
    company = get_company_os(company_id) or {}
    message = next((item for item in company.get("conversation", []) if item.get("message_id") == message_id), None)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _artifact(company_id: str, artifact_id: str) -> dict[str, Any]:
    company = get_company_os(company_id) or {}
    artifact = next((item for item in company.get("artifacts", []) if item.get("artifact_id") == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


def _dismiss_pending_approvals(company_id: str, company: dict[str, Any], *, reason: str) -> None:
    """Invalidate approval cards whose originating chat context was discarded."""
    task_ids = set()
    for approval in company.get("approvals", []):
        if approval.get("state") != "pending":
            continue
        update_approval(company_id, approval["approval_id"], state="dismissed", note=reason)
        if approval.get("task_id"):
            task_ids.add(str(approval["task_id"]))
    for task in company.get("tasks", []):
        if str(task.get("task_id")) in task_ids and task.get("state") == "awaiting_approval":
            update_task(company_id, task["task_id"], state="blocked", blocked_reason=reason)


def _ensure_default_chat_thread_reflected(company: dict[str, Any], company_id: str) -> None:
    """ensure_default_chat_thread() may just have created the record via a
    fresh append_event -- but `company` here was fetched before that call
    ran, so its own chat_threads list is stale on a brand-new company. Patch
    the known result in rather than paying for another get_company_os()."""
    thread = ensure_default_chat_thread(company_id)
    if not any(item.get("thread_id") == thread["thread_id"] for item in company.get("chat_threads", [])):
        company["chat_threads"] = company.get("chat_threads", []) + [thread]


def _company(request: Request, company_id: str, founder_id: str, *, operator: bool = False) -> dict[str, Any]:
    """Authorize access, then lazily create the local Company OS for a new company."""
    require_founder_access(request, founder_id, min_role="operator" if operator else "viewer")
    company = get_company_os(company_id)
    if company:
        if company["founder_id"] != founder_id:
            raise HTTPException(status_code=404, detail="Company not found")
        ensure_company_operations(company_id)
        _ensure_default_chat_thread_reflected(company, company_id)
        return company
    created = create_company_os(company_id, founder_id, "Company")
    ensure_company_operations(company_id)
    _ensure_default_chat_thread_reflected(created, company_id)
    return created


@router.post("/company-os")
async def create_company_os_route(body: CompanyOSCreateBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")
    company_id = body.company_id or body.founder_id
    company = create_company_os(company_id, body.founder_id, body.name)
    ensure_company_operations(company_id)
    return get_company_os(company_id) or company


# Hot read ─ multiple panels poll this 5-30s. The 2-second TTL is the
# cheapest way to collapse the stampeding herd without making the UI feel
# stale.
#
# policy_decisions/mcp_audit/dispatch_audit/task_attempts are write-only
# backend audit trails -- confirmed zero references anywhere in frontend/,
# and nothing else in backend/ ever reads them back either. On the busiest
# real company these four collections alone were ~4.3MB of an 11MB snapshot
# (policy_decisions was 15k+ entries, 3.6MB by itself), fully re-serialized
# to the browser on every single poll for data nothing ever displays.
# Dropped from this response only -- they stay intact in the underlying
# event-sourced state for any future internal/debugging use.
_DASHBOARD_EXCLUDED_COLLECTIONS = ("policy_decisions", "mcp_audit", "dispatch_audit", "task_attempts")


@ttl_cache(ttl_seconds=2)
def _read_company_os_state(company_id: str) -> dict[str, Any]:
    state = reconcile_initiatives(company_id)
    return {key: value for key, value in state.items() if key not in _DASHBOARD_EXCLUDED_COLLECTIONS}


# Every durable mutation -- not just approvals -- must invalidate this cache,
# or a poll landing within the 2s window after a founder sends a message,
# edits/deletes a message, edits an initiative, etc. serves a stale response
# that's missing what they just did. That was previously only wired up for
# the approval routes (cache_bump calls sprinkled at 5 call sites), which
# left every other mutation route silently stale for up to 2s -- e.g. a
# founder's own message appearing, then vanishing when a stale-cached poll
# response replaced local state, then reappearing once the cache expired.
# Hooking company_os.on_mutation() instead of a per-route cache_bump call
# means this can't be forgotten again by a route added later.
on_mutation(lambda company_id: cache_bump(_read_company_os_state, company_id))


@router.get("/companies/{company_id}/os")
async def get_company_os_route(company_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    return await asyncio.to_thread(_read_company_os_state, company_id)


@router.patch("/companies/{company_id}/os/initiatives/{initiative_id}")
async def edit_company_os_initiative(company_id: str, initiative_id: str, body: InitiativeEditBody, request: Request):
    company = _company(request, company_id, body.founder_id, operator=True)
    if not any(item.get("initiative_id") == initiative_id for item in company.get("initiatives", [])):
        raise HTTPException(status_code=404, detail="Initiative not found")
    changes = body.model_dump(exclude={"founder_id"}, exclude_none=True)
    state_aliases = {"active": "working", "waiting": "review", "blocked": "review", "complete": "done"}
    if "state" in changes:
        changes["state"] = state_aliases.get(str(changes["state"]).lower(), str(changes["state"]).lower())
        if changes["state"] not in {"planned", "working", "review", "done", "archived"}:
            raise HTTPException(status_code=422, detail="Invalid initiative state")
        if changes["state"] == "done":
            changes.setdefault("acceptance_confirmed", True)
    update_initiative(company_id, initiative_id, **changes)
    return {"ok": True, "initiative_id": initiative_id, "company": reconcile_initiatives(company_id)}


@router.delete("/companies/{company_id}/os/initiatives/{initiative_id}")
async def delete_company_os_initiative(company_id: str, initiative_id: str, founder_id: str, request: Request):
    """Soft-delete (archive) an initiative -- matches every other entity in this
    event-sourced store: nothing is physically removed from history, it's just
    excluded from what the dashboard shows going forward."""
    company = _company(request, company_id, founder_id, operator=True)
    if not any(item.get("initiative_id") == initiative_id for item in company.get("initiatives", [])):
        raise HTTPException(status_code=404, detail="Initiative not found")
    update_initiative(company_id, initiative_id, state="archived")
    return {"ok": True, "initiative_id": initiative_id, "company": get_company_os(company_id)}


@router.delete("/companies/{company_id}/os/squads/{squad_id}")
async def delete_company_os_squad(company_id: str, squad_id: str, founder_id: str, request: Request):
    """Soft-delete (archive) a squad, same pattern as initiatives/artifacts."""
    company = _company(request, company_id, founder_id, operator=True)
    if not any(item.get("squad_id") == squad_id for item in company.get("squads", [])):
        raise HTTPException(status_code=404, detail="Squad not found")
    update_squad(company_id, squad_id, state="archived", lifecycle="archived")
    return {"ok": True, "squad_id": squad_id, "company": get_company_os(company_id)}


@router.get("/companies/{company_id}/os/squads/{squad_id}/workbench")
async def get_company_os_squad_workbench(company_id: str, squad_id: str, founder_id: str, request: Request):
    """Return the durable squad collaboration projection without chat noise."""
    company = _company(request, company_id, founder_id)
    squad = next((item for item in company.get("squads", []) if item.get("squad_id") == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail="Squad not found")
    missions = [item for item in company.get("missions", []) if item.get("squad_id") == squad_id]
    return {
        "squad": squad,
        "roles": [item for item in company.get("squad_roles", []) if item.get("squad_id") == squad_id],
        "meetings": [item for item in company.get("squad_meetings", []) if item.get("squad_id") == squad_id],
        "tasks": [item for item in company.get("tasks", []) if item.get("squad_id") == squad_id],
        "missions": missions,
    }


@router.post("/companies/{company_id}/os/squads/{squad_id}/control")
async def control_company_os_squad(company_id: str, squad_id: str, body: SquadControlBody, request: Request):
    """Pause, resume, or cancel a squad through durable lifecycle state."""
    from backend.company_os_runner import launch_mission

    company = _company(request, company_id, body.founder_id, operator=True)
    squad = next((item for item in company.get("squads", []) if item.get("squad_id") == squad_id), None)
    if not squad:
        raise HTTPException(status_code=404, detail="Squad not found")
    tasks = [item for item in company.get("tasks", []) if item.get("squad_id") == squad_id]
    if body.action == "pause":
        update_squad(company_id, squad_id, state="paused", lifecycle="review")
        for task in tasks:
            if task.get("state") in {"pending", "ready", "planned", "scheduled"}:
                update_task(company_id, task["task_id"], state="waiting", blocked_reason="Paused by founder")
    elif body.action == "cancel":
        update_squad(company_id, squad_id, state="archived", lifecycle="archived")
        for task in tasks:
            if task.get("state") not in {"done", "blocked", "awaiting_approval"}:
                update_task(company_id, task["task_id"], state="blocked", blocked_reason="Cancelled by founder")
    else:
        update_squad(company_id, squad_id, state="active", lifecycle="working")
        missions = [item for item in company.get("missions", []) if item.get("squad_id") == squad_id]
        for task in tasks:
            if task.get("state") == "waiting" and task.get("blocked_reason") == "Paused by founder":
                update_task(company_id, task["task_id"], state="pending", blocked_reason=None)
        for mission in missions:
            launch_mission(company_id, str(mission["mission_id"]))
    return {"ok": True, "action": body.action, "company": reconcile_initiatives(company_id)}


@router.delete("/companies/{company_id}/os/artifacts/{artifact_id}")
async def delete_company_os_artifact_route(company_id: str, artifact_id: str, founder_id: str, request: Request):
    """Soft-delete (archive) an artifact, same pattern as initiatives, and cascade
    the delete into the Library -- artifacts created via create_artifact() get
    auto-mirrored into a Library file (_mirror_artifact_to_library), and
    delete_file() already cascades into Company Brain, so this one call cleans
    up all three layers instead of leaving an orphaned Library file behind."""
    company = _company(request, company_id, founder_id, operator=True)
    artifact = _artifact(company_id, artifact_id)
    library_file_id = artifact.get("library_file_id")
    if library_file_id:
        try:
            from backend.library.store import delete_file
            delete_file(str(company["founder_id"]), str(library_file_id))
        except Exception:
            logger.warning("Artifact delete: Library cascade failed company=%s artifact=%s file=%s", company_id, artifact_id, library_file_id, exc_info=True)
    update_artifact(company_id, artifact_id, state="archived")
    return {"ok": True, "artifact_id": artifact_id, "company": get_company_os(company_id)}


@router.get("/companies/{company_id}/os/artifacts/{artifact_id}")
async def get_company_os_artifact(company_id: str, artifact_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    return _artifact(company_id, artifact_id)


@router.get("/companies/{company_id}/os/artifacts/{artifact_id}/download")
async def download_company_os_artifact(company_id: str, artifact_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    artifact = _artifact(company_id, artifact_id)
    safe_name = "".join(char if char.isalnum() or char in " -_." else "_" for char in str(artifact.get("name") or "artifact"))
    return PlainTextResponse(str(artifact.get("content") or ""), headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'})


def _attachment_context(attachments: list[CopilotAttachmentBody]) -> str:
    """Fold attached file content into what the copilot reasons over, without
    polluting the founder's own visible chat bubble with a raw file dump."""
    valid = [item for item in attachments if item.content.strip()]
    if not valid:
        return ""
    parts = [f"--- Attached file: {item.name} ---\n{item.content}" for item in valid]
    return "\n\nAttached files for context:\n" + "\n\n".join(parts)


@router.post("/companies/{company_id}/os/copilot")
async def copilot_message_route(company_id: str, body: CopilotMessageBody, request: Request):
    company = _company(request, company_id, body.founder_id, operator=True)
    _maybe_auto_title_thread(company_id, company, body.thread_id, body.message)
    append_message(company_id, body.message, author="founder", role="user", thread_id=body.thread_id)
    augmented_message = body.message + _attachment_context(body.attachments)
    result = await coordinate_turn(company_id, augmented_message, thread_id=body.thread_id, proposed_spend=body.proposed_spend)
    return {"message": result["message"], "dispatch": result["dispatch"], "company": get_company_os(company_id)}


def _maybe_auto_title_thread(company_id: str, company: dict[str, Any], thread_id: str, message: str) -> None:
    """First message in a still-default-titled thread renames it -- cheap
    (~40 chars of the founder's own text, no LLM call) parity with ChatGPT/
    Claude's auto-title, without new infra. Never overwrites a manual rename."""
    thread = next((item for item in company.get("chat_threads", []) if item.get("thread_id") == thread_id), None)
    if not thread or thread.get("title") not in ("New chat", "General"):
        return
    has_prior_message = any(item.get("thread_id") == thread_id for item in company.get("conversation", []))
    if has_prior_message:
        return
    snippet = message.strip().replace("\n", " ")[:40]
    if snippet:
        update_thread(company_id, thread_id, title=snippet)


@router.patch("/companies/{company_id}/os/messages/{message_id}")
async def edit_company_os_message(company_id: str, message_id: str, body: MessageEditBody, request: Request):
    """Edit a founder's own chat message. Copilot replies aren't editable --
    they're the durable record of what Astra actually said and did.

    Everything after the edited message is now stale (it was a reply to text
    that no longer exists) -- archive it, same soft-delete convention as a
    single deleted message, then resubmit the edited text through the normal
    copilot turn so a fresh reply actually gets generated instead of leaving
    the edit sitting there with the old (now-mismatched) conversation below
    it."""
    company = _company(request, company_id, body.founder_id, operator=True)
    message = _message(company_id, message_id)
    if message.get("author") != "founder":
        raise HTTPException(status_code=400, detail="Only your own messages can be edited")
    thread_id = message.get("thread_id", "default")
    conversation = company.get("conversation", [])
    edited_index = next(i for i, item in enumerate(conversation) if item.get("message_id") == message_id)
    # Only archive later messages in the SAME thread -- "everything after" is
    # positional within the whole conversation list, but threads interleave
    # in that list, so an unscoped archive would wrongly wipe other threads'
    # later messages too.
    for later in conversation[edited_index + 1:]:
        if later.get("thread_id", "default") == thread_id:
            update_message(company_id, later["message_id"], archived=True)
    _dismiss_pending_approvals(company_id, company, reason="Dismissed because the originating chat message was edited")
    update_message(company_id, message_id, message=body.message, edited=True)
    result = await coordinate_turn(company_id, body.message, thread_id=thread_id)
    return {"ok": True, "message_id": message_id, "message": result["message"], "dispatch": result["dispatch"], "company": get_company_os(company_id)}


@router.delete("/companies/{company_id}/os/messages/{message_id}")
async def delete_company_os_message(company_id: str, message_id: str, founder_id: str, request: Request):
    """Soft-delete (archive) a single message, same pattern as every other entity."""
    company = _company(request, company_id, founder_id, operator=True)
    if not any(item.get("message_id") == message_id for item in company.get("conversation", [])):
        raise HTTPException(status_code=404, detail="Message not found")
    update_message(company_id, message_id, archived=True)
    return {"ok": True, "message_id": message_id, "company": get_company_os(company_id)}


@router.post("/companies/{company_id}/os/messages/clear")
async def clear_company_os_messages(company_id: str, founder_id: str, request: Request):
    """Archive the whole conversation thread. History still replays -- this
    only changes what the dashboard shows going forward, same as every other
    soft-delete in this store."""
    company = _company(request, company_id, founder_id, operator=True)
    for item in company.get("conversation", []):
        if not item.get("archived"):
            update_message(company_id, item["message_id"], archived=True)
    _dismiss_pending_approvals(company_id, company, reason="Dismissed because the chat was cleared")
    return {"ok": True, "company": get_company_os(company_id)}


@router.post("/companies/{company_id}/os/chats")
async def create_chat_thread_route(company_id: str, body: ChatThreadCreateBody, request: Request):
    company = _company(request, company_id, body.founder_id, operator=True)
    thread = create_thread(company_id, body.title)
    # Append in place instead of a fresh get_company_os() -- _company()
    # already paid for one read this request (plus its own internal
    # ensure_company_operations/ensure_default_chat_thread reads); chat_threads
    # isn't derived from anything else the way reconcile_initiatives'
    # initiative rollups are, so appending the just-created record is exactly
    # what a re-read would show.
    company["chat_threads"] = company.get("chat_threads", []) + [thread]
    return {"ok": True, "thread_id": thread["thread_id"], "company": company}


@router.patch("/companies/{company_id}/os/chats/{thread_id}")
async def rename_chat_thread_route(company_id: str, thread_id: str, body: ChatThreadRenameBody, request: Request):
    company = _company(request, company_id, body.founder_id, operator=True)
    if not any(item.get("thread_id") == thread_id for item in company.get("chat_threads", [])):
        raise HTTPException(status_code=404, detail="Chat not found")
    updated = update_thread(company_id, thread_id, title=body.title)
    for item in company["chat_threads"]:
        if item.get("thread_id") == thread_id:
            item.update(updated)
    return {"ok": True, "thread_id": thread_id, "company": company}


@router.delete("/companies/{company_id}/os/chats/{thread_id}")
async def delete_chat_thread_route(company_id: str, thread_id: str, founder_id: str, request: Request):
    """Soft-delete a chat thread, same convention as initiatives/squads --
    messages stay intact in the durable log, the thread just stops listing."""
    company = _company(request, company_id, founder_id, operator=True)
    if not any(item.get("thread_id") == thread_id for item in company.get("chat_threads", [])):
        raise HTTPException(status_code=404, detail="Chat not found")
    if thread_id == "default":
        raise HTTPException(status_code=400, detail="The default chat can't be deleted")
    updated = update_thread(company_id, thread_id, archived=True)
    for item in company["chat_threads"]:
        if item.get("thread_id") == thread_id:
            item.update(updated)
    return {"ok": True, "thread_id": thread_id, "company": company}


@router.post("/companies/{company_id}/os/operations/tick")
async def operations_tick_route(company_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id, operator=True)
    # The scheduler can only execute policy-approved internal tasks. This executor
    # deliberately produces a local audit artifact rather than performing I/O.
    results = scheduler_tick(company_id, lambda task: {"kind": "local_internal_update", "task": task.get("name")})
    return {"results": results, "company": get_company_os(company_id)}


@router.post("/companies/{company_id}/os/tasks/{task_id}/retry")
async def retry_company_os_task(company_id: str, task_id: str, founder_id: str, request: Request):
    """Give a blocked task another shot: execute_task() permanently blocks a task
    after two failed attempts (e.g. a research call that couldn't clear the
    source-quality gate) with no automatic recovery -- this is the founder's
    manual retry. Resets it to pending and relaunches its mission, same as an
    approval decision does."""
    from backend.company_os_runner import launch_mission
    company = _company(request, company_id, founder_id, operator=True)
    task = next((item for item in company.get("tasks", []) if item.get("task_id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("state") != "blocked":
        raise HTTPException(status_code=409, detail="Task is not blocked")
    update_task(company_id, task_id, state="pending", blocked_reason=None)
    mission_id = task.get("mission_id")
    if mission_id:
        launch_mission(company_id, str(mission_id))
    return {"ok": True, "task_id": task_id, "company": reconcile_initiatives(company_id)}


# ── Async Company OS approval flow ─────────────────────────────────
# Why: a founder "Approve" click used to block on the SAME request while the
# backend composed five sequential writes (approval ledger → task → mission
# → launch_mission → reconcile_initiatives). On a large tenant each of those
# scans a JSONL event log; the total request routinely took 2-4s, and any
# one slowing down stalled the entire dashboard refresh cycle.
#
# What this does now:
#   1. The approval endpoint writes the durable decision FIRST
#      (single small file write; always succeeds if auth/payload checks pass).
#   2. Returns 202 Accepted immediately with the persisted decision + the
#      approval_id, so the UI can mark the card "Approved" synchronously.
#   3. Spawns asyncio.create_task(...) to apply the heavier side-effects
#      (update_task, update_mission, launch_mission, reconcile_initiatives)
#      in the background.
#   4. Exposes GET /companies/{c}/os/approvals/{a}/status for the FE to
#      learn whether side-effects have flushed. The FE polls it briefly
#      (≤3s) immediately after submit, then stops -- no recurring load.
#   5. On startup, the worker runs ``resync_pending_async_approvals`` to
#      pick up decisions ACK'd by a previous web process whose side-effects
#      never landed (process restart, crash, etc.). Idempotent.
#
# Idempotency contract: every side-effect is keyed by its target's identity
# (task_id / mission_id) and inspects current state before mutating, so a
# retry of any one of them produces the same final state. A double-apply
# is safe.
#
# Crash window: between ACK and side-effects, the durable approval ledger
# holds the decision while task/mission state has NOT yet been updated.
# The startup resync closes that window on next boot. Within a single
# process, asyncio.create_task fires before the response is sent, and the
# coroutine runs on the same loop, so an in-process crash mid-task is the
# only path where side-effects don't land -- covered by resync.

_ASYNC_APPROVAL_SIDE_EFFECT_TIMEOUT_SECONDS = float(
    os.environ.get("ASTRA_ASYNC_APPROVAL_SIDE_EFFECT_TIMEOUT", "60")
)


def _apply_approval_side_effects(
    company_id: str,
    approval_id: str,
    *,
    approved: bool,
    note: str | None,
) -> None:
    """Apply task/mission/launch updates after the durable decision is already
    persisted. Idempotent: every branch inspects current state first."""
    try:
        from backend.company_os_runner import launch_mission

        company = get_company_os(company_id) or {}
        approval = next((item for item in company.get("approvals", []) if item.get("approval_id") == approval_id), None)
        if not approval:
            logger.warning("async approval: approval %s vanished before side-effects", approval_id)
            cache_bump(_read_company_os_state, company_id)
            return
        # If the decision file says approved/rejected but append_event below
        # didn't fire -- e.g. worker process restart -- we treat side-effects
        # as already-applied and re-fire only what's still pending.
        task_id = approval.get("task_id")
        task = next((item for item in company.get("tasks", []) if item.get("task_id") == task_id), None) if task_id else None
        target_state = "pending" if approved else "blocked"
        approval_decision = "approved" if approved else "rejected"
        if task and task.get("state") != target_state:
            update_task(
                company_id, task_id,
                state=target_state,
                approval_decision=approval_decision,
                approval_note=note or "",
            )
        if approved and task:
            mission_id = task.get("mission_id")
            if mission_id:
                mission = next((m for m in company.get("missions", []) if m.get("mission_id") == mission_id), None)
                if mission and mission.get("state") != "active":
                    update_mission(company_id, str(mission_id), state="active", blocked_reason=None)
                launch_mission(company_id, str(mission_id))
        # Force a fresh read on the next dashboard poll regardless of side-effect
        # outcome -- if launch_mission raises, the next reconcile will surface
        # that, and we don't want a stale 2-3s TTL hiding it.
        cache_bump(_read_company_os_state, company_id)
    except Exception:
        logger.exception("async approval: side-effects failed company=%s approval=%s", company_id, approval_id)
        cache_bump(_read_company_os_state, company_id)
        # Don't re-raise -- we're a fire-and-forget task; the startup resync
        # will retry on next boot if any branch above partially applied.


def resync_pending_async_approvals() -> int:
    """Walk every Company OS durable ledger, find approvals whose task has
    not yet moved (state == awaiting_approval but approval.state in {
    approved, rejected}), and apply their side-effects. Idempotent.

    Called once at startup (only in worker role) so a process that accepted
    an approval but crashed before asyncio.create_task finished -- or before
    the background side-effects ran at all -- picks up where it left off.

    Returns the number of side-effects applied. Zero on a clean restart."""
    from backend.company_os_runner import launch_mission

    base_root = Path(os.environ.get("ASTRA_WORKSPACE", "/data/astra-workspaces")) / "company"
    if not base_root.exists():
        return 0
    applied = 0
    try:
        for company_dir in base_root.iterdir():
            if not company_dir.is_dir():
                continue
            company_id = company_dir.name
            try:
                company = get_company_os(company_id) or {}
            except Exception:
                continue
            for approval in company.get("approvals", []) or []:
                state = approval.get("state")
                if state not in {"approved", "rejected"}:
                    continue
                task_id = approval.get("task_id")
                if not task_id:
                    continue
                task = next((t for t in company.get("tasks", []) if str(t.get("task_id")) == str(task_id)), None)
                if not task:
                    continue
                needs_apply = False
                if state == "approved" and task.get("state") not in {"pending", "in_progress"}:
                    needs_apply = True
                if state == "rejected" and task.get("state") != "blocked":
                    needs_apply = True
                if not needs_apply:
                    continue
                try:
                    if state == "approved":
                        update_task(company_id, task_id, state="pending", approval_decision="approved", approval_note=approval.get("note", ""))
                        mission_id = task.get("mission_id")
                        if mission_id:
                            mission = next((m for m in company.get("missions", []) if str(m.get("mission_id")) == str(mission_id)), None)
                            if mission and mission.get("state") != "active":
                                update_mission(company_id, str(mission_id), state="active", blocked_reason=None)
                            launch_mission(company_id, str(mission_id))
                    else:
                        update_task(company_id, task_id, state="blocked", approval_decision="rejected", approval_note=approval.get("note", ""))
                    applied += 1
                except Exception:
                    logger.exception("resync: failed company=%s approval=%s", company_id, approval.get("approval_id"))
            cache_bump(_read_company_os_state, company_id)
    except Exception:
        logger.exception("resync_pending_async_approvals: outer failure")
    return applied


class ApprovalStatusResponse(BaseModel):
    """Compact summary of the post-ACK side-effect state. Used by the FE
    to confirm the click landed (so it can refresh panels) and by tests."""

    approval_id: str
    state: str
    task_state: str | None = None
    mission_state: str | None = None
    applied: bool
    error: str | None = None
    decided_at: str | None = None
    completed_at: str | None = None


@router.post("/companies/{company_id}/os/approvals/{approval_id}")
async def decide_company_os_approval(company_id: str, approval_id: str, body: ApprovalDecisionBody, request: Request):
    """Persist the founder's approval decision and ACK immediately.

    The endpoint does the durable write (always small + atomic) then
    returns 202 with a status handle. Side-effects ``_apply_approval_side_effects``
    are scheduled as a background task, with their completion observable
    via ``GET /companies/{c}/os/approvals/{a}/status`` and reconciled by
    ``resync_pending_async_approvals`` on next worker startup."""
    company = _company(request, company_id, body.founder_id, operator=True)
    approval = next((item for item in company.get("approvals", []) if item.get("approval_id") == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.get("state") != "pending":
        # Idempotent re-submit: same approval already decided → still return
        # its current status so the FE doesn't see a confusing 409 every
        # time the click is double-fired.
        status = _approval_status_payload(company_id, approval_id)
        return JSONResponse(
            status_code=200,
            content={"ok": True, "approval_id": approval_id, "approved": approval.get("state") == "approved", "idempotent": True, "status": status},
        )
    decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_state = "approved" if body.approved else "rejected"
    update_approval(company_id, approval_id, state=new_state, note=body.note, decided_at=decided_at)
    # Invalidate cached GET /companies/{c}/os so the dashboard reflects the
    # decision right away.
    cache_bump(_read_company_os_state, company_id)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            asyncio.wait_for(
                asyncio.to_thread(_apply_approval_side_effects, company_id, approval_id, approved=body.approved, note=body.note),
                timeout=_ASYNC_APPROVAL_SIDE_EFFECT_TIMEOUT_SECONDS,
            )
        )
    except RuntimeError:
        # Fallback path: somehow called outside a running loop (only possible
        # in tests/scripting). Run synchronously instead of dropping the work.
        _apply_approval_side_effects(company_id, approval_id, approved=body.approved, note=body.note)
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "approval_id": approval_id,
            "approved": body.approved,
            "state": new_state,
            "decided_at": decided_at,
            "applied": False,
            "status_url": f"/companies/{company_id}/os/approvals/{approval_id}/status",
            "company": _read_company_os_state(company_id),
        },
    )


def _approval_status_payload(company_id: str, approval_id: str) -> ApprovalStatusResponse:
    company = get_company_os(company_id) or {}
    approval = next((item for item in company.get("approvals", []) if item.get("approval_id") == approval_id), None)
    if not approval:
        return ApprovalStatusResponse(approval_id=approval_id, state="missing", applied=False, error="approval not found")
    state = approval.get("state", "pending")
    task = None
    mission = None
    task_id = approval.get("task_id")
    if task_id:
        task = next((t for t in company.get("tasks", []) if str(t.get("task_id")) == str(task_id)), None)
        if task and task.get("mission_id"):
            mission = next((m for m in company.get("missions", []) if str(m.get("mission_id")) == str(task.get("mission_id"))), None)
    applied = True
    if state == "approved":
        # Applied = task is in pending/in_progress AND (no mission OR mission active).
        if task and task.get("state") not in {"pending", "in_progress", "done"}:
            applied = False
        if mission and mission.get("state") not in {"active", "done"}:
            applied = False
    elif state == "rejected":
        applied = bool(task and task.get("state") == "blocked")
    return ApprovalStatusResponse(
        approval_id=approval_id,
        state=state,
        task_state=(task or {}).get("state"),
        mission_state=(mission or {}).get("state"),
        applied=applied,
        decided_at=approval.get("decided_at") or approval.get("updated_at"),
        completed_at=approval.get("decided_at") or approval.get("updated_at") if applied else None,
    )


@router.get("/companies/{company_id}/os/approvals/{approval_id}/status")
async def approval_status_route(company_id: str, approval_id: str, founder_id: str, request: Request):
    """Inspect whether a previously-ACK'd asynchronous approval decision has
    had its side-effects applied. Returns ``applied: true/false`` so the FE
    knows when to stop polling and refresh panels."""
    _company(request, company_id, founder_id)
    payload = await asyncio.to_thread(_approval_status_payload, company_id, approval_id)
    return {"ok": True, **payload.model_dump()}

"""Company OS API: the permanent Copilot thread and its durable work graph."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, model_validator

from backend.company_os import append_message, create_company_os, ensure_company_operations, get_company_os, reconcile_initiatives, update_artifact, update_approval, update_initiative, update_message, update_squad, update_task
from backend.company_os_copilot import coordinate_turn
from backend.company_os_dispatch import scheduler_tick
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
    proposed_spend: float = Field(default=0, ge=0)
    attachments: list[CopilotAttachmentBody] = Field(default_factory=list)


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


def _company(request: Request, company_id: str, founder_id: str, *, operator: bool = False) -> dict[str, Any]:
    """Authorize access, then lazily create the local Company OS for a new company."""
    require_founder_access(request, founder_id, min_role="operator" if operator else "viewer")
    company = get_company_os(company_id)
    if company:
        if company["founder_id"] != founder_id:
            raise HTTPException(status_code=404, detail="Company not found")
        ensure_company_operations(company_id)
        return company
    created = create_company_os(company_id, founder_id, "Company")
    ensure_company_operations(company_id)
    return created


@router.post("/company-os")
async def create_company_os_route(body: CompanyOSCreateBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")
    company_id = body.company_id or body.founder_id
    company = create_company_os(company_id, body.founder_id, body.name)
    ensure_company_operations(company_id)
    return get_company_os(company_id) or company


@router.get("/companies/{company_id}/os")
async def get_company_os_route(company_id: str, founder_id: str, request: Request):
    _company(request, company_id, founder_id)
    reconcile_initiatives(company_id)
    return get_company_os(company_id)


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
    reconcile_initiatives(company_id)
    return {"ok": True, "initiative_id": initiative_id, "company": get_company_os(company_id)}


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
    reconcile_initiatives(company_id)
    return {"ok": True, "action": body.action, "company": get_company_os(company_id)}


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
    _company(request, company_id, body.founder_id, operator=True)
    append_message(company_id, body.message, author="founder", role="user")
    augmented_message = body.message + _attachment_context(body.attachments)
    result = await coordinate_turn(company_id, augmented_message, proposed_spend=body.proposed_spend)
    return {"message": result["message"], "dispatch": result["dispatch"], "company": get_company_os(company_id)}


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
    conversation = company.get("conversation", [])
    edited_index = next(i for i, item in enumerate(conversation) if item.get("message_id") == message_id)
    for later in conversation[edited_index + 1:]:
        update_message(company_id, later["message_id"], archived=True)
    _dismiss_pending_approvals(company_id, company, reason="Dismissed because the originating chat message was edited")
    update_message(company_id, message_id, message=body.message, edited=True)
    result = await coordinate_turn(company_id, body.message)
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
    reconcile_initiatives(company_id)
    return {"ok": True, "task_id": task_id, "company": get_company_os(company_id)}


@router.post("/companies/{company_id}/os/approvals/{approval_id}")
async def decide_company_os_approval(company_id: str, approval_id: str, body: ApprovalDecisionBody, request: Request):
    from backend.company_os_runner import launch_mission
    company = _company(request, company_id, body.founder_id, operator=True)
    approval = next((item for item in company.get("approvals", []) if item.get("approval_id") == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.get("state") != "pending":
        raise HTTPException(status_code=409, detail="Approval is no longer pending")
    task_id = approval.get("task_id")
    task = next((item for item in company.get("tasks", []) if item.get("task_id") == task_id), None)
    update_approval(company_id, approval_id, state="approved" if body.approved else "rejected", note=body.note)
    if task:
        update_task(company_id, task_id, state="pending" if body.approved else "blocked", approval_decision="approved" if body.approved else "rejected", approval_note=body.note)
        if body.approved and task.get("mission_id"):
            launch_mission(company_id, str(task["mission_id"]))
    reconcile_initiatives(company_id)
    return {"ok": True, "approval_id": approval_id, "approved": body.approved, "company": get_company_os(company_id)}

"""Wave 4.3 durable external action executor.

Provides one side-effect boundary that persists action intent before execution,
enforces exact approval consumption when required, re-checks cancellation
immediately before the effect, and stores provider receipts for idempotent
replay/collision detection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from backend.control_plane.models import Action, ActionReceipt
from backend.control_plane.repositories import (
    ActionReceiptRepository,
    ActionRepository,
    ApprovalRequestRepository,
)
from backend.observability.tracing import action_span

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlPlaneRepoBundle:
    action_repo: ActionRepository
    receipt_repo: ActionReceiptRepository
    approval_repo: ApprovalRequestRepository


_default_repo_bundle: Optional[ControlPlaneRepoBundle] = None
_default_repo_bundle_lock = threading.Lock()


class ActionExecutionError(RuntimeError):
    pass


class ApprovalRequiredError(ActionExecutionError):
    pass


class CancellationFenceError(ActionExecutionError):
    pass


class ReceiptCollisionError(ActionExecutionError):
    pass


def get_default_repo_bundle() -> ControlPlaneRepoBundle:
    global _default_repo_bundle
    if _default_repo_bundle is None:
        with _default_repo_bundle_lock:
            if _default_repo_bundle is None:
                from backend.config import settings

                if settings.supabase_url and settings.supabase_key:
                    from backend.control_plane.supabase_repositories import (
                        SupabaseActionReceiptRepository,
                        SupabaseActionRepository,
                        SupabaseApprovalRequestRepository,
                    )

                    _default_repo_bundle = ControlPlaneRepoBundle(
                        action_repo=SupabaseActionRepository(),
                        receipt_repo=SupabaseActionReceiptRepository(),
                        approval_repo=SupabaseApprovalRequestRepository(),
                    )
                else:
                    from backend.control_plane.fakes import (
                        FakeActionReceiptRepository,
                        FakeActionRepository,
                        FakeApprovalRequestRepository,
                    )

                    _default_repo_bundle = ControlPlaneRepoBundle(
                        action_repo=FakeActionRepository(),
                        receipt_repo=FakeActionReceiptRepository(),
                        approval_repo=FakeApprovalRequestRepository(),
                    )
    return _default_repo_bundle


def canonicalize_tool_args(args: dict[str, Any]) -> str:
    return json.dumps(args or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_action_hashes(
    *,
    run_id: str,
    step_id: str,
    action_id: str,
    tool: str,
    args: dict[str, Any],
    policy_version: str,
) -> tuple[str, str]:
    canonical_args = canonicalize_tool_args(args)
    canonical_args_hash = hashlib.sha256(canonical_args.encode("utf-8")).hexdigest()
    normalized_tool = str(tool or "").strip().lower()
    idem_source = "::".join([
        run_id,
        step_id,
        action_id,
        normalized_tool,
        canonical_args,
        policy_version,
    ])
    idempotency_key = hashlib.sha256(idem_source.encode("utf-8")).hexdigest()
    return canonical_args_hash, idempotency_key


@dataclass(frozen=True)
class ExternalActionRequest:
    run_id: str
    step_id: str
    tool: str
    args: dict[str, Any]
    risk_level: str = "low"
    policy_version: str = "v1"
    approval_id: Optional[str] = None
    approval_action_digest: Optional[str] = None
    require_approval: bool = False
    action_id: Optional[str] = None
    org_id: Optional[str] = None


@dataclass(frozen=True)
class ExternalActionResult:
    action: Action
    receipt: ActionReceipt
    provider_result: dict[str, Any]
    replayed: bool = False


async def execute_external_action(
    request: ExternalActionRequest,
    *,
    action_repo: ActionRepository,
    receipt_repo: ActionReceiptRepository,
    approval_repo: Optional[ApprovalRequestRepository],
    execute_effect: Callable[[dict[str, Any], str], Awaitable[dict[str, Any]]],
    is_cancelled: Callable[[str], bool] = lambda _run_id: False,
) -> ExternalActionResult:
    action_id = request.action_id or str(uuid.uuid4())
    with action_span(
        request.run_id, action_id, request.tool, request.approval_id, org_id=(request.org_id or ""),
    ) as _action_span:
        canonical_args_hash, idempotency_key = compute_action_hashes(
            run_id=request.run_id,
            step_id=request.step_id,
            action_id=action_id,
            tool=request.tool,
            args=request.args,
            policy_version=request.policy_version,
        )

        existing_action = action_repo.get_by_idempotency_key(idempotency_key)
        if existing_action is not None:
            existing_receipt = receipt_repo.get_by_idempotency_key(idempotency_key)
            if existing_receipt is not None:
                _action_span.set_attribute("action.receipt", existing_receipt.id)
                return ExternalActionResult(
                    action=existing_action,
                    receipt=existing_receipt,
                    provider_result=dict(existing_receipt.provider_result or {}),
                    replayed=True,
                )
            action = existing_action
        else:
            action = action_repo.create(Action(
                id=action_id,
                run_id=request.run_id,
                step_id=request.step_id,
                tool=request.tool,
                canonical_args_hash=canonical_args_hash,
                risk_level=request.risk_level,
                approval_id=request.approval_id,
                idempotency_key=idempotency_key,
                status="approved" if request.require_approval else "pending",
            ))

        if is_cancelled(request.run_id):
            action_repo.update_status(action.id, "blocked")
            raise CancellationFenceError(f"run {request.run_id!r} was cancelled before external effect execution")

        if request.require_approval:
            if not request.approval_id or not request.approval_action_digest:
                raise ApprovalRequiredError("approval_id and approval_action_digest are required when approval is required")
            if approval_repo is None:
                raise ApprovalRequiredError("approval repository is required when approval is required")
            consumed = approval_repo.consume(
                request.approval_id,
                expected_action_digest=request.approval_action_digest,
                expected_policy_version=request.policy_version,
            )
            action_repo.update_status(action.id, "approved")
            action = action.model_copy(update={"status": "approved", "approval_id": consumed.id})

        # Recheck immediately before the effect, not just before approval consumption --
        # approval_repo.consume() above is a real round trip and can take enough wall
        # time for a cancel signal to land in between. Spec requires the recheck happen
        # right before the side effect itself, not merely somewhere earlier in the call.
        if is_cancelled(request.run_id):
            action_repo.update_status(action.id, "blocked")
            raise CancellationFenceError(f"run {request.run_id!r} was cancelled before external effect execution")

        action_repo.update_status(action.id, "executing")
        try:
            provider_result = await execute_effect(dict(request.args or {}), idempotency_key)
        except Exception:
            action_repo.update_status(action.id, "failed")
            raise

        receipt = ActionReceipt(
            id=str(uuid.uuid4()),
            action_id=action.id,
            idempotency_key=idempotency_key,
            provider_result=dict(provider_result or {}),
        )
        existing_receipt = receipt_repo.get_by_idempotency_key(idempotency_key)
        if existing_receipt is not None and existing_receipt.action_id != action.id:
            receipt_repo.update_collision_status(existing_receipt.id, "detected")
            try:
                from backend.control_plane.anomalies import record_anomaly

                record_anomaly(
                    "receipt_collision",
                    run_id=request.run_id,
                    step_id=request.step_id,
                    payload={
                        "action_id": action.id,
                        "existing_action_id": existing_receipt.action_id,
                        "idempotency_key": idempotency_key,
                        "tool": request.tool,
                    },
                )
            except Exception:
                pass
            raise ReceiptCollisionError(
                f"idempotency receipt collision for key {idempotency_key}: "
                f"{existing_receipt.action_id!r} != {action.id!r}"
            )
        if existing_receipt is None:
            receipt_repo.create(receipt)
        else:
            receipt = existing_receipt

        action_repo.update_status(action.id, "succeeded")
        action = action.model_copy(update={"status": "succeeded", "receipt": dict(receipt.provider_result or {})})
        logger.info("external action succeeded run=%s step=%s tool=%s action_id=%s", request.run_id, request.step_id, request.tool, action.id)
        _action_span.set_attribute("action.receipt", receipt.id)
        return ExternalActionResult(
            action=action,
            receipt=receipt,
            provider_result=dict(receipt.provider_result or {}),
            replayed=False,
        )

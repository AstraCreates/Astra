"""Real Supabase-backed implementations of the Wave 1 repository interfaces.

These are additive dual-writes alongside the legacy session store and credits
ledger. Every live call site must continue treating them as best-effort, but
the repository behavior itself should match the canonical Wave 1 contracts.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.control_plane.models import (
    Action,
    ApprovalRequest,
    Artifact,
    BudgetReservation,
    BudgetReservationLedger,
    Run,
    RunEvent,
    RunStep,
)

logger = logging.getLogger(__name__)


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def _row_to_run(row: dict[str, Any]) -> Run:
    return Run.model_validate(row)


def _row_to_step(row: dict[str, Any]) -> RunStep:
    return RunStep.model_validate(row)


def _row_to_action(row: dict[str, Any]) -> Action:
    return Action.model_validate(row)


def _row_to_approval(row: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest.model_validate(row)


def _row_to_event(row: dict[str, Any]) -> RunEvent:
    return RunEvent.model_validate(row)


def _row_to_artifact(row: dict[str, Any]) -> Artifact:
    return Artifact.model_validate(row)


def _row_to_reservation(row: dict[str, Any]) -> BudgetReservation:
    return BudgetReservation.model_validate(row)


def _row_to_reservation_ledger(row: dict[str, Any]) -> BudgetReservationLedger:
    return BudgetReservationLedger.model_validate(row)


class SupabaseRunRepository:
    def create(self, run: Run) -> Run:
        from backend.db.client import get_supabase

        get_supabase().table("astra_runs").upsert(_dump(run), on_conflict="id").execute()
        return run

    def get(self, run_id: str) -> Optional[Run]:
        from backend.db.client import get_supabase

        rows = get_supabase().table("astra_runs").select("*").eq("id", run_id).limit(1).execute().data
        return _row_to_run(rows[0]) if rows else None

    def update_status(self, run_id: str, status: str, *, error: Optional[str] = None) -> None:
        from backend.db.client import get_supabase

        patch: dict[str, Any] = {"status": status}
        if error is not None:
            patch["error"] = error
        get_supabase().table("astra_runs").update(patch).eq("id", run_id).execute()


class SupabaseRunStepRepository:
    def create_attempt(self, step: RunStep) -> RunStep:
        from backend.db.client import get_supabase

        existing = (
            get_supabase().table("astra_run_steps")
            .select("attempt_number")
            .eq("run_id", step.run_id)
            .eq("step_key", step.step_key)
            .order("attempt_number", desc=True)
            .limit(1)
            .execute()
            .data
        )
        next_attempt = (int(existing[0]["attempt_number"]) + 1) if existing else 1
        step = step.model_copy(update={"attempt_number": next_attempt})
        get_supabase().table("astra_run_steps").upsert(_dump(step), on_conflict="id").execute()
        return step

    def get_latest_attempt(self, run_id: str, step_key: str) -> Optional[RunStep]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_run_steps")
            .select("*")
            .eq("run_id", run_id)
            .eq("step_key", step_key)
            .order("attempt_number", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_step(rows[0]) if rows else None

    def list_attempts(self, run_id: str, step_key: str) -> list[RunStep]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_run_steps")
            .select("*")
            .eq("run_id", run_id)
            .eq("step_key", step_key)
            .order("attempt_number")
            .execute()
            .data
        )
        return [_row_to_step(row) for row in rows]

    def update_status(self, step_id: str, status: str, *, error: Optional[str] = None) -> None:
        from backend.db.client import get_supabase

        patch: dict[str, Any] = {"status": status}
        if error is not None:
            patch["error"] = error
        get_supabase().table("astra_run_steps").update(patch).eq("id", step_id).execute()


class SupabaseActionRepository:
    def create(self, action: Action) -> Action:
        from backend.db.client import get_supabase

        get_supabase().table("astra_actions").upsert(_dump(action), on_conflict="id").execute()
        return action

    def get(self, action_id: str) -> Optional[Action]:
        from backend.db.client import get_supabase

        rows = get_supabase().table("astra_actions").select("*").eq("id", action_id).limit(1).execute().data
        return _row_to_action(rows[0]) if rows else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Action]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_actions")
            .select("*")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_action(rows[0]) if rows else None

    def update_status(self, action_id: str, status: str) -> None:
        from backend.db.client import get_supabase

        get_supabase().table("astra_actions").update({"status": status}).eq("id", action_id).execute()


class SupabaseApprovalRequestRepository:
    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        from backend.db.client import get_supabase

        get_supabase().table("astra_approval_requests").upsert(_dump(request), on_conflict="id").execute()
        return request

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_approval_requests")
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_approval(rows[0]) if rows else None

    def get_pending_for_gate(self, run_id: str, gate_key: str) -> list[ApprovalRequest]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_approval_requests")
            .select("*")
            .eq("run_id", run_id)
            .eq("gate_key", gate_key)
            .eq("status", "pending")
            .order("revision", desc=True)
            .execute()
            .data
        )
        return [_row_to_approval(row) for row in rows]

    def decide(self, request_id: str, status: str, *, decided_by: str, note: Optional[str] = None) -> ApprovalRequest:
        from backend.db.client import get_supabase
        from datetime import datetime, timezone

        patch: dict[str, Any] = {
            "status": status,
            "decided_by": decided_by,
            "decision_note": note,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        get_supabase().table("astra_approval_requests").update(patch).eq("id", request_id).execute()
        updated = self.get(request_id)
        if updated is None:
            raise KeyError(f"unknown request_id {request_id!r}")
        return updated


class SupabaseRunEventRepository:
    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        from backend.db.client import get_supabase

        result = get_supabase().rpc(
            "astra_append_run_event",
            {"p_run_id": run_id, "p_event_type": event_type, "p_payload": payload},
        ).execute()
        return int(result.data)

    def list_since(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_run_events")
            .select("*")
            .eq("run_id", run_id)
            .gte("sequence", after_sequence)
            .order("sequence")
            .execute()
            .data
        )
        return [_row_to_event(row) for row in rows]


class SupabaseArtifactRepository:
    def upsert(self, artifact: Artifact) -> Artifact:
        from backend.db.client import get_supabase

        get_supabase().table("astra_artifacts").upsert(_dump(artifact), on_conflict="id").execute()
        return artifact

    def list_for_run(self, run_id: str) -> list[Artifact]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_artifacts")
            .select("*")
            .eq("run_id", run_id)
            .order("created_at")
            .execute()
            .data
        )
        return [_row_to_artifact(row) for row in rows]


class SupabaseBudgetReservationRepository:
    def reserve(
        self,
        reservation: BudgetReservation,
        *,
        founder_id: Optional[str] = None,
        reserved_credits: Optional[int] = None,
        markup: float = 10.0,
    ) -> BudgetReservation:
        from backend.db.client import get_supabase

        supabase = get_supabase()
        supabase.table("astra_budget_reservations").upsert(_dump(reservation), on_conflict="id").execute()
        if founder_id is not None:
            ledger = BudgetReservationLedger(
                reservation_id=reservation.id,
                founder_id=founder_id,
                reserved_credits=max(0, int(reserved_credits or 0)),
                markup=markup,
            )
            supabase.table("astra_budget_reservation_ledgers").upsert(_dump(ledger), on_conflict="reservation_id").execute()
        return reservation

    def get(self, reservation_id: str) -> Optional[BudgetReservation]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_budget_reservations")
            .select("*")
            .eq("id", reservation_id)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_reservation(rows[0]) if rows else None

    def get_ledger(self, reservation_id: str) -> Optional[BudgetReservationLedger]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_budget_reservation_ledgers")
            .select("*")
            .eq("reservation_id", reservation_id)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_reservation_ledger(rows[0]) if rows else None

    def sum_reserved_credits(self, founder_id: str, *, exclude_reservation_id: Optional[str] = None) -> int:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_budget_reservation_ledgers")
            .select("reserved_credits,reservation_id,astra_budget_reservations!inner(status)")
            .eq("founder_id", founder_id)
            .execute()
            .data
        )
        total = 0
        for row in rows:
            if exclude_reservation_id and row.get("reservation_id") == exclude_reservation_id:
                continue
            joined = row.get("astra_budget_reservations") or {}
            if joined.get("status") == "reserved":
                total += int(row.get("reserved_credits") or 0)
        return total

    def commit(
        self,
        reservation_id: str,
        actual_usd: float,
        *,
        billed_credits: int = 0,
        overspend_usd: float = 0.0,
        unreconciled_credits: int = 0,
        reconciliation_error: Optional[str] = None,
    ) -> None:
        from backend.db.client import get_supabase
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        supabase = get_supabase()
        supabase.table("astra_budget_reservations").update({
            "status": "committed",
            "actual_usd": actual_usd,
            "reconciled_at": now,
        }).eq("id", reservation_id).execute()
        supabase.table("astra_budget_reservation_ledgers").update({
            "billed_credits": max(0, int(billed_credits)),
            "overspend_usd": max(0.0, float(overspend_usd)),
            "unreconciled_credits": max(0, int(unreconciled_credits)),
            "reconciliation_error": reconciliation_error,
            "updated_at": now,
        }).eq("reservation_id", reservation_id).execute()

    def release(self, reservation_id: str) -> None:
        from backend.db.client import get_supabase

        get_supabase().table("astra_budget_reservations").update({"status": "released"}).eq("id", reservation_id).execute()

    def expire(self, reservation_id: str) -> None:
        from backend.db.client import get_supabase

        get_supabase().table("astra_budget_reservations").update({"status": "expired"}).eq("id", reservation_id).execute()

    def list_expired(self, *, now: Optional[str] = None) -> list[BudgetReservation]:
        from backend.db.client import get_supabase
        from datetime import datetime, timezone

        cutoff = now or datetime.now(timezone.utc).isoformat()
        rows = (
            get_supabase().table("astra_budget_reservations")
            .select("*")
            .eq("status", "reserved")
            .lte("expires_at", cutoff)
            .order("expires_at")
            .execute()
            .data
        )
        return [_row_to_reservation(row) for row in rows]


async def durable_create_run(run: Run) -> None:
    try:
        await asyncio.to_thread(SupabaseRunRepository().create, run)
    except Exception as exc:
        logger.warning("durable_create_run failed for run_id=%s: %s", run.id, exc)


async def durable_append_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(SupabaseRunEventRepository().append, run_id, event_type, payload)
    except Exception as exc:
        logger.debug("durable_append_event failed for run_id=%s type=%s: %s", run_id, event_type, exc)

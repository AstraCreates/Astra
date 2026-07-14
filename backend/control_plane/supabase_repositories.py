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
    ActionReceipt,
    ApprovalRequest,
    Artifact,
    BrainAcl,
    BrainRecord,
    BudgetReservation,
    BudgetReservationLedger,
    LegacyRetirementCheck,
    RolloutCampaign,
    RolloutEvidence,
    Run,
    RunEvent,
    RunStep,
    ShadowComparison,
)

logger = logging.getLogger(__name__)


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def _json_safe_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw update-patch dict's values to JSON-serializable forms.

    Callers building patches by hand (e.g. wave7_rollout.py's evaluate_rollout_campaign,
    which sets patch["completed_at"] = datetime.now(timezone.utc) directly) pass real
    datetime objects, not the ISO strings a pydantic model_dump(mode="json") would give
    -- postgrest's httpx json encoder has no datetime support and raises TypeError."""
    import datetime as _dt

    safe: dict[str, Any] = {}
    for key, value in (patch or {}).items():
        safe[key] = value.isoformat() if isinstance(value, (_dt.datetime, _dt.date)) else value
    return safe


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


def _row_to_shadow_comparison(row: dict[str, Any]) -> ShadowComparison:
    return ShadowComparison.model_validate(row)


def _row_to_action_receipt(row: dict[str, Any]) -> ActionReceipt:
    return ActionReceipt.model_validate(row)


def _row_to_brain_record(row: dict[str, Any]) -> BrainRecord:
    return BrainRecord.model_validate(row)


def _row_to_brain_acl(row: dict[str, Any]) -> BrainAcl:
    return BrainAcl.model_validate(row)


def _row_to_rollout_campaign(row: dict[str, Any]) -> RolloutCampaign:
    return RolloutCampaign.model_validate(row)


def _row_to_rollout_evidence(row: dict[str, Any]) -> RolloutEvidence:
    return RolloutEvidence.model_validate(row)


def _row_to_legacy_retirement_check(row: dict[str, Any]) -> LegacyRetirementCheck:
    return LegacyRetirementCheck.model_validate(row)


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
        get_supabase().table("astra_runs").update(_json_safe_patch(patch)).eq("id", run_id).execute()

    def update_fields(self, run_id: str, patch: dict[str, Any]) -> None:
        from backend.db.client import get_supabase

        if not patch:
            return
        get_supabase().table("astra_runs").update(_json_safe_patch(patch)).eq("id", run_id).execute()


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
        get_supabase().table("astra_run_steps").update(_json_safe_patch(patch)).eq("id", step_id).execute()

    def update_fields(self, step_id: str, patch: dict[str, Any]) -> None:
        from backend.db.client import get_supabase

        if not patch:
            return
        get_supabase().table("astra_run_steps").update(_json_safe_patch(patch)).eq("id", step_id).execute()


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
        get_supabase().table("astra_approval_requests").update(_json_safe_patch(patch)).eq("id", request_id).execute()
        updated = self.get(request_id)
        if updated is None:
            raise KeyError(f"unknown request_id {request_id!r}")
        return updated

    def consume(
        self,
        request_id: str,
        *,
        expected_action_digest: str,
        expected_policy_version: str,
    ) -> ApprovalRequest:
        from backend.db.client import get_supabase
        from datetime import datetime, timezone

        current = self.get(request_id)
        if current is None:
            raise KeyError(f"unknown request_id {request_id!r}")
        if current.action_digest != expected_action_digest:
            try:
                from backend.control_plane.anomalies import record_anomaly

                record_anomaly(
                    "approval_mismatch",
                    run_id=current.run_id,
                    step_id=str(current.step_id or ""),
                    payload={
                        "approval_id": request_id,
                        "expected_action_digest": expected_action_digest,
                        "actual_action_digest": current.action_digest,
                        "reason": "action_digest",
                    },
                )
            except Exception:
                pass
            raise ValueError("approval action digest mismatch")
        if current.policy_version != expected_policy_version:
            try:
                from backend.control_plane.anomalies import record_anomaly

                record_anomaly(
                    "approval_mismatch",
                    run_id=current.run_id,
                    step_id=str(current.step_id or ""),
                    payload={
                        "approval_id": request_id,
                        "expected_policy_version": expected_policy_version,
                        "actual_policy_version": current.policy_version,
                        "reason": "policy_version",
                    },
                )
            except Exception:
                pass
            raise ValueError("approval policy version mismatch")
        if current.status == "consumed":
            return current
        if current.status not in {"approved", "skipped"}:
            raise ValueError(f"approval {request_id!r} is not consumable from status {current.status!r}")
        patch = {
            "status": "consumed",
            "consumed_at": datetime.now(timezone.utc).isoformat(),
        }
        get_supabase().table("astra_approval_requests").update(_json_safe_patch(patch)).eq("id", request_id).execute()
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
        events = [_row_to_event(row) for row in rows]
        sequences = [event.sequence for event in events]
        for previous, current in zip(sequences, sequences[1:]):
            if current != previous + 1:
                try:
                    from backend.control_plane.anomalies import record_anomaly

                    record_anomaly(
                        "event_sequence_gap",
                        run_id=run_id,
                        payload={"previous_sequence": previous, "current_sequence": current},
                    )
                except Exception:
                    pass
                break
        return events


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


class SupabaseActionReceiptRepository:
    def create(self, receipt: ActionReceipt) -> ActionReceipt:
        from backend.db.client import get_supabase

        get_supabase().table("astra_action_receipts").upsert(_dump(receipt), on_conflict="id").execute()
        return receipt

    def get_by_action_id(self, action_id: str) -> Optional[ActionReceipt]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_action_receipts")
            .select("*")
            .eq("action_id", action_id)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_action_receipt(rows[0]) if rows else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ActionReceipt]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_action_receipts")
            .select("*")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_action_receipt(rows[0]) if rows else None

    def update_collision_status(self, receipt_id: str, collision_status: str) -> None:
        from backend.db.client import get_supabase

        get_supabase().table("astra_action_receipts").update({"collision_status": collision_status}).eq("id", receipt_id).execute()


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


class SupabaseShadowComparisonRepository:
    def create(self, comparison: ShadowComparison) -> ShadowComparison:
        from backend.db.client import get_supabase

        get_supabase().table("astra_shadow_comparisons").upsert(_dump(comparison), on_conflict="id").execute()
        return comparison

    def list_for_run(self, run_id: str) -> list[ShadowComparison]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_shadow_comparisons")
            .select("*")
            .eq("run_id", run_id)
            .order("created_at")
            .execute()
            .data
        )
        return [_row_to_shadow_comparison(row) for row in rows]


async def durable_create_run(run: Run) -> None:
    try:
        await asyncio.to_thread(SupabaseRunRepository().create, run)
    except Exception as exc:
        logger.warning("durable_create_run failed for run_id=%s: %s", run.id, exc)


async def durable_create_run_with_event(
    run: Run,
    *,
    event_type: str = "run.created",
    payload: Optional[dict[str, Any]] = None,
) -> None:
    try:
        from backend.db.client import get_supabase

        await asyncio.to_thread(
            lambda: get_supabase().rpc(
                "astra_create_run_with_event",
                {
                    "p_run": _dump(run),
                    "p_event_type": event_type,
                    "p_event_payload": payload or {},
                },
            ).execute()
        )
    except Exception as exc:
        logger.warning("durable_create_run_with_event failed for run_id=%s: %s", run.id, exc)


async def durable_append_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(SupabaseRunEventRepository().append, run_id, event_type, payload)
    except Exception as exc:
        logger.debug("durable_append_event failed for run_id=%s type=%s: %s", run_id, event_type, exc)


class SupabaseBrainRecordRepository:
    def create(self, record: BrainRecord) -> BrainRecord:
        from backend.db.client import get_supabase

        get_supabase().table("astra_brain_records").upsert(_dump(record), on_conflict="id").execute()
        return record

    def get(self, record_id: str) -> Optional[BrainRecord]:
        from backend.db.client import get_supabase

        rows = get_supabase().table("astra_brain_records").select("*").eq("id", record_id).limit(1).execute().data
        return _row_to_brain_record(rows[0]) if rows else None

    def list_by_company(self, company_id: str, *, include_tombstoned: bool = False) -> list[BrainRecord]:
        from backend.db.client import get_supabase

        query = get_supabase().table("astra_brain_records").select("*").eq("company_id", company_id)
        if not include_tombstoned:
            query = query.is_("tombstoned_at", "null")
        rows = query.order("created_at").execute().data
        return [_row_to_brain_record(row) for row in rows]

    def list_by_external_id(self, company_id: str, source: str, external_id: str) -> list[BrainRecord]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_brain_records")
            .select("*")
            .eq("company_id", company_id)
            .eq("source", source)
            .eq("external_id", external_id)
            .order("version")
            .execute()
            .data
        )
        return [_row_to_brain_record(row) for row in rows]

    def list_by_ids(self, record_ids: list[str]) -> list[BrainRecord]:
        from backend.db.client import get_supabase

        normalized_ids = [str(record_id).strip() for record_id in record_ids if str(record_id).strip()]
        if not normalized_ids:
            return []
        rows = (
            get_supabase().table("astra_brain_records")
            .select("*")
            .in_("id", normalized_ids)
            .execute()
            .data
        )
        records = [_row_to_brain_record(row) for row in rows]
        by_id = {record.id: record for record in records}
        return [by_id[record_id] for record_id in normalized_ids if record_id in by_id]

    def search_content(self, company_id: str, query: str, limit: int = 10) -> list[BrainRecord]:
        import re

        terms = [term.lower() for term in re.findall(r"\b\w{3,}\b", query) if len(term) > 2]
        if not terms:
            return []
        scored: list[tuple[int, BrainRecord]] = []
        for record in self.list_by_company(company_id, include_tombstoned=False):
            content = record.provenance.get("content") if isinstance(record.provenance, dict) else {}
            title = str((content or {}).get("title") or "").lower()
            body = str((content or {}).get("body") or "").lower()
            score = sum(title.count(term) * 2 + body.count(term) for term in terms)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[: max(1, limit)]]

    def mark_superseded(self, old_record_id: str, new_record_id: str) -> None:
        from backend.db.client import get_supabase

        old = self.get(old_record_id)
        if old is not None:
            provenance = (old.provenance or {}).copy()
            provenance["superseded_by"] = new_record_id
            get_supabase().table("astra_brain_records").update({
                "provenance": provenance,
                "is_canonical": False,
            }).eq("id", old_record_id).execute()

    def mark_tombstone(self, record_id: str) -> None:
        from backend.db.client import get_supabase
        from datetime import datetime, timezone

        get_supabase().table("astra_brain_records").update({
            "tombstoned_at": datetime.now(timezone.utc).isoformat(),
            "is_canonical": False,
        }).eq("id", record_id).execute()


class SupabaseBrainAclRepository:
    def create(self, acl: BrainAcl) -> BrainAcl:
        from backend.db.client import get_supabase

        get_supabase().table("astra_brain_acl").upsert(_dump(acl), on_conflict="id").execute()
        return acl

    def list_for_record(self, record_id: str) -> list[BrainAcl]:
        from backend.db.client import get_supabase

        rows = get_supabase().table("astra_brain_acl").select("*").eq("record_id", record_id).order("created_at").execute().data
        return [_row_to_brain_acl(row) for row in rows]

    def has_access(self, record_id: str, caller_role: str, caller_user_id: Optional[str] = None) -> bool:
        acls = self.list_for_record(record_id)
        if not acls:
            return False
        for acl in acls:
            if acl.principal_type == "company":
                return True
            if acl.principal_type == "role" and acl.principal_id == caller_role:
                return True
            if acl.principal_type == "user" and caller_user_id and acl.principal_id == caller_user_id:
                return True
        return False

    def delete_for_record(self, record_id: str) -> None:
        from backend.db.client import get_supabase

        get_supabase().table("astra_brain_acl").delete().eq("record_id", record_id).execute()


class SupabaseRolloutCampaignRepository:
    def create(self, campaign: RolloutCampaign) -> RolloutCampaign:
        from backend.db.client import get_supabase

        get_supabase().table("astra_rollout_campaigns").upsert(_dump(campaign), on_conflict="id").execute()
        return campaign

    def get_active(self, feature: str) -> Optional[RolloutCampaign]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_rollout_campaigns")
            .select("*")
            .eq("feature", feature)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_rollout_campaign(rows[0]) if rows else None

    def update(self, campaign_id: str, patch: dict[str, object]) -> Optional[RolloutCampaign]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_rollout_campaigns")
            .update(_json_safe_patch(dict(patch or {})))
            .eq("id", campaign_id)
            .execute()
            .data
        )
        return _row_to_rollout_campaign(rows[0]) if rows else None


class SupabaseRolloutEvidenceRepository:
    def create(self, evidence: RolloutEvidence) -> RolloutEvidence:
        from backend.db.client import get_supabase

        get_supabase().table("astra_rollout_evidence").upsert(_dump(evidence), on_conflict="id").execute()
        return evidence

    def list_for_campaign(self, campaign_id: str) -> list[RolloutEvidence]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_rollout_evidence")
            .select("*")
            .eq("campaign_id", campaign_id)
            .order("created_at")
            .execute()
            .data
        )
        return [_row_to_rollout_evidence(row) for row in rows]


class SupabaseLegacyRetirementCheckRepository:
    def upsert(self, check: LegacyRetirementCheck) -> LegacyRetirementCheck:
        from backend.db.client import get_supabase

        get_supabase().table("astra_legacy_retirement_checks").upsert(_dump(check), on_conflict="feature").execute()
        return check

    def get(self, feature: str) -> Optional[LegacyRetirementCheck]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_legacy_retirement_checks")
            .select("*")
            .eq("feature", feature)
            .limit(1)
            .execute()
            .data
        )
        return _row_to_legacy_retirement_check(rows[0]) if rows else None

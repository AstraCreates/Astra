"""In-memory fake implementations of the Wave 1 repository interfaces.

Used by this wave's own tests and by later-wave subagents until a real
Supabase-backed implementation exists. The one property that MUST match the
real astra_append_run_event() Postgres function exactly is atomic,
monotonic, gapless per-run sequence assignment -- FakeRunEventRepository
guards that with a lock the same way the real function's row lock does.
"""
import threading
from datetime import datetime, timezone
from typing import Optional

from backend.control_plane.models import (
    Action,
    ActionReceipt,
    ApprovalRequest,
    Artifact,
    BudgetReservation,
    BudgetReservationLedger,
    Run,
    RunEvent,
    RunStep,
    ShadowComparison,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeRunRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}

    def create(self, run: Run) -> Run:
        with self._lock:
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def update_status(self, run_id: str, status: str, *, error: Optional[str] = None) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"unknown run_id {run_id!r}")
            updated = run.model_copy(update={"status": status, "error": error if error is not None else run.error})
            self._runs[run_id] = updated


class FakeRunStepRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # keyed by (run_id, step_key) -> list of attempts, ordered
        self._attempts: dict[tuple[str, str], list[RunStep]] = {}
        self._by_id: dict[str, RunStep] = {}

    def create_attempt(self, step: RunStep) -> RunStep:
        with self._lock:
            key = (step.run_id, step.step_key)
            existing = self._attempts.setdefault(key, [])
            next_attempt = (max((s.attempt_number for s in existing), default=0)) + 1
            step = step.model_copy(update={"attempt_number": next_attempt})
            existing.append(step)
            self._by_id[step.id] = step
        return step

    def get_latest_attempt(self, run_id: str, step_key: str) -> Optional[RunStep]:
        attempts = self._attempts.get((run_id, step_key)) or []
        return attempts[-1] if attempts else None

    def list_attempts(self, run_id: str, step_key: str) -> list[RunStep]:
        return list(self._attempts.get((run_id, step_key)) or [])

    def update_status(self, step_id: str, status: str, *, error: Optional[str] = None) -> None:
        with self._lock:
            step = self._by_id.get(step_id)
            if step is None:
                raise KeyError(f"unknown step_id {step_id!r}")
            updated = step.model_copy(update={"status": status, "error": error if error is not None else step.error})
            self._by_id[step_id] = updated
            attempts = self._attempts[(step.run_id, step.step_key)]
            attempts[attempts.index(step)] = updated

    def update_fields(self, step_id: str, patch: dict[str, object]) -> None:
        with self._lock:
            step = self._by_id.get(step_id)
            if step is None:
                raise KeyError(f"unknown step_id {step_id!r}")
            updated = step.model_copy(update=dict(patch or {}))
            self._by_id[step_id] = updated
            attempts = self._attempts[(step.run_id, step.step_key)]
            attempts[attempts.index(step)] = updated


class FakeActionRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, Action] = {}
        self._by_idempotency_key: dict[str, str] = {}

    def create(self, action: Action) -> Action:
        with self._lock:
            self._by_id[action.id] = action
            self._by_idempotency_key[action.idempotency_key] = action.id
        return action

    def get(self, action_id: str) -> Optional[Action]:
        return self._by_id.get(action_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Action]:
        action_id = self._by_idempotency_key.get(idempotency_key)
        return self._by_id.get(action_id) if action_id else None

    def update_status(self, action_id: str, status: str) -> None:
        with self._lock:
            action = self._by_id.get(action_id)
            if action is None:
                raise KeyError(f"unknown action_id {action_id!r}")
            self._by_id[action_id] = action.model_copy(update={"status": status})


class FakeApprovalRequestRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, ApprovalRequest] = {}

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            self._by_id[request.id] = request
        return request

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._by_id.get(request_id)

    def get_pending_for_gate(self, run_id: str, gate_key: str) -> list[ApprovalRequest]:
        return [
            r for r in self._by_id.values()
            if r.run_id == run_id and r.gate_key == gate_key and r.status == "pending"
        ]

    def decide(self, request_id: str, status: str, *, decided_by: str, note: Optional[str] = None) -> ApprovalRequest:
        with self._lock:
            request = self._by_id.get(request_id)
            if request is None:
                raise KeyError(f"unknown request_id {request_id!r}")
            updated = request.model_copy(update={
                "status": status, "decided_by": decided_by, "decision_note": note, "decided_at": _now(),
            })
            self._by_id[request_id] = updated
            return updated

    def consume(
        self,
        request_id: str,
        *,
        expected_action_digest: str,
        expected_policy_version: str,
    ) -> ApprovalRequest:
        with self._lock:
            request = self._by_id.get(request_id)
            if request is None:
                raise KeyError(f"unknown request_id {request_id!r}")
            if request.action_digest != expected_action_digest:
                try:
                    from backend.control_plane.anomalies import record_anomaly

                    record_anomaly(
                        "approval_mismatch",
                        run_id=request.run_id,
                        step_id=str(request.step_id or ""),
                        payload={
                            "approval_id": request_id,
                            "expected_action_digest": expected_action_digest,
                            "actual_action_digest": request.action_digest,
                            "reason": "action_digest",
                        },
                    )
                except Exception:
                    pass
                raise ValueError("approval action digest mismatch")
            if request.policy_version != expected_policy_version:
                try:
                    from backend.control_plane.anomalies import record_anomaly

                    record_anomaly(
                        "approval_mismatch",
                        run_id=request.run_id,
                        step_id=str(request.step_id or ""),
                        payload={
                            "approval_id": request_id,
                            "expected_policy_version": expected_policy_version,
                            "actual_policy_version": request.policy_version,
                            "reason": "policy_version",
                        },
                    )
                except Exception:
                    pass
                raise ValueError("approval policy version mismatch")
            if request.status not in {"approved", "skipped", "consumed"}:
                raise ValueError(f"approval {request_id!r} is not consumable from status {request.status!r}")
            if request.status == "consumed":
                return request
            updated = request.model_copy(update={"status": "consumed", "consumed_at": _now()})
            self._by_id[request_id] = updated
            return updated


class FakeRunEventRepository:
    """Mirrors astra_append_run_event()'s locking property: sequence
    assignment for a given run_id is atomic and monotonic, gapless, and
    independent across runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_sequence: dict[str, int] = {}
        self._events: dict[str, list[RunEvent]] = {}

    def append(self, run_id: str, event_type: str, payload: dict) -> int:
        with self._lock:
            sequence = self._next_sequence.get(run_id, 0)
            self._next_sequence[run_id] = sequence + 1
            event = RunEvent(run_id=run_id, sequence=sequence, event_type=event_type, payload=payload, created_at=_now())
            self._events.setdefault(run_id, []).append(event)
            return sequence

    def list_since(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        events = self._events.get(run_id, [])
        filtered = [e for e in events if e.sequence >= after_sequence]
        self._record_gap_if_present(run_id, filtered)
        return filtered

    @staticmethod
    def _record_gap_if_present(run_id: str, events: list[RunEvent]) -> None:
        if not events:
            return
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
                return


class FakeArtifactRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_run: dict[str, dict[str, Artifact]] = {}

    def upsert(self, artifact: Artifact) -> Artifact:
        with self._lock:
            self._by_run.setdefault(artifact.run_id, {})[artifact.key] = artifact
        return artifact

    def list_for_run(self, run_id: str) -> list[Artifact]:
        return list(self._by_run.get(run_id, {}).values())


class FakeActionReceiptRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, ActionReceipt] = {}
        self._by_action_id: dict[str, str] = {}
        self._by_idempotency_key: dict[str, str] = {}

    def create(self, receipt: ActionReceipt) -> ActionReceipt:
        with self._lock:
            existing_id = self._by_idempotency_key.get(receipt.idempotency_key)
            if existing_id and existing_id != receipt.id:
                raise KeyError(f"duplicate idempotency_key {receipt.idempotency_key!r}")
            self._by_id[receipt.id] = receipt
            self._by_action_id[receipt.action_id] = receipt.id
            self._by_idempotency_key[receipt.idempotency_key] = receipt.id
            return receipt

    def get_by_action_id(self, action_id: str) -> Optional[ActionReceipt]:
        receipt_id = self._by_action_id.get(action_id)
        return self._by_id.get(receipt_id) if receipt_id else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ActionReceipt]:
        receipt_id = self._by_idempotency_key.get(idempotency_key)
        return self._by_id.get(receipt_id) if receipt_id else None

    def update_collision_status(self, receipt_id: str, collision_status: str) -> None:
        with self._lock:
            receipt = self._by_id.get(receipt_id)
            if receipt is None:
                raise KeyError(f"unknown receipt_id {receipt_id!r}")
            self._by_id[receipt_id] = receipt.model_copy(update={"collision_status": collision_status})


class FakeBudgetReservationRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BudgetReservation] = {}
        self._ledger_by_id: dict[str, BudgetReservationLedger] = {}

    def reserve(
        self,
        reservation: BudgetReservation,
        *,
        founder_id: Optional[str] = None,
        reserved_credits: Optional[int] = None,
        markup: float = 10.0,
    ) -> BudgetReservation:
        with self._lock:
            if reservation.id in self._by_id:
                raise KeyError(f"duplicate reservation_id {reservation.id!r}")
            self._by_id[reservation.id] = reservation
            if founder_id is not None:
                now = _now()
                self._ledger_by_id[reservation.id] = BudgetReservationLedger(
                    reservation_id=reservation.id,
                    founder_id=founder_id,
                    reserved_credits=max(0, int(reserved_credits or 0)),
                    markup=markup,
                    created_at=now,
                    updated_at=now,
                )
        return reservation

    def get(self, reservation_id: str) -> Optional[BudgetReservation]:
        return self._by_id.get(reservation_id)

    def get_ledger(self, reservation_id: str) -> Optional[BudgetReservationLedger]:
        return self._ledger_by_id.get(reservation_id)

    def sum_reserved_credits(self, founder_id: str, *, exclude_reservation_id: Optional[str] = None) -> int:
        with self._lock:
            total = 0
            for reservation_id, ledger in self._ledger_by_id.items():
                if ledger.founder_id != founder_id or reservation_id == exclude_reservation_id:
                    continue
                reservation = self._by_id.get(reservation_id)
                if reservation and reservation.status == "reserved":
                    total += ledger.reserved_credits
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
        with self._lock:
            r = self._by_id.get(reservation_id)
            if r is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            if r.status == "committed":
                if r.actual_usd != actual_usd:
                    raise ValueError(f"reservation {reservation_id!r} already committed with actual_usd={r.actual_usd!r}")
                return
            if r.status != "reserved":
                raise ValueError(f"reservation {reservation_id!r} cannot commit from status {r.status!r}")
            now = _now()
            self._by_id[reservation_id] = r.model_copy(update={"status": "committed", "actual_usd": actual_usd, "reconciled_at": now})
            ledger = self._ledger_by_id.get(reservation_id)
            if ledger is not None:
                self._ledger_by_id[reservation_id] = ledger.model_copy(update={
                    "billed_credits": max(0, int(billed_credits)),
                    "overspend_usd": max(0.0, float(overspend_usd)),
                    "unreconciled_credits": max(0, int(unreconciled_credits)),
                    "reconciliation_error": reconciliation_error,
                    "updated_at": now,
                })

    def release(self, reservation_id: str) -> None:
        with self._lock:
            r = self._by_id.get(reservation_id)
            if r is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            if r.status == "released":
                return
            if r.status != "reserved":
                raise ValueError(f"reservation {reservation_id!r} cannot release from status {r.status!r}")
            self._by_id[reservation_id] = r.model_copy(update={"status": "released"})

    def expire(self, reservation_id: str) -> None:
        with self._lock:
            r = self._by_id.get(reservation_id)
            if r is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            if r.status == "expired":
                return
            if r.status != "reserved":
                raise ValueError(f"reservation {reservation_id!r} cannot expire from status {r.status!r}")
            self._by_id[reservation_id] = r.model_copy(update={"status": "expired"})

    def list_expired(self, *, now: Optional[str] = None) -> list[BudgetReservation]:
        cutoff = datetime.fromisoformat(now) if now else _now()
        return [r for r in self._by_id.values() if r.status == "reserved" and r.expires_at <= cutoff]


class FakeShadowComparisonRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_run: dict[str, list[ShadowComparison]] = {}

    def create(self, comparison: ShadowComparison) -> ShadowComparison:
        with self._lock:
            self._by_run.setdefault(comparison.run_id, []).append(comparison)
        return comparison

    def list_for_run(self, run_id: str) -> list[ShadowComparison]:
        return list(self._by_run.get(run_id, []))

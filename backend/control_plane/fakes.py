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
    ApprovalRequest,
    Artifact,
    BudgetReservation,
    Run,
    RunEvent,
    RunStep,
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
        return [e for e in events if e.sequence >= after_sequence]


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


class FakeBudgetReservationRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BudgetReservation] = {}

    def reserve(self, reservation: BudgetReservation) -> BudgetReservation:
        with self._lock:
            self._by_id[reservation.id] = reservation
        return reservation

    def get(self, reservation_id: str) -> Optional[BudgetReservation]:
        return self._by_id.get(reservation_id)

    def commit(self, reservation_id: str, actual_usd: float) -> None:
        with self._lock:
            r = self._by_id.get(reservation_id)
            if r is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            self._by_id[reservation_id] = r.model_copy(update={"status": "committed", "actual_usd": actual_usd, "reconciled_at": _now()})

    def release(self, reservation_id: str) -> None:
        with self._lock:
            r = self._by_id.get(reservation_id)
            if r is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            self._by_id[reservation_id] = r.model_copy(update={"status": "released"})

    def list_expired(self, *, now: Optional[str] = None) -> list[BudgetReservation]:
        cutoff = datetime.fromisoformat(now) if now else _now()
        return [r for r in self._by_id.values() if r.status == "reserved" and r.expires_at <= cutoff]

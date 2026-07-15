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

    def list_pending_for_run(self, run_id: str) -> list[ApprovalRequest]:
        return [
            r for r in self._by_id.values()
            if r.run_id == run_id and r.status == "pending"
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


class FakeBrainRecordRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BrainRecord] = {}

    def create(self, record: BrainRecord) -> BrainRecord:
        with self._lock:
            self._by_id[record.id] = record
        return record

    def get(self, record_id: str) -> Optional[BrainRecord]:
        return self._by_id.get(record_id)

    def list_by_company(self, company_id: str, *, include_tombstoned: bool = False) -> list[BrainRecord]:
        records = [r for r in self._by_id.values() if r.company_id == company_id]
        if not include_tombstoned:
            records = [r for r in records if r.tombstoned_at is None]
        return records

    def list_by_external_id(self, company_id: str, source: str, external_id: str) -> list[BrainRecord]:
        return [
            r for r in self._by_id.values()
            if r.company_id == company_id and r.source == source and r.external_id == external_id
        ]

    def list_by_ids(self, record_ids: list[str]) -> list[BrainRecord]:
        return [self._by_id[record_id] for record_id in record_ids if record_id in self._by_id]

    def search_content(self, company_id: str, query: str, limit: int = 10) -> list[BrainRecord]:
        import re

        terms = set(re.findall(r"\b\w{3,}\b", query.lower()))
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
        return [record for _, record in scored[:limit]]

    def mark_superseded(self, old_record_id: str, new_record_id: str) -> None:
        with self._lock:
            old = self._by_id.get(old_record_id)
            if old is not None:
                provenance = old.provenance.copy() if old.provenance else {}
                provenance["superseded_by"] = new_record_id
                self._by_id[old_record_id] = old.model_copy(update={"provenance": provenance, "is_canonical": False})

    def mark_tombstone(self, record_id: str) -> None:
        with self._lock:
            record = self._by_id.get(record_id)
            if record is not None:
                self._by_id[record_id] = record.model_copy(update={"tombstoned_at": _now(), "is_canonical": False})


class FakeBrainRecordRepositoryForRetrieval:
    """Expanded FakeBrainRecordRepository with retrieval-specific methods."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}  # Store as dicts for retrieval

    def get(self, record_id: str) -> Optional[dict]:
        return self._by_id.get(record_id)

    def list_by_ids(self, record_ids: list[str]) -> list[dict]:
        return [self._by_id[rid] for rid in record_ids if rid in self._by_id]

    def search_content(self, company_id: str, query: str, limit: int = 10) -> list[dict]:
        """Simple full-text search on content field."""
        import re
        query_lower = query.lower()
        terms = set(re.findall(r"\b\w{3,}\b", query_lower))

        results = []
        for record in self._by_id.values():
            if record.get("company_id") != company_id:
                continue
            if record.get("tombstoned_at"):
                continue

            content_lower = (record.get("content", "") or "").lower()
            title_lower = (record.get("title", "") or "").lower()

            # Score by term matches
            score = sum(
                title_lower.count(t) * 2 + content_lower.count(t)
                for t in terms
            )
            if score > 0:
                results.append((score, record))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def insert(self, record_id: str, record: dict) -> None:
        """Insert or update a record."""
        with self._lock:
            self._by_id[record_id] = record


class FakeBrainAclRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, BrainAcl] = {}
        self._by_record: dict[str, list[BrainAcl]] = {}

    def create(self, acl: BrainAcl) -> BrainAcl:
        with self._lock:
            self._by_id[acl.id] = acl
            self._by_record.setdefault(acl.record_id, []).append(acl)
        return acl

    def list_for_record(self, record_id: str) -> list[BrainAcl]:
        return list(self._by_record.get(record_id, []))

    def has_access(self, record_id: str, caller_role: str, caller_user_id: Optional[str] = None) -> bool:
        """Check if the caller has access to this record.

        If ACLs are defined, caller must match at least one.
        If no ACLs are defined, deny by default (fail secure).
        """
        acls = self.list_for_record(record_id)
        if not acls:
            # No ACLs defined = deny access (fail secure)
            return False

        # Check if caller_role or caller_user_id appears in ACLs
        for acl in acls:
            if acl.principal_type == "company":
                return True
            if acl.principal_type == "role" and acl.principal_id == caller_role:
                return True
            if acl.principal_type == "user" and acl.principal_id == caller_user_id:
                return True
        return False

    def delete_for_record(self, record_id: str) -> None:
        with self._lock:
            acls = self._by_record.pop(record_id, [])
            for acl in acls:
                self._by_id.pop(acl.id, None)


class FakeGraphitiClient:
    """Fake Graphiti vector search client."""
    def __init__(self) -> None:
        self._indexed_records: dict[str, list[str]] = {}  # company_id -> list of record_ids
        self._episodes: dict[str, dict[str, dict]] = {}

    def search(self, query: str, top_k: int = 10, company_id: Optional[str] = None) -> dict:
        """Fake vector search that returns indexed record IDs."""
        if not company_id or company_id not in self._indexed_records:
            # Return empty results if no indexed records for this company
            return {"record_ids": []}

        # For testing, just return first top_k from indexed records
        record_ids = self._indexed_records.get(company_id, [])[:top_k]
        return {"record_ids": record_ids}

    def index_records(self, company_id: str, record_ids: list[str]) -> None:
        """Index records for a company (for testing)."""
        self._indexed_records[company_id] = record_ids

    def upsert_episode(self, company_id: str, episode_id: str, text: str, metadata: dict) -> None:
        self._episodes.setdefault(company_id, {})[episode_id] = {"text": text, "metadata": metadata}
        indexed = self._indexed_records.setdefault(company_id, [])
        if episode_id not in indexed:
            indexed.append(episode_id)

    def clear_namespace(self, company_id: str) -> None:
        self._indexed_records.pop(company_id, None)
        self._episodes.pop(company_id, None)

    def delete_episode(self, company_id: str, episode_id: str) -> None:
        self._episodes.get(company_id, {}).pop(episode_id, None)
        indexed = self._indexed_records.get(company_id, [])
        if episode_id in indexed:
            indexed.remove(episode_id)

    def get_episode(self, company_id: str, episode_id: str) -> Optional[dict]:
        return self._episodes.get(company_id, {}).get(episode_id)

    def mark_superseded(self, company_id: str, old_episode_id: str, new_episode_id: str) -> None:
        episode = self._episodes.get(company_id, {}).get(old_episode_id)
        if not episode:
            return
        metadata = dict(episode.get("metadata") or {})
        metadata["superseded_by"] = new_episode_id
        metadata["status"] = "superseded"
        episode["metadata"] = metadata


class FakeRolloutCampaignRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, RolloutCampaign] = {}

    def create(self, campaign: RolloutCampaign) -> RolloutCampaign:
        with self._lock:
            self._by_id[campaign.id] = campaign
        return campaign

    def get_active(self, feature: str) -> Optional[RolloutCampaign]:
        campaigns = [
            campaign for campaign in self._by_id.values()
            if campaign.feature == feature and campaign.status == "active"
        ]
        campaigns.sort(key=lambda item: item.created_at or _now(), reverse=True)
        return campaigns[0] if campaigns else None

    def update(self, campaign_id: str, patch: dict[str, object]) -> Optional[RolloutCampaign]:
        with self._lock:
            campaign = self._by_id.get(campaign_id)
            if campaign is None:
                return None
            updated = campaign.model_copy(update=dict(patch or {}))
            self._by_id[campaign_id] = updated
            return updated


class FakeRolloutEvidenceRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_campaign: dict[str, list[RolloutEvidence]] = {}

    def create(self, evidence: RolloutEvidence) -> RolloutEvidence:
        with self._lock:
            self._by_campaign.setdefault(evidence.campaign_id, []).append(evidence)
        return evidence

    def list_for_campaign(self, campaign_id: str) -> list[RolloutEvidence]:
        return list(self._by_campaign.get(campaign_id, []))


class FakeLegacyRetirementCheckRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_feature: dict[str, LegacyRetirementCheck] = {}

    def upsert(self, check: LegacyRetirementCheck) -> LegacyRetirementCheck:
        with self._lock:
            self._by_feature[check.feature] = check
        return check

    def get(self, feature: str) -> Optional[LegacyRetirementCheck]:
        return self._by_feature.get(feature)

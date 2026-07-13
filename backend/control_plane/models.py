"""Wave 1 control-plane domain contracts.

Field-for-field mirrors of supabase/migrations/0001-0013. Nothing in the
running app constructs these yet -- later waves wire them in. Pure,
additive, unused-by-anything-yet code.
"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

RunStatus = Literal["queued", "running", "awaiting_approval", "cancelling", "cancelled", "succeeded", "failed"]
StepStatus = RunStatus
ActionStatus = Literal["pending", "approved", "executing", "succeeded", "failed", "blocked"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "skipped", "consumed"]
ArtifactVerificationStatus = Literal["unverified", "passed", "weak", "missing"]
ReservationStatus = Literal["reserved", "committed", "released", "expired"]
CollisionStatus = Literal["none", "detected", "resolved"]
BrainJobType = Literal["upsert", "tombstone", "rebuild"]
BrainJobStatus = Literal["pending", "running", "succeeded", "failed", "dead_letter"]
RolloutStage = Literal["internal_fixture", "internal_live", "pct_1", "pct_5", "pct_25", "pct_50", "pct_100"]
RolloutCampaignStatus = Literal["draft", "active", "halted", "rolled_back", "completed"]
RolloutEvidenceKind = Literal["fixture", "chaos", "live_run", "halt_probe", "rollback_drill", "archive_snapshot"]
LegacyRetirementStatus = Literal["pending", "ready", "blocked", "completed"]


class Run(BaseModel):
    id: str
    owner_id: str
    org_id: str
    company_id: Optional[str] = None
    workspace_id: Optional[str] = None
    chapter_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    goal: str
    stack_id: Optional[str] = None
    engine: str = "legacy"
    workflow_version: str = "v1"
    status: RunStatus = "queued"
    next_event_sequence: int = 0
    budget_limit_usd: Optional[float] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancellation_requested_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunStep(BaseModel):
    id: str
    run_id: str
    step_key: str
    parent_step_id: Optional[str] = None
    kind: str
    agent: Optional[str] = None
    phase: Optional[str] = None
    status: StepStatus = "queued"
    attempt_number: int = 1
    max_attempts: int = 1
    input_ref: Optional[str] = None
    output_ref: Optional[str] = None
    idempotency_key: Optional[str] = None
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class Action(BaseModel):
    id: str
    run_id: str
    step_id: Optional[str] = None
    tool: str
    canonical_args_hash: str
    risk_level: str = "low"
    approval_id: Optional[str] = None
    idempotency_key: str
    status: ActionStatus = "pending"
    receipt: Optional[dict] = None
    created_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None


class ApprovalRequest(BaseModel):
    id: str
    run_id: str
    step_id: Optional[str] = None
    action_id: Optional[str] = None
    gate_key: str
    action_digest: str
    required_role: str = "owner"
    policy_version: str = "v1"
    status: ApprovalStatus = "pending"
    expires_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None
    revision: int = 1
    created_at: Optional[datetime] = None


class RunEvent(BaseModel):
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class Artifact(BaseModel):
    id: str
    run_id: str
    step_id: Optional[str] = None
    key: str
    uri: Optional[str] = None
    content_hash: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    verification_status: ArtifactVerificationStatus = "unverified"
    created_at: Optional[datetime] = None


class BudgetReservation(BaseModel):
    id: str
    run_id: str
    step_id: Optional[str] = None
    estimated_max_usd: float
    actual_usd: Optional[float] = None
    status: ReservationStatus = "reserved"
    expires_at: datetime
    provider_request_id: Optional[str] = None
    reconciled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class BudgetReservationLedger(BaseModel):
    reservation_id: str
    founder_id: str
    reserved_credits: int
    markup: float = 10.0
    billed_credits: int = 0
    overspend_usd: float = 0.0
    unreconciled_credits: int = 0
    reconciliation_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ActionReceipt(BaseModel):
    id: str
    action_id: str
    idempotency_key: str
    provider_result: Optional[dict] = None
    collision_status: CollisionStatus = "none"
    created_at: Optional[datetime] = None


class ShadowComparison(BaseModel):
    id: str
    run_id: str
    comparison_type: str
    discrepancies: list[Any] = Field(default_factory=list)
    passed: bool = False
    created_at: Optional[datetime] = None


class BrainRecord(BaseModel):
    id: str
    company_id: str
    source: str
    external_id: str
    version: int = 1
    content_hash: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    is_canonical: bool = True
    tombstoned_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class BrainAcl(BaseModel):
    id: str
    record_id: str
    principal_type: Literal["company", "user", "role"]
    principal_id: str
    access_level: Literal["read", "write"] = "read"
    created_at: Optional[datetime] = None


class BrainProjectionJob(BaseModel):
    id: str
    record_id: str
    job_type: BrainJobType
    status: BrainJobStatus = "pending"
    attempts: int = 0
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    last_attempted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RolloutCampaign(BaseModel):
    id: str
    feature: str
    stage: RolloutStage = "internal_fixture"
    status: RolloutCampaignStatus = "draft"
    started_at: Optional[datetime] = None
    last_stage_changed_at: Optional[datetime] = None
    required_sample_size: int = 0
    observed_sample_size: int = 0
    required_observation_hours: int = 24
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RolloutEvidence(BaseModel):
    id: str
    campaign_id: str
    run_id: Optional[str] = None
    kind: RolloutEvidenceKind
    stage: RolloutStage
    passed: bool = False
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class LegacyRetirementCheck(BaseModel):
    id: str
    feature: str
    status: LegacyRetirementStatus = "pending"
    temporal_run_count: int = 0
    clean_days: int = 0
    restart_chaos_passed: bool = False
    parity_discrepancies_open: int = 0
    rollback_drill_passed: bool = False
    archival_snapshots_exported: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

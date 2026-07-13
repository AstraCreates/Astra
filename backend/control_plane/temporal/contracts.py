"""Shared Temporal control-plane contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

TASK_QUEUE = "astra-runs-v1"
WORKFLOW_NAME = "AstraRun"
WORKFLOW_ID_PREFIX = "astra-run"
SHADOW_WORKFLOW_ID_PREFIX = "astra-run-shadow"


def workflow_id_for_run(run_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}/{run_id}"


def shadow_workflow_id_for_run(run_id: str) -> str:
    return f"{SHADOW_WORKFLOW_ID_PREFIX}/{run_id}"


@dataclass
class RunInput:
    """IDs-only workflow input for durable run execution."""

    run_id: str


@dataclass
class ApprovalDecisionInput:
    approval_id: str
    action_digest: str
    decision: str
    policy_version: Optional[str] = None
    decided_by: Optional[str] = None
    note: Optional[str] = None


@dataclass
class RetryStepInput:
    step_key: str
    requested_by: Optional[str] = None
    note: Optional[str] = None


@dataclass
class PhaseGateInput:
    run_id: str
    gate_key: str
    phase_name: str
    next_phase: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    timeout_seconds: int = 7200


@dataclass
class PhaseGateResult:
    run_id: str
    gate_key: str
    approval_id: str
    action_digest: str
    decision: str
    note: Optional[str] = None


@dataclass
class LaneAttemptInput:
    run_id: str
    step_key: str


@dataclass
class LaneAttemptResult:
    run_id: str
    step_key: str
    step_id: str
    agent: str
    status: str
    attempt_number: int
    result: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class DeepResearchInput:
    """IDs-only (PLAN.md invariant #5): the actual query/focus text lives in
    session meta under run_id, fetched inside the activity -- never placed in
    Temporal workflow history."""

    run_id: str
    step_id: str
    query_id: str


@dataclass
class DeepResearchResult:
    run_id: str
    query_id: str
    status: str  # "completed" | "cancelled" | "error"
    structured: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class VerificationInput:
    run_id: str
    step_key: str
    attempt_number: int = 1


@dataclass
class VerificationResult:
    run_id: str
    step_key: str
    agent: str
    status: str
    verification: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseRunInput:
    run_id: str
    phase_name: str
    next_phase: str
    step_keys: list[str] = field(default_factory=list)
    step_dependencies: dict[str, list[str]] = field(default_factory=dict)
    timeout_seconds: int = 7200


@dataclass
class PhaseRunResult:
    run_id: str
    phase_name: str
    next_phase: str
    status: str
    decision: str = "approved"
    lane_results: list[dict[str, Any]] = field(default_factory=list)
    approval: Optional[dict[str, Any]] = None


@dataclass
class MultiPhaseRunInput:
    run_id: str
    phases: list[PhaseRunInput] = field(default_factory=list)
    completed_phases_seed: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MultiPhaseRunResult:
    run_id: str
    status: str
    completed_phases: list[dict[str, Any]] = field(default_factory=list)
    stopped_phase: Optional[str] = None
    decision: Optional[str] = None


@dataclass
class WorkflowObservedState:
    run_id: str
    workflow_status: str = "queued"
    active_step: Optional[str] = None
    waiting_approval: Optional[dict[str, Any]] = None
    cancellation_requested: bool = False
    shadow_mode: bool = False
    sequence: int = 0
    last_event_type: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """Workflow result for a completed run."""

    run_id: str
    status: str
    error: Optional[str] = None
    session_id: Optional[str] = None

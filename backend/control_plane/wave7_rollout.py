"""Wave 7 rollout governance for control-plane migration.

This module owns the durable staged-rollout rules that sit above per-run
feature assignment. It records rollout evidence, evaluates halt conditions,
advances stages only when their observation window and sample requirements are
met, and blocks legacy retirement until every required proof exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from backend.control_plane.models import (
    LegacyRetirementCheck,
    RolloutCampaign,
    RolloutEvidence,
    RolloutStage,
)

STAGE_ORDER: tuple[RolloutStage, ...] = (
    "internal_fixture",
    "internal_live",
    "pct_1",
    "pct_5",
    "pct_25",
    "pct_50",
    "pct_100",
)

STAGE_PERCENT: dict[RolloutStage, int] = {
    "internal_fixture": 0,
    "internal_live": 0,
    "pct_1": 1,
    "pct_5": 5,
    "pct_25": 25,
    "pct_50": 50,
    "pct_100": 100,
}

DEFAULT_STAGE_SAMPLE_SIZE: dict[RolloutStage, int] = {
    "internal_fixture": 5,
    "internal_live": 10,
    "pct_1": 25,
    "pct_5": 50,
    "pct_25": 100,
    "pct_50": 250,
    "pct_100": 1000,
}


@dataclass
class Wave7Repositories:
    campaign_repo: Any
    evidence_repo: Any
    retirement_repo: Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repos(
    campaign_repo: Any | None = None,
    evidence_repo: Any | None = None,
    retirement_repo: Any | None = None,
) -> Wave7Repositories:
    if campaign_repo is not None and evidence_repo is not None and retirement_repo is not None:
        return Wave7Repositories(campaign_repo, evidence_repo, retirement_repo)
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    return Wave7Repositories(
        campaign_repo or SupabaseRolloutCampaignRepository() if campaign_repo is None else campaign_repo,
        evidence_repo or SupabaseRolloutEvidenceRepository() if evidence_repo is None else evidence_repo,
        retirement_repo or SupabaseLegacyRetirementCheckRepository() if retirement_repo is None else retirement_repo,
    )


def start_rollout_campaign(
    *,
    feature: str,
    stage: RolloutStage = "internal_fixture",
    required_sample_size: Optional[int] = None,
    observation_hours: int = 24,
    metadata: Optional[dict[str, Any]] = None,
    campaign_repo: Any | None = None,
) -> RolloutCampaign:
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    now = _utc_now()
    campaign = RolloutCampaign(
        id=str(uuid4()),
        feature=feature,
        stage=stage,
        status="active",
        started_at=now,
        last_stage_changed_at=now,
        required_sample_size=required_sample_size if required_sample_size is not None else DEFAULT_STAGE_SAMPLE_SIZE[stage],
        observed_sample_size=0,
        required_observation_hours=max(0, int(observation_hours)),
        metadata=dict(metadata or {}),
        created_at=now,
    )
    repos = _repos(
        campaign_repo=campaign_repo or SupabaseRolloutCampaignRepository(),
        evidence_repo=SupabaseRolloutEvidenceRepository(),
        retirement_repo=SupabaseLegacyRetirementCheckRepository(),
    )
    return repos.campaign_repo.create(campaign)


def get_rollout_percentage(
    feature: str,
    *,
    default_percent: int,
    campaign_repo: Any | None = None,
) -> int:
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )
    try:
        campaign = _repos(
            campaign_repo=campaign_repo or SupabaseRolloutCampaignRepository(),
            evidence_repo=SupabaseRolloutEvidenceRepository(),
            retirement_repo=SupabaseLegacyRetirementCheckRepository(),
        ).campaign_repo.get_active(feature)
    except Exception:
        campaign = None
    if campaign is None:
        return max(0, min(100, int(default_percent)))
    if campaign.status != "active":
        return 0 if campaign.status in {"halted", "rolled_back"} else max(0, min(100, int(default_percent)))
    return STAGE_PERCENT.get(campaign.stage, max(0, min(100, int(default_percent))))


def record_rollout_evidence(
    *,
    campaign_id: str,
    kind: str,
    stage: RolloutStage,
    passed: bool,
    summary: str,
    metrics: Optional[dict[str, Any]] = None,
    run_id: str | None = None,
    evidence_repo: Any | None = None,
) -> RolloutEvidence:
    evidence = RolloutEvidence(
        id=str(uuid4()),
        campaign_id=campaign_id,
        run_id=run_id,
        kind=kind,  # type: ignore[arg-type]
        stage=stage,
        passed=passed,
        summary=summary,
        metrics=dict(metrics or {}),
        created_at=_utc_now(),
    )
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    repos = _repos(
        campaign_repo=SupabaseRolloutCampaignRepository(),
        evidence_repo=evidence_repo or SupabaseRolloutEvidenceRepository(),
        retirement_repo=SupabaseLegacyRetirementCheckRepository(),
    )
    return repos.evidence_repo.create(evidence)


def evaluate_rollout_campaign(
    *,
    feature: str,
    baseline_completion_rate: float,
    baseline_p95_latency_ms: float,
    campaign_repo: Any | None = None,
    evidence_repo: Any | None = None,
) -> dict[str, Any]:
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    repos = _repos(
        campaign_repo=campaign_repo or SupabaseRolloutCampaignRepository(),
        evidence_repo=evidence_repo or SupabaseRolloutEvidenceRepository(),
        retirement_repo=SupabaseLegacyRetirementCheckRepository(),
    )
    campaign = repos.campaign_repo.get_active(feature)
    if campaign is None:
        return {"ok": False, "reason": "no_active_campaign"}

    evidence = repos.evidence_repo.list_for_campaign(campaign.id)
    now = _utc_now()
    halt_reasons = _halt_reasons(evidence, baseline_completion_rate, baseline_p95_latency_ms)
    observation_ready = _observation_window_satisfied(campaign, now)
    sample_size = len([item for item in evidence if item.kind in {"fixture", "chaos", "live_run"} and item.passed])
    stage_ready = sample_size >= max(1, int(campaign.required_sample_size or 0))

    patch: dict[str, Any] = {"observed_sample_size": sample_size}
    result: dict[str, Any] = {
        "ok": True,
        "campaign_id": campaign.id,
        "feature": feature,
        "stage": campaign.stage,
        "status": campaign.status,
        "observation_ready": observation_ready,
        "sample_ready": stage_ready,
        "halt_reasons": halt_reasons,
    }
    if halt_reasons:
        patch["status"] = "halted"
        patch.setdefault("metadata", dict(campaign.metadata or {}))
        patch["metadata"]["halt_reasons"] = halt_reasons
        updated = repos.campaign_repo.update(campaign.id, patch)
        result["status"] = getattr(updated, "status", "halted")
        return result
    if observation_ready and stage_ready:
        next_stage = _next_stage(campaign.stage)
        if next_stage is None:
            patch["status"] = "completed"
            patch["completed_at"] = now
            updated = repos.campaign_repo.update(campaign.id, patch)
            result["status"] = getattr(updated, "status", "completed")
            result["advanced_to"] = None
            return result
        patch.update({
            "stage": next_stage,
            "last_stage_changed_at": now,
            "required_sample_size": DEFAULT_STAGE_SAMPLE_SIZE[next_stage],
            "observed_sample_size": 0,
            "metadata": dict(campaign.metadata or {}),
        })
        patch["metadata"]["previous_stage"] = campaign.stage
        updated = repos.campaign_repo.update(campaign.id, patch)
        result["stage"] = getattr(updated, "stage", next_stage)
        result["advanced_to"] = next_stage
    return result


def mark_rollout_rolled_back(
    *,
    feature: str,
    reason: str,
    campaign_repo: Any | None = None,
) -> dict[str, Any]:
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )
    repos = _repos(
        campaign_repo=campaign_repo or SupabaseRolloutCampaignRepository(),
        evidence_repo=SupabaseRolloutEvidenceRepository(),
        retirement_repo=SupabaseLegacyRetirementCheckRepository(),
    )
    campaign = repos.campaign_repo.get_active(feature)
    if campaign is None:
        return {"ok": False, "reason": "no_active_campaign"}
    metadata = dict(campaign.metadata or {})
    metadata["rollback_reason"] = reason
    updated = repos.campaign_repo.update(campaign.id, {"status": "rolled_back", "metadata": metadata})
    return {"ok": updated is not None, "campaign_id": campaign.id, "status": getattr(updated, "status", "rolled_back")}


def evaluate_legacy_retirement(
    *,
    feature: str,
    temporal_run_count: int,
    clean_days: int,
    restart_chaos_passed: bool,
    parity_discrepancies_open: int,
    rollback_drill_passed: bool,
    archival_snapshots_exported: bool,
    retirement_repo: Any | None = None,
    metadata: Optional[dict[str, Any]] = None,
) -> LegacyRetirementCheck:
    ready = (
        temporal_run_count >= 1000
        or clean_days >= 30
    ) and restart_chaos_passed and parity_discrepancies_open == 0 and rollback_drill_passed and archival_snapshots_exported
    status = "ready" if ready else "blocked"
    check = LegacyRetirementCheck(
        id=str(uuid4()),
        feature=feature,
        status=status,
        temporal_run_count=max(0, int(temporal_run_count)),
        clean_days=max(0, int(clean_days)),
        restart_chaos_passed=bool(restart_chaos_passed),
        parity_discrepancies_open=max(0, int(parity_discrepancies_open)),
        rollback_drill_passed=bool(rollback_drill_passed),
        archival_snapshots_exported=bool(archival_snapshots_exported),
        metadata=dict(metadata or {}),
        created_at=_utc_now(),
        completed_at=_utc_now() if ready else None,
    )
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )
    repos = _repos(
        campaign_repo=SupabaseRolloutCampaignRepository(),
        evidence_repo=SupabaseRolloutEvidenceRepository(),
        retirement_repo=retirement_repo or SupabaseLegacyRetirementCheckRepository(),
    )
    return repos.retirement_repo.upsert(check)


def rollout_status_snapshot(
    *,
    features: tuple[str, ...] = ("control_plane_v2", "event_stream_v2", "model_gateway_v2", "research_engine_v2", "brain_v2"),
    campaign_repo: Any | None = None,
    retirement_repo: Any | None = None,
) -> dict[str, Any]:
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    repos = _repos(
        campaign_repo=campaign_repo or SupabaseRolloutCampaignRepository(),
        evidence_repo=SupabaseRolloutEvidenceRepository(),
        retirement_repo=retirement_repo or SupabaseLegacyRetirementCheckRepository(),
    )
    campaigns: dict[str, Any] = {}
    retirement: dict[str, Any] = {}
    for feature in features:
        campaign = repos.campaign_repo.get_active(feature)
        if campaign is not None:
            campaigns[feature] = campaign.model_dump(mode="json")
        check = repos.retirement_repo.get(feature)
        if check is not None:
            retirement[feature] = check.model_dump(mode="json")
    return {"campaigns": campaigns, "legacy_retirement": retirement}


def _observation_window_satisfied(campaign: RolloutCampaign, now: datetime) -> bool:
    changed = campaign.last_stage_changed_at or campaign.started_at or now
    return now >= changed + timedelta(hours=max(0, int(campaign.required_observation_hours or 0)))


def _next_stage(stage: RolloutStage) -> RolloutStage | None:
    try:
        index = STAGE_ORDER.index(stage)
    except ValueError:
        return None
    if index >= len(STAGE_ORDER) - 1:
        return None
    return STAGE_ORDER[index + 1]


def _halt_reasons(
    evidence: list[RolloutEvidence],
    baseline_completion_rate: float,
    baseline_p95_latency_ms: float,
) -> list[str]:
    reasons: list[str] = []
    for item in evidence:
        metrics = item.metrics or {}
        if metrics.get("tenant_leak_probe_failed"):
            reasons.append("tenant_leak_probe_failed")
        if metrics.get("approval_digest_mismatch"):
            reasons.append("approval_digest_mismatch")
        if metrics.get("duplicate_external_effect_receipt"):
            reasons.append("duplicate_external_effect_receipt")
        if metrics.get("budget_overshoot_unexplained"):
            reasons.append("budget_overshoot_unexplained")
        if metrics.get("event_sequence_gap"):
            reasons.append("event_sequence_gap")
        if metrics.get("artifact_verification_regression_critical"):
            reasons.append("artifact_verification_regression_critical")
        completion_rate = metrics.get("completion_rate")
        if completion_rate is not None and float(completion_rate) < float(baseline_completion_rate) - 0.02:
            reasons.append("completion_rate_regression")
        latency_ms = metrics.get("p95_latency_ms")
        if latency_ms is not None and baseline_p95_latency_ms > 0 and float(latency_ms) > float(baseline_p95_latency_ms) * 1.25:
            reasons.append("p95_latency_regression")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped

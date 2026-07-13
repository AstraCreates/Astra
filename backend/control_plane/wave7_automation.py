"""Wave 7 rollout automation and drill harness.

Bridges real run outcomes into rollout evidence so staged rollout decisions can
advance or halt without a human manually copying metrics around.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable, Optional

from backend.control_plane.models import RolloutCampaign, RolloutEvidence
from backend.control_plane.wave7_rollout import evaluate_rollout_campaign, record_rollout_evidence

DEFAULT_BASELINE_COMPLETION_RATE = 0.95
DEFAULT_BASELINE_P95_LATENCY_MS = 1000.0
AUTOMATED_FEATURES: tuple[str, ...] = (
    "control_plane_v2",
    "event_stream_v2",
    "model_gateway_v2",
    "research_engine_v2",
    "brain_v2",
)
TERMINAL_SESSION_STATUSES = {"done", "error", "failed", "killed", "cancelled", "stalled", "stopped"}
_HALT_PROBE_FLAGS: dict[str, dict[str, Any]] = {
    "tenant_leak_probe_failed": {"tenant_leak_probe_failed": True},
    "approval_digest_mismatch": {"approval_digest_mismatch": True},
    "duplicate_external_effect_receipt": {"duplicate_external_effect_receipt": True},
    "budget_overshoot_unexplained": {"budget_overshoot_unexplained": True},
    "event_sequence_gap": {"event_sequence_gap": True},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _p95_ms(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values if value is not None)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return round(float(ordered[index]), 2)


def _feature_assigned(meta: dict[str, Any], feature: str) -> bool:
    assignment = meta.get("feature_assignment")
    if isinstance(assignment, dict):
        return bool(assignment.get(feature))
    if feature == "control_plane_v2":
        return str(meta.get("engine") or "").strip().lower() == "temporal"
    return False


def _artifact_regression_present(state: dict[str, Any]) -> bool:
    completion_audit = state.get("completion_audit") or {}
    if completion_audit.get("status") == "incomplete" or completion_audit.get("ok") is False:
        return True
    for verification in state.get("artifact_verifications") or []:
        status = str((verification or {}).get("status") or "").strip().lower()
        if status in {"blocked", "missing", "weak"}:
            return True
    return False


def collect_rollout_metrics(
    *,
    feature: str,
    sessions: Optional[list[dict[str, Any]]] = None,
    load_state: Any | None = None,
    load_meta: Any | None = None,
) -> dict[str, Any]:
    from backend.core.session_store import get_session_meta, list_sessions
    from backend.workflow_state import load_session_state

    session_rows = list(sessions if sessions is not None else list_sessions(limit=500))
    state_loader = load_state or load_session_state
    meta_loader = load_meta or get_session_meta

    evaluated_runs = 0
    successful_runs = 0
    latency_samples_ms: list[float] = []
    artifact_regression_critical = False
    recent_run_ids: list[str] = []

    for row in session_rows:
        run_id = str(row.get("session_id") or row.get("id") or "").strip()
        if not run_id:
            continue
        meta = meta_loader(run_id) or {}
        if str(meta.get("kind") or "").strip().lower() == "shadow":
            continue
        if not _feature_assigned(meta, feature):
            continue
        state = state_loader(run_id) or {}
        session_status = str((state.get("status") or meta.get("status") or "")).strip().lower()
        if session_status not in TERMINAL_SESSION_STATUSES:
            continue

        evaluated_runs += 1
        recent_run_ids.append(run_id)
        if session_status == "done" and not _artifact_regression_present(state):
            successful_runs += 1
        artifact_regression_critical = artifact_regression_critical or _artifact_regression_present(state)

        created_at = _parse_timestamp(meta.get("created_at"))
        completed_at = _parse_timestamp(meta.get("completed_at"))
        if created_at is not None and completed_at is not None and completed_at >= created_at:
            latency_samples_ms.append((completed_at - created_at).total_seconds() * 1000.0)

    completion_rate = round(successful_runs / evaluated_runs, 4) if evaluated_runs else None
    p95_latency_ms = _p95_ms(latency_samples_ms)
    return {
        "feature": feature,
        "evaluated_runs": evaluated_runs,
        "successful_runs": successful_runs,
        "completion_rate": completion_rate,
        "p95_latency_ms": p95_latency_ms,
        "artifact_verification_regression_critical": artifact_regression_critical,
        "recent_run_ids": recent_run_ids[-25:],
    }


def _build_metrics_summary(metrics: dict[str, Any]) -> str:
    evaluated = int(metrics.get("evaluated_runs") or 0)
    completion_rate = metrics.get("completion_rate")
    p95_latency_ms = metrics.get("p95_latency_ms")
    artifact_regression = bool(metrics.get("artifact_verification_regression_critical"))
    completion_text = "n/a" if completion_rate is None else f"{float(completion_rate) * 100:.1f}%"
    latency_text = "n/a" if p95_latency_ms is None else f"{float(p95_latency_ms):.0f}ms"
    return (
        f"Automated rollout metrics sampled {evaluated} run(s): "
        f"completion={completion_text}, p95={latency_text}, "
        f"artifact_regression_critical={'yes' if artifact_regression else 'no'}."
    )


def run_rollout_automation_tick(
    *,
    feature: str,
    baseline_completion_rate: float = DEFAULT_BASELINE_COMPLETION_RATE,
    baseline_p95_latency_ms: float = DEFAULT_BASELINE_P95_LATENCY_MS,
    campaign_repo: Any | None = None,
    evidence_repo: Any | None = None,
    retirement_repo: Any | None = None,
    sessions: Optional[list[dict[str, Any]]] = None,
    load_state: Any | None = None,
    load_meta: Any | None = None,
) -> dict[str, Any]:
    from backend.control_plane.fakes import (
        FakeLegacyRetirementCheckRepository,
        FakeRolloutCampaignRepository,
        FakeRolloutEvidenceRepository,
    )
    from backend.control_plane.supabase_repositories import (
        SupabaseLegacyRetirementCheckRepository,
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    campaign_repo = campaign_repo or SupabaseRolloutCampaignRepository()
    evidence_repo = evidence_repo or SupabaseRolloutEvidenceRepository()
    retirement_repo = retirement_repo or SupabaseLegacyRetirementCheckRepository()
    if isinstance(campaign_repo, FakeRolloutCampaignRepository) and evidence_repo is None:
        evidence_repo = FakeRolloutEvidenceRepository()
    if isinstance(campaign_repo, FakeRolloutCampaignRepository) and retirement_repo is None:
        retirement_repo = FakeLegacyRetirementCheckRepository()

    campaign = campaign_repo.get_active(feature)
    if campaign is None:
        return {"ok": False, "reason": "no_active_campaign", "feature": feature}

    metrics = collect_rollout_metrics(
        feature=feature,
        sessions=sessions,
        load_state=load_state,
        load_meta=load_meta,
    )
    evidence = record_rollout_evidence(
        campaign_id=campaign.id,
        kind="live_run",
        stage=campaign.stage,
        passed=not bool(metrics.get("artifact_verification_regression_critical")),
        summary=_build_metrics_summary(metrics),
        metrics=metrics,
        evidence_repo=evidence_repo,
        run_id=(metrics.get("recent_run_ids") or [None])[-1],
    )
    evaluation = evaluate_rollout_campaign(
        feature=feature,
        baseline_completion_rate=baseline_completion_rate,
        baseline_p95_latency_ms=baseline_p95_latency_ms,
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
    )
    return {
        "ok": True,
        "feature": feature,
        "campaign_id": campaign.id,
        "stage": campaign.stage,
        "evidence_id": evidence.id,
        "metrics": metrics,
        "evaluation": evaluation,
    }


def run_all_rollout_automation_ticks(
    *,
    features: tuple[str, ...] = AUTOMATED_FEATURES,
    baseline_completion_rate: float = DEFAULT_BASELINE_COMPLETION_RATE,
    baseline_p95_latency_ms: float = DEFAULT_BASELINE_P95_LATENCY_MS,
) -> dict[str, Any]:
    results = []
    for feature in features:
        try:
            results.append(
                run_rollout_automation_tick(
                    feature=feature,
                    baseline_completion_rate=baseline_completion_rate,
                    baseline_p95_latency_ms=baseline_p95_latency_ms,
                )
            )
        except Exception as exc:
            results.append({"ok": False, "feature": feature, "reason": str(exc)})
    return {"ok": True, "results": results}


def run_canary_halt_drills(
    *,
    feature: str,
    campaign_repo: Any | None = None,
    evidence_repo: Any | None = None,
    baseline_completion_rate: float = DEFAULT_BASELINE_COMPLETION_RATE,
    baseline_p95_latency_ms: float = DEFAULT_BASELINE_P95_LATENCY_MS,
) -> dict[str, Any]:
    from backend.control_plane.supabase_repositories import (
        SupabaseRolloutCampaignRepository,
        SupabaseRolloutEvidenceRepository,
    )

    campaign_repo = campaign_repo or SupabaseRolloutCampaignRepository()
    evidence_repo = evidence_repo or SupabaseRolloutEvidenceRepository()
    campaign: RolloutCampaign | None = campaign_repo.get_active(feature)
    if campaign is None:
        return {"ok": False, "reason": "no_active_campaign", "feature": feature}

    drill_records: list[RolloutEvidence] = []
    for key, flags in _HALT_PROBE_FLAGS.items():
        drill_records.append(
            record_rollout_evidence(
                campaign_id=campaign.id,
                kind="halt_probe",
                stage=campaign.stage,
                passed=False,
                summary=f"Canary drill triggered {key}",
                metrics=dict(flags),
                evidence_repo=evidence_repo,
            )
        )
    evaluation = evaluate_rollout_campaign(
        feature=feature,
        baseline_completion_rate=baseline_completion_rate,
        baseline_p95_latency_ms=baseline_p95_latency_ms,
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
    )
    return {
        "ok": True,
        "feature": feature,
        "campaign_id": campaign.id,
        "drills": [
            {"evidence_id": record.id, "summary": record.summary, "metrics": record.metrics}
            for record in drill_records
        ],
        "evaluation": evaluation,
    }

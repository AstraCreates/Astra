from datetime import datetime, timedelta, timezone

from backend.control_plane.fakes import (
    FakeLegacyRetirementCheckRepository,
    FakeRolloutCampaignRepository,
    FakeRolloutEvidenceRepository,
)
from backend.control_plane.models import RolloutCampaign
from backend.control_plane.wave7_rollout import (
    evaluate_legacy_retirement,
    evaluate_rollout_campaign,
    get_rollout_percentage,
    mark_rollout_rolled_back,
    record_rollout_evidence,
    start_rollout_campaign,
)


def test_start_rollout_campaign_sets_active_stage_defaults():
    repo = FakeRolloutCampaignRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        campaign_repo=repo,
    )

    assert campaign.status == "active"
    assert campaign.stage == "internal_fixture"
    assert campaign.required_sample_size > 0
    assert repo.get_active("control_plane_v2").id == campaign.id


def test_get_rollout_percentage_prefers_active_campaign_stage():
    repo = FakeRolloutCampaignRepository()
    repo.create(
        RolloutCampaign(
            id="campaign_1",
            feature="control_plane_v2",
            stage="pct_5",
            status="active",
            created_at=datetime.now(timezone.utc),
        )
    )

    assert get_rollout_percentage("control_plane_v2", default_percent=50, campaign_repo=repo) == 5


def test_evaluate_rollout_campaign_advances_when_observation_and_samples_met():
    campaign_repo = FakeRolloutCampaignRepository()
    evidence_repo = FakeRolloutEvidenceRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        stage="internal_fixture",
        required_sample_size=2,
        campaign_repo=campaign_repo,
    )
    campaign_repo.update(
        campaign.id,
        {"last_stage_changed_at": datetime.now(timezone.utc) - timedelta(hours=25)},
    )
    record_rollout_evidence(
        campaign_id=campaign.id,
        kind="fixture",
        stage="internal_fixture",
        passed=True,
        summary="fixture ok",
        evidence_repo=evidence_repo,
    )
    record_rollout_evidence(
        campaign_id=campaign.id,
        kind="chaos",
        stage="internal_fixture",
        passed=True,
        summary="chaos ok",
        evidence_repo=evidence_repo,
    )

    result = evaluate_rollout_campaign(
        feature="control_plane_v2",
        baseline_completion_rate=0.95,
        baseline_p95_latency_ms=1000,
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
    )

    assert result["ok"] is True
    assert result["advanced_to"] == "internal_live"
    assert campaign_repo.get_active("control_plane_v2").stage == "internal_live"


def test_evaluate_rollout_campaign_halts_on_critical_probe():
    campaign_repo = FakeRolloutCampaignRepository()
    evidence_repo = FakeRolloutEvidenceRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        campaign_repo=campaign_repo,
    )
    record_rollout_evidence(
        campaign_id=campaign.id,
        kind="halt_probe",
        stage=campaign.stage,
        passed=False,
        summary="tenant leak",
        metrics={"tenant_leak_probe_failed": True},
        evidence_repo=evidence_repo,
    )

    result = evaluate_rollout_campaign(
        feature="control_plane_v2",
        baseline_completion_rate=0.95,
        baseline_p95_latency_ms=1000,
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
    )

    assert result["status"] == "halted"
    assert "tenant_leak_probe_failed" in result["halt_reasons"]


def test_mark_rollout_rolled_back_marks_campaign_inactive():
    repo = FakeRolloutCampaignRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        campaign_repo=repo,
    )

    result = mark_rollout_rolled_back(
        feature="control_plane_v2",
        reason="manual rollback drill",
        campaign_repo=repo,
    )

    assert result["ok"] is True
    assert repo.update(campaign.id, {}).status == "rolled_back"


def test_evaluate_legacy_retirement_blocks_until_all_proofs_exist():
    repo = FakeLegacyRetirementCheckRepository()
    check = evaluate_legacy_retirement(
        feature="control_plane_v2",
        temporal_run_count=900,
        clean_days=20,
        restart_chaos_passed=True,
        parity_discrepancies_open=0,
        rollback_drill_passed=True,
        archival_snapshots_exported=False,
        retirement_repo=repo,
    )

    assert check.status == "blocked"


def test_evaluate_legacy_retirement_marks_ready_when_requirements_met():
    repo = FakeLegacyRetirementCheckRepository()
    check = evaluate_legacy_retirement(
        feature="control_plane_v2",
        temporal_run_count=1000,
        clean_days=10,
        restart_chaos_passed=True,
        parity_discrepancies_open=0,
        rollback_drill_passed=True,
        archival_snapshots_exported=True,
        retirement_repo=repo,
    )

    assert check.status == "ready"
    assert repo.get("control_plane_v2").status == "ready"

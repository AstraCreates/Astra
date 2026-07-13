from datetime import datetime, timedelta, timezone

from backend.control_plane.fakes import (
    FakeRolloutCampaignRepository,
    FakeRolloutEvidenceRepository,
)
from backend.control_plane.wave7_automation import (
    collect_rollout_metrics,
    run_canary_halt_drills,
    run_rollout_automation_tick,
)
from backend.control_plane.wave7_rollout import start_rollout_campaign


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_collect_rollout_metrics_tracks_completion_latency_and_artifact_regressions():
    now = datetime.now(timezone.utc)
    sessions = [
        {"session_id": "run_ok"},
        {"session_id": "run_bad"},
        {"session_id": "run_other"},
    ]
    metas = {
        "run_ok": {
            "engine": "temporal",
            "kind": "",
            "created_at": _iso(now - timedelta(minutes=10)),
            "completed_at": _iso(now - timedelta(minutes=5)),
            "feature_assignment": {"control_plane_v2": True},
        },
        "run_bad": {
            "engine": "temporal",
            "kind": "",
            "created_at": _iso(now - timedelta(minutes=8)),
            "completed_at": _iso(now - timedelta(minutes=1)),
            "feature_assignment": {"control_plane_v2": True},
        },
        "run_other": {
            "engine": "legacy",
            "kind": "",
            "created_at": _iso(now - timedelta(minutes=8)),
            "completed_at": _iso(now - timedelta(minutes=1)),
            "feature_assignment": {"control_plane_v2": False},
        },
    }
    states = {
        "run_ok": {
            "status": "done",
            "completion_audit": {"ok": True, "status": "complete"},
            "artifact_verifications": [{"status": "passed"}],
        },
        "run_bad": {
            "status": "stalled",
            "completion_audit": {"ok": False, "status": "incomplete"},
            "artifact_verifications": [{"status": "blocked"}],
        },
        "run_other": {
            "status": "done",
            "completion_audit": {"ok": True, "status": "complete"},
            "artifact_verifications": [{"status": "passed"}],
        },
    }

    metrics = collect_rollout_metrics(
        feature="control_plane_v2",
        sessions=sessions,
        load_meta=lambda run_id: metas[run_id],
        load_state=lambda run_id: states[run_id],
    )

    assert metrics["evaluated_runs"] == 2
    assert metrics["successful_runs"] == 1
    assert metrics["completion_rate"] == 0.5
    assert metrics["p95_latency_ms"] == 420000.0
    assert metrics["artifact_verification_regression_critical"] is True


def test_run_rollout_automation_tick_records_metrics_and_halts_on_regression():
    now = datetime.now(timezone.utc)
    campaign_repo = FakeRolloutCampaignRepository()
    evidence_repo = FakeRolloutEvidenceRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        campaign_repo=campaign_repo,
    )
    campaign_repo.update(
        campaign.id,
        {"last_stage_changed_at": now - timedelta(hours=25)},
    )
    sessions = [{"session_id": "run_fail"}]
    metas = {
        "run_fail": {
            "engine": "temporal",
            "kind": "",
            "created_at": _iso(now - timedelta(minutes=6)),
            "completed_at": _iso(now),
            "feature_assignment": {"control_plane_v2": True},
        }
    }
    states = {
        "run_fail": {
            "status": "stalled",
            "completion_audit": {"ok": False, "status": "incomplete"},
            "artifact_verifications": [{"status": "blocked"}],
        }
    }

    result = run_rollout_automation_tick(
        feature="control_plane_v2",
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
        sessions=sessions,
        load_meta=lambda run_id: metas[run_id],
        load_state=lambda run_id: states[run_id],
    )

    assert result["ok"] is True
    assert result["evaluation"]["status"] == "halted"
    assert "artifact_verification_regression_critical" in result["evaluation"]["halt_reasons"]


def test_run_canary_halt_drills_records_all_required_probe_types():
    campaign_repo = FakeRolloutCampaignRepository()
    evidence_repo = FakeRolloutEvidenceRepository()
    campaign = start_rollout_campaign(
        feature="control_plane_v2",
        campaign_repo=campaign_repo,
    )

    result = run_canary_halt_drills(
        feature="control_plane_v2",
        campaign_repo=campaign_repo,
        evidence_repo=evidence_repo,
    )

    assert result["ok"] is True
    reasons = set(result["evaluation"]["halt_reasons"])
    assert {
        "tenant_leak_probe_failed",
        "approval_digest_mismatch",
        "duplicate_external_effect_receipt",
        "budget_overshoot_unexplained",
        "event_sequence_gap",
    }.issubset(reasons)
    assert len(evidence_repo.list_for_campaign(campaign.id)) == 5

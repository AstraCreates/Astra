from backend.control_plane.fakes import (
    FakeLegacyRetirementCheckRepository,
    FakeRolloutCampaignRepository,
)
from backend.control_plane.models import LegacyRetirementCheck, RolloutCampaign
from backend.control_plane.wave7_readiness import build_wave7_readiness_report


def test_wave7_readiness_reports_live_evidence_missing(monkeypatch):
    monkeypatch.setattr(
        "backend.control_plane.wave7_readiness.rollout_status_snapshot",
        lambda: {"campaigns": {}, "legacy_retirement": {}},
    )
    monkeypatch.setattr(
        "backend.control_plane.wave7_readiness.build_legacy_retirement_manifest",
        lambda: {"ok": True, "ready_for_delete_last": False, "items": [{"key": "x", "retirement_ready": False}]},
    )

    report = build_wave7_readiness_report()

    assert report["complete"] is False
    by_key = {check["key"]: check for check in report["checks"]}
    assert by_key["live_rollout_evidence"]["status"] == "needs_live_evidence"
    assert by_key["legacy_delete_last_readiness"]["status"] == "needs_live_evidence"


def test_wave7_readiness_reports_complete_only_with_campaign_and_retirement_ready(monkeypatch):
    monkeypatch.setattr(
        "backend.control_plane.wave7_readiness.rollout_status_snapshot",
        lambda: {
            "campaigns": {"control_plane_v2": {"status": "completed"}},
            "legacy_retirement": {"control_plane_v2": {"status": "ready"}},
        },
    )
    monkeypatch.setattr(
        "backend.control_plane.wave7_readiness.build_legacy_retirement_manifest",
        lambda: {"ok": True, "ready_for_delete_last": True, "items": [{"key": "x", "retirement_ready": True}]},
    )

    report = build_wave7_readiness_report()

    assert report["complete"] is True

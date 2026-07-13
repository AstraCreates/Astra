from backend.control_plane.fakes import FakeShadowComparisonRepository
from backend.control_plane.temporal.shadow_compare import compare_run_snapshots, persist_shadow_comparison


def test_compare_run_snapshots_passes_when_shadow_is_ordered_subset_and_artifacts_match():
    result = compare_run_snapshots(
        run_id="run_1",
        legacy_status="succeeded",
        shadow_status="succeeded",
        legacy_events=[
            {"event_type": "run.created"},
            {"event_type": "run_started"},
            {"event_type": "run.observed"},
            {"event_type": "run_completed"},
        ],
        shadow_events=[
            {"event_type": "run_started"},
            {"event_type": "run.observed"},
            {"event_type": "run_completed"},
        ],
        legacy_artifacts=[{"key": "brief", "content_hash": "abc123", "verification_status": "passed"}],
        shadow_artifacts=[{"key": "brief", "content_hash": "abc123", "verification_status": "passed"}],
        legacy_cost_usd=1.0,
        shadow_cost_usd=1.1,
    )

    assert result.passed is True
    assert result.discrepancies == []


def test_compare_run_snapshots_records_structural_mismatches():
    result = compare_run_snapshots(
        run_id="run_2",
        legacy_status="succeeded",
        shadow_status="failed",
        legacy_events=[{"event_type": "run_started"}, {"event_type": "run_completed"}],
        shadow_events=[{"event_type": "run_started"}, {"event_type": "run_failed"}, {"event_type": "run_completed"}],
        legacy_artifacts=[{"key": "brief", "content_hash": "abc123"}],
        shadow_artifacts=[{"key": "brief", "content_hash": "xyz999"}],
        legacy_cost_usd=1.0,
        shadow_cost_usd=2.0,
    )

    categories = {item["category"] for item in result.discrepancies}
    assert result.passed is False
    assert "terminal_status_mismatch" in categories
    assert "event_order_subset_mismatch" in categories
    assert "artifact_hash_mismatch" in categories
    assert "cost_tolerance_exceeded" in categories


def test_persist_shadow_comparison_records_result():
    repo = FakeShadowComparisonRepository()
    result = compare_run_snapshots(
        run_id="run_3",
        legacy_status="succeeded",
        shadow_status="succeeded",
        legacy_events=[],
        shadow_events=[],
        legacy_artifacts=[],
        shadow_artifacts=[],
    )

    stored = persist_shadow_comparison(
        repository=repo,
        run_id="run_3",
        comparison_type="temporal_shell_vs_legacy",
        result=result,
    )

    assert stored.run_id == "run_3"
    assert stored.passed is True
    assert repo.list_for_run("run_3")[0].comparison_type == "temporal_shell_vs_legacy"

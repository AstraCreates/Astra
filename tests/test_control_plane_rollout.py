from pathlib import Path

import pytest

from backend.control_plane.rollout import assign_run_features, get_run_feature_assignment


def test_same_org_run_pair_is_deterministic(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 50)

    first = assign_run_features("org_1", "run_1")
    second = assign_run_features("org_1", "run_1")
    assert first == second


def test_different_run_ids_can_land_in_different_buckets(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 50)

    results = {assign_run_features("org_1", f"run_{i}")["control_plane_v2"] for i in range(40)}
    # Not all-or-nothing per org: some runs land true, some false at 40 samples / 50%.
    assert results == {True, False}


def test_rollout_percent_zero_never_assigns_true(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 0)

    for i in range(30):
        assert assign_run_features("org_1", f"run_{i}")["control_plane_v2"] is False


def test_rollout_percent_hundred_always_assigns_true(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 100)

    for i in range(30):
        assert assign_run_features("org_1", f"run_{i}")["control_plane_v2"] is True


def test_circuit_breaker_disables_a_feature_even_at_full_rollout(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 100)
    monkeypatch.setattr("backend.runtime.circuit_breaker.is_disabled", lambda feature: feature == "control_plane_v2")

    assert assign_run_features("org_1", "run_1")["control_plane_v2"] is False


def test_engine_reflects_control_plane_v2_resolution(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", False)
    assert assign_run_features("org_1", "run_1")["engine"] == "legacy"

    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 100)
    assert assign_run_features("org_1", "run_1")["engine"] == "temporal"


def test_temporal_shadow_is_independent_of_engine(monkeypatch):
    # Legacy engine (control_plane_v2 off) but still selected for shadow comparison.
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", False)
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 5)
    monkeypatch.setattr("backend.control_plane.rollout._bucket", lambda *_args: 0)

    result = assign_run_features("org_1", "run_1", founder_id="founder_1", plan="beta")
    assert result["engine"] == "legacy"
    assert result["temporal_shadow"] is True


def test_temporal_shadow_zero_percent_never_selects():
    result = assign_run_features("org_1", "run_1", founder_id="founder_1", plan="beta")
    assert result["temporal_shadow"] is False


def test_temporal_shadow_requires_internal_or_beta_eligibility(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 5)
    monkeypatch.setattr("backend.control_plane.rollout._bucket", lambda *_args: 0)

    result = assign_run_features("org_1", "run_1", founder_id="founder_1", plan="starter")
    assert result["temporal_shadow"] is False


def test_temporal_shadow_accepts_platform_admins(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 5)
    monkeypatch.setattr("backend.config.settings.astra_platform_admins", "founder_1")
    monkeypatch.setattr("backend.control_plane.rollout._bucket", lambda *_args: 0)

    result = assign_run_features("org_1", "run_1", founder_id="founder_1", plan="starter")
    assert result["temporal_shadow"] is True


def test_temporal_shadow_accepts_beta_allowlist(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 5)
    monkeypatch.setattr("backend.config.settings.astra_beta_allowlist", "Founder@One.com")
    monkeypatch.setattr("backend.control_plane.rollout._bucket", lambda *_args: 0)

    result = assign_run_features("org_1", "run_1", founder_id="google_founder_one_com", plan="starter")
    assert result["temporal_shadow"] is True


def test_temporal_shadow_percent_is_hard_capped_at_five(monkeypatch):
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 100)
    monkeypatch.setattr("backend.control_plane.rollout._bucket", lambda *_args: 6)

    result = assign_run_features("org_1", "run_1", founder_id="founder_1", plan="beta")
    assert result["temporal_shadow"] is False


def test_get_run_feature_assignment_reads_persisted_value_not_recomputed(tmp_path: Path, monkeypatch):
    """The whole point of persisting: a rollout_percent change after dispatch
    must not change what an in-flight run resolves to."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.core.session_store import merge_session_meta

    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", True)
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2_rollout_percent", 100)
    original = assign_run_features("org_1", "run_persisted")
    assert original["engine"] == "temporal"

    merge_session_meta("run_persisted", feature_assignment=original, engine=original["engine"])

    # Config changes after dispatch -- a fresh assign_run_features() call
    # would now resolve differently, but the persisted run must not move.
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", False)
    assert assign_run_features("org_1", "run_persisted")["engine"] == "legacy"  # fresh call really would differ

    stuck = get_run_feature_assignment("run_persisted")
    assert stuck["engine"] == "temporal"
    assert stuck == original


def test_get_run_feature_assignment_falls_back_when_never_persisted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.config.settings.astra_control_plane_v2", False)

    result = get_run_feature_assignment("run_never_dispatched", org_id="org_1")
    assert result["engine"] == "legacy"

from backend.control_plane.rollout import assign_run_features


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
    monkeypatch.setattr("backend.config.settings.astra_temporal_shadow_percent", 100)

    result = assign_run_features("org_1", "run_1")
    assert result["engine"] == "legacy"
    assert result["temporal_shadow"] is True


def test_temporal_shadow_zero_percent_never_selects():
    result = assign_run_features("org_1", "run_1")
    assert result["temporal_shadow"] is False

from backend.control_plane.anomalies import _mirror_rollout_evidence


def test_wave7_anomaly_bridge_records_halt_probe_and_evaluates(monkeypatch):
    calls = {"record": [], "evaluate": []}

    monkeypatch.setattr(
        "backend.control_plane.wave7_rollout.rollout_status_snapshot",
        lambda: {
            "campaigns": {
                "control_plane_v2": {
                    "id": "campaign_1",
                    "feature": "control_plane_v2",
                    "stage": "pct_1",
                }
            }
        },
    )
    monkeypatch.setattr(
        "backend.control_plane.wave7_rollout.record_rollout_evidence",
        lambda **kwargs: calls["record"].append(kwargs),
    )
    monkeypatch.setattr(
        "backend.control_plane.wave7_rollout.evaluate_rollout_campaign",
        lambda **kwargs: calls["evaluate"].append(kwargs),
    )

    _mirror_rollout_evidence({
        "key": "approval_mismatch",
        "run_id": "run_1",
        "payload": {"approval_id": "ap_1"},
    })

    assert len(calls["record"]) == 1
    assert calls["record"][0]["kind"] == "halt_probe"
    assert calls["record"][0]["metrics"]["approval_digest_mismatch"] is True
    assert len(calls["evaluate"]) == 1


def test_wave7_anomaly_bridge_ignores_unknown_keys(monkeypatch):
    monkeypatch.setattr(
        "backend.control_plane.wave7_rollout.rollout_status_snapshot",
        lambda: {"campaigns": {"control_plane_v2": {"id": "campaign_1", "feature": "control_plane_v2", "stage": "pct_1"}}},
    )
    called = {"record": False}
    monkeypatch.setattr(
        "backend.control_plane.wave7_rollout.record_rollout_evidence",
        lambda **kwargs: called.__setitem__("record", True),
    )

    _mirror_rollout_evidence({"key": "something_else", "payload": {}})

    assert called["record"] is False

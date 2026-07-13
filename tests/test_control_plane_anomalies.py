import threading
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from backend.control_plane.anomalies import anomaly_metrics, list_anomalies, record_anomaly
from backend.control_plane.budget import BudgetReservationService
from backend.control_plane.fakes import (
    FakeApprovalRequestRepository,
    FakeBudgetReservationRepository,
    FakeRunEventRepository,
)
from backend.control_plane.models import ApprovalRequest, BudgetReservation, RunEvent


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_record_anomaly_tracks_metrics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    record_anomaly("receipt_collision", run_id="run_1", payload={"idempotency_key": "k1"})
    record_anomaly("approval_mismatch", run_id="run_2", payload={"approval_id": "ap_1"})

    metrics = anomaly_metrics()
    listed = list_anomalies(limit=10)

    assert metrics["control_plane_anomalies_total"] == 2
    assert metrics["receipt_collision_alerts"] == 1
    assert metrics["approval_mismatch_alerts"] == 1
    assert listed["events"][0]["key"] == "approval_mismatch"


def test_fake_approval_consume_records_mismatch_anomaly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = FakeApprovalRequestRepository()
    repo.create(ApprovalRequest(id="ap1", run_id="run_1", gate_key="gate", action_digest="digest_good", policy_version="v1"))

    with pytest.raises(ValueError, match="digest mismatch"):
        repo.consume("ap1", expected_action_digest="digest_bad", expected_policy_version="v1")

    assert anomaly_metrics()["approval_mismatch_alerts"] == 1


def test_fake_event_repo_records_sequence_gap_anomaly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = FakeRunEventRepository()
    repo._events["run_gap"] = [  # type: ignore[attr-defined]
        RunEvent(run_id="run_gap", sequence=0, event_type="run.created", payload={}, created_at=datetime.now(timezone.utc)),
        RunEvent(run_id="run_gap", sequence=2, event_type="run.started", payload={}, created_at=datetime.now(timezone.utc)),
    ]

    listed = repo.list_since("run_gap", 0)

    assert len(listed) == 2
    assert anomaly_metrics()["event_sequence_gap_alerts"] == 1


def test_budget_commit_records_overshoot_anomaly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = FakeBudgetReservationRepository()
    service = BudgetReservationService(repo)
    reservation = BudgetReservation(
        id="res_1",
        run_id="run_1",
        step_id="step_1",
        estimated_max_usd=1.0,
        status="reserved",
        expires_at=datetime.now(timezone.utc),
    )

    repo.reserve(reservation, founder_id="founder_1", reserved_credits=10)
    monkeypatch.setattr("backend.credits.store._get_lock", lambda _founder_id: _DummyLock())
    monkeypatch.setattr("backend.credits.store._load", lambda _founder_id: {"balance": 100, "total_used": 0, "transactions": []})
    monkeypatch.setattr("backend.credits.store._init_if_new", lambda _founder_id, data: data)
    monkeypatch.setattr(BudgetReservationService, "_deduct_credits_locked", staticmethod(lambda *_args, **_kwargs: None))

    service.commit("res_1", actual_usd=2.5, founder_id="founder_1")

    assert anomaly_metrics()["budget_overshoot_alerts"] == 1


def test_require_company_access_records_tenant_leak_probe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from backend import tenant_auth

    class _Request:
        headers = {}
        query_params = {}

    monkeypatch.setattr(tenant_auth, "request_user_id", lambda _request: "owner_1")
    monkeypatch.setattr(tenant_auth, "_missing_user_allowed", lambda: False)
    monkeypatch.setattr(tenant_auth, "require_founder_access", lambda *_args, **_kwargs: "owner_1")
    monkeypatch.setattr("backend.core.workspace_store.get_workspace", lambda _company_id: {"founder_id": "owner_2"})

    with pytest.raises(HTTPException, match="another workspace"):
        tenant_auth.require_company_access(_Request(), "owner_1", "company_2")

    assert anomaly_metrics()["tenant_leak_probe_alerts"] == 1

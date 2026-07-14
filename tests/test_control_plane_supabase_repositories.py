from unittest.mock import MagicMock

import pytest

from backend.control_plane.models import Run
from backend.control_plane.supabase_repositories import (
    SupabaseActionRepository,
    SupabaseActionReceiptRepository,
    SupabaseApprovalRequestRepository,
    SupabaseArtifactRepository,
    SupabaseBudgetReservationRepository,
    SupabaseRolloutCampaignRepository,
    SupabaseRunEventRepository,
    SupabaseRunRepository,
    SupabaseRunStepRepository,
    _json_safe_patch,
    durable_append_event,
    durable_create_run,
    durable_create_run_with_event,
)
from backend.control_plane.models import Action, ActionReceipt, ApprovalRequest, Artifact, BudgetReservation, RunStep
from datetime import datetime, timezone


@pytest.fixture
def mock_supabase(mocker):
    mock = MagicMock()
    mocker.patch("backend.db.client.get_supabase", return_value=mock)
    return mock


def _run(**overrides) -> Run:
    defaults = dict(id="run_1", owner_id="f1", org_id="f1", goal="Investigate ICP")
    defaults.update(overrides)
    return Run(**defaults)


def test_run_repository_create_upserts_by_id(mock_supabase):
    SupabaseRunRepository().create(_run())
    mock_supabase.table.assert_called_with("astra_runs")
    upsert_call = mock_supabase.table.return_value.upsert
    upsert_call.assert_called_once()
    args, kwargs = upsert_call.call_args
    assert args[0]["id"] == "run_1"
    assert kwargs["on_conflict"] == "id"


def test_run_repository_get_returns_none_when_missing(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    assert SupabaseRunRepository().get("missing") is None


def test_run_repository_get_maps_row_to_model(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "run_1", "owner_id": "f1", "org_id": "f1", "goal": "g", "status": "running", "next_event_sequence": 3}
    ]
    run = SupabaseRunRepository().get("run_1")
    assert run.id == "run_1"
    assert run.status == "running"
    assert run.next_event_sequence == 3


def test_run_repository_update_status_patches_row(mock_supabase):
    SupabaseRunRepository().update_status("run_1", "failed", error="boom")
    update_call = mock_supabase.table.return_value.update
    update_call.assert_called_once_with({"status": "failed", "error": "boom"})


def test_run_event_repository_append_calls_atomic_rpc(mock_supabase):
    mock_supabase.rpc.return_value.execute.return_value.data = 5
    sequence = SupabaseRunEventRepository().append("run_1", "agent_done", {"agent": "design"})
    assert sequence == 5
    mock_supabase.rpc.assert_called_once_with(
        "astra_append_run_event",
        {"p_run_id": "run_1", "p_event_type": "agent_done", "p_payload": {"agent": "design"}},
    )


def test_run_event_repository_list_since_maps_rows(mock_supabase):
    (mock_supabase.table.return_value.select.return_value.eq.return_value
     .gte.return_value.order.return_value.execute.return_value.data) = [
        {"run_id": "run_1", "sequence": 0, "event_type": "agent_start", "payload": {}},
        {"run_id": "run_1", "sequence": 1, "event_type": "agent_done", "payload": {}},
    ]
    events = SupabaseRunEventRepository().list_since("run_1", after_sequence=0)
    assert [e.sequence for e in events] == [0, 1]


@pytest.mark.asyncio
async def test_durable_create_run_never_raises_on_failure(mock_supabase):
    mock_supabase.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("network down")
    await durable_create_run(_run())  # must not raise


@pytest.mark.asyncio
async def test_durable_create_run_with_event_calls_transactional_rpc(mock_supabase):
    mock_supabase.rpc.return_value.execute.return_value.data = 1

    await durable_create_run_with_event(_run(), payload={"type": "run.created"})

    mock_supabase.rpc.assert_called_once_with(
        "astra_create_run_with_event",
        {
            "p_run": _run().model_dump(mode="json", exclude_none=True),
            "p_event_type": "run.created",
            "p_event_payload": {"type": "run.created"},
        },
    )


@pytest.mark.asyncio
async def test_durable_append_event_never_raises_on_fk_violation(mock_supabase):
    """The real-world case: astra_run_events has an FK to astra_runs. An
    event for a run that was never durably created (pre-Wave-1 session, or
    durable_create_run failed) must silently no-op, not break the live run."""
    mock_supabase.rpc.return_value.execute.side_effect = RuntimeError("FK violation")
    await durable_append_event("run_never_created", "agent_start", {})  # must not raise


def test_run_step_repository_create_attempt_increments_attempt_number(mock_supabase):
    query = mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value
    query.execute.return_value.data = [{"attempt_number": 2}]
    step = SupabaseRunStepRepository().create_attempt(RunStep(id="s3", run_id="run_1", step_key="build", kind="agent"))
    assert step.attempt_number == 3
    mock_supabase.table.return_value.upsert.assert_called()


def test_json_safe_patch_converts_datetime_to_isoformat_string():
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    safe = _json_safe_patch({"status": "succeeded", "completed_at": now, "heartbeat_at": now})
    assert safe["status"] == "succeeded"
    assert safe["completed_at"] == now.isoformat()
    assert safe["heartbeat_at"] == now.isoformat()


def test_json_safe_patch_leaves_non_datetime_values_untouched():
    assert _json_safe_patch({"status": "failed", "error": "boom", "n": 3}) == {
        "status": "failed", "error": "boom", "n": 3,
    }


def test_run_step_repository_update_fields_serializes_raw_datetime(mock_supabase):
    # Regression test: execution.py's lane-attempt heartbeat/completion path calls
    # update_fields(step.id, {"heartbeat_at": datetime.now(timezone.utc), ...}) directly
    # with a real datetime object -- postgrest's httpx JSON encoder has no datetime
    # support and raised TypeError on every real heartbeat/completion write in prod
    # before _json_safe_patch was wired in (never caught by MagicMock-based tests).
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    SupabaseRunStepRepository().update_fields("s1", {"status": "succeeded", "completed_at": now})
    update_call = mock_supabase.table.return_value.update
    update_call.assert_called_once_with({"status": "succeeded", "completed_at": now.isoformat()})


def test_rollout_campaign_repository_update_serializes_raw_datetime(mock_supabase):
    # Regression test: wave7_rollout.py's evaluate_rollout_campaign sets
    # patch["completed_at"] / patch["last_stage_changed_at"] to a raw datetime.
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    SupabaseRolloutCampaignRepository().update("c1", {"status": "completed", "completed_at": now})
    update_call = mock_supabase.table.return_value.update
    update_call.assert_called_once_with({"status": "completed", "completed_at": now.isoformat()})


def test_action_repository_get_by_idempotency_key_reads_matching_row(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "a1", "run_id": "run_1", "tool": "deploy", "canonical_args_hash": "h", "idempotency_key": "idem_1"}
    ]
    action = SupabaseActionRepository().get_by_idempotency_key("idem_1")
    assert action is not None
    assert action.id == "a1"


def test_approval_repository_decide_updates_and_returns_row(mock_supabase):
    table = mock_supabase.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "ap1", "run_id": "run_1", "gate_key": "phase_gate", "action_digest": "d1", "status": "approved"}
    ]
    approval = SupabaseApprovalRequestRepository().decide("ap1", "approved", decided_by="founder_1", note="ok")
    assert approval.status == "approved"
    table.update.assert_called_once()


def test_approval_repository_consume_updates_status_and_consumed_at(mock_supabase):
    table = mock_supabase.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.side_effect = [
        MagicMock(data=[{
            "id": "ap1",
            "run_id": "run_1",
            "gate_key": "phase_gate",
            "action_digest": "d1",
            "policy_version": "v1",
            "status": "approved",
        }]),
        MagicMock(data=[{
            "id": "ap1",
            "run_id": "run_1",
            "gate_key": "phase_gate",
            "action_digest": "d1",
            "policy_version": "v1",
            "status": "consumed",
            "consumed_at": "2026-07-12T00:00:00+00:00",
        }]),
    ]
    approval = SupabaseApprovalRequestRepository().consume(
        "ap1",
        expected_action_digest="d1",
        expected_policy_version="v1",
    )
    assert approval.status == "consumed"
    update_payload = table.update.call_args.args[0]
    assert update_payload["status"] == "consumed"
    assert "consumed_at" in update_payload


def test_artifact_repository_list_for_run_maps_rows(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {"id": "art1", "run_id": "run_1", "key": "deck", "verification_status": "passed", "metadata": {}}
    ]
    artifacts = SupabaseArtifactRepository().list_for_run("run_1")
    assert len(artifacts) == 1
    assert artifacts[0].key == "deck"


def test_action_receipt_repository_round_trips_rows(mock_supabase):
    table = mock_supabase.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "rc1", "action_id": "a1", "idempotency_key": "idem_1", "provider_result": {"ok": True}, "collision_status": "none"}
    ]
    repo = SupabaseActionReceiptRepository()
    receipt = repo.create(ActionReceipt(id="rc1", action_id="a1", idempotency_key="idem_1", provider_result={"ok": True}))
    assert receipt.id == "rc1"
    assert repo.get_by_action_id("a1").id == "rc1"
    assert repo.get_by_idempotency_key("idem_1").id == "rc1"
    repo.update_collision_status("rc1", "detected")
    assert table.update.call_args.args[0] == {"collision_status": "detected"}


def test_budget_reservation_repository_persists_reservation_and_ledger(mock_supabase):
    reservation = BudgetReservation(
        id="res1",
        run_id="run_1",
        estimated_max_usd=1.5,
        expires_at=datetime.now(timezone.utc),
    )
    repo = SupabaseBudgetReservationRepository()
    repo.reserve(reservation, founder_id="founder_1", reserved_credits=3000, markup=10.0)
    assert mock_supabase.table.call_args_list[0].args[0] == "astra_budget_reservations"
    assert mock_supabase.table.call_args_list[1].args[0] == "astra_budget_reservation_ledgers"


def test_budget_reservation_repository_sum_reserved_credits_filters_to_reserved_rows(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"reservation_id": "r1", "reserved_credits": 100, "astra_budget_reservations": {"status": "reserved"}},
        {"reservation_id": "r2", "reserved_credits": 90, "astra_budget_reservations": {"status": "released"}},
        {"reservation_id": "r3", "reserved_credits": 80, "astra_budget_reservations": {"status": "reserved"}},
    ]
    total = SupabaseBudgetReservationRepository().sum_reserved_credits("founder_1", exclude_reservation_id="r3")
    assert total == 100

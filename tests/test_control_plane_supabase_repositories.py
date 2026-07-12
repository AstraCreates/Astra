from unittest.mock import MagicMock

import pytest

from backend.control_plane.models import Run
from backend.control_plane.supabase_repositories import (
    SupabaseRunEventRepository,
    SupabaseRunRepository,
    durable_append_event,
    durable_create_run,
)


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
async def test_durable_append_event_never_raises_on_fk_violation(mock_supabase):
    """The real-world case: astra_run_events has an FK to astra_runs. An
    event for a run that was never durably created (pre-Wave-1 session, or
    durable_create_run failed) must silently no-op, not break the live run."""
    mock_supabase.rpc.return_value.execute.side_effect = RuntimeError("FK violation")
    await durable_append_event("run_never_created", "agent_start", {})  # must not raise

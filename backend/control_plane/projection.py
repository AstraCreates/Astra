from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from backend.control_plane.supabase_repositories import (
    SupabaseActionRepository,
    SupabaseApprovalRequestRepository,
    SupabaseArtifactRepository,
    SupabaseBudgetReservationRepository,
    SupabaseRunEventRepository,
    SupabaseRunRepository,
    SupabaseRunStepRepository,
)


async def get_run_snapshot(run_id: str) -> dict[str, Any]:
    run_repo = SupabaseRunRepository()
    step_repo = SupabaseRunStepRepository()
    approval_repo = SupabaseApprovalRequestRepository()
    artifact_repo = SupabaseArtifactRepository()
    reservation_repo = SupabaseBudgetReservationRepository()

    run = await asyncio.to_thread(run_repo.get, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    steps = await asyncio.to_thread(_list_steps_for_run, run_id)
    approvals = await asyncio.to_thread(_list_approvals_for_run, run_id)
    artifacts = await asyncio.to_thread(artifact_repo.list_for_run, run_id)
    reservations = await asyncio.to_thread(_list_reservations_for_run, run_id)

    return {
        "run": run.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in steps],
        "approvals": [approval.model_dump(mode="json") for approval in approvals],
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        "budget": [reservation.model_dump(mode="json") for reservation in reservations],
        "engine": run.engine,
    }


async def list_run_events(run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
    repo = SupabaseRunEventRepository()
    events = await asyncio.to_thread(repo.list_since, run_id, after_sequence)
    filtered = [event for event in events if event.sequence > after_sequence]
    return [event.model_dump(mode="json") for event in filtered]


def _list_steps_for_run(run_id: str):
    from backend.db.client import get_supabase
    from backend.control_plane.supabase_repositories import _row_to_step

    rows = (
        get_supabase().table("astra_run_steps")
        .select("*")
        .eq("run_id", run_id)
        .order("started_at")
        .order("attempt_number")
        .execute()
        .data
    )
    return [_row_to_step(row) for row in rows]


def _list_approvals_for_run(run_id: str):
    from backend.db.client import get_supabase
    from backend.control_plane.supabase_repositories import _row_to_approval

    rows = (
        get_supabase().table("astra_approval_requests")
        .select("*")
        .eq("run_id", run_id)
        .order("created_at")
        .order("revision")
        .execute()
        .data
    )
    return [_row_to_approval(row) for row in rows]


def _list_reservations_for_run(run_id: str):
    from backend.db.client import get_supabase
    from backend.control_plane.supabase_repositories import _row_to_reservation

    rows = (
        get_supabase().table("astra_budget_reservations")
        .select("*")
        .eq("run_id", run_id)
        .order("created_at")
        .execute()
        .data
    )
    return [_row_to_reservation(row) for row in rows]

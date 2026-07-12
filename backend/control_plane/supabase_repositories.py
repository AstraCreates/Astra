"""Real Supabase-backed implementations of the Wave 1 repository interfaces.

Dual-write only: these are called ADDITIVELY alongside the existing
session_store JSONL flow (backend/core/session_store.py) and the existing
run_ledger summary (backend/run_ledger.py), never replacing them. Every
call site wraps these in a best-effort try/except -- a Supabase hiccup must
never break a live run. This is how the durable astra_runs/astra_run_events
tables (applied in supabase/migrations/) actually start filling up; nothing
wrote to them before this.

Matches the same supabase-py call pattern already used in backend/db/client.py
(get_supabase().table(...).execute(), run off the event loop via
asyncio.to_thread since the client is synchronous).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.control_plane.models import Run, RunEvent

logger = logging.getLogger(__name__)


def _row_to_run(row: dict) -> Run:
    return Run(
        id=row["id"],
        owner_id=row["owner_id"],
        org_id=row["org_id"],
        company_id=row.get("company_id"),
        workspace_id=row.get("workspace_id"),
        chapter_id=row.get("chapter_id"),
        parent_run_id=row.get("parent_run_id"),
        goal=row["goal"],
        stack_id=row.get("stack_id"),
        engine=row.get("engine", "legacy"),
        workflow_version=row.get("workflow_version", "v1"),
        status=row.get("status", "queued"),
        next_event_sequence=row.get("next_event_sequence", 0),
        budget_limit_usd=row.get("budget_limit_usd"),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        cancellation_requested_at=row.get("cancellation_requested_at"),
        error=row.get("error"),
        metadata=row.get("metadata") or {},
    )


class SupabaseRunRepository:
    def create(self, run: Run) -> Run:
        from backend.db.client import get_supabase

        payload = run.model_dump(mode="json", exclude_none=True)
        get_supabase().table("astra_runs").upsert(payload, on_conflict="id").execute()
        return run

    def get(self, run_id: str) -> Optional[Run]:
        from backend.db.client import get_supabase

        rows = get_supabase().table("astra_runs").select("*").eq("id", run_id).limit(1).execute().data
        return _row_to_run(rows[0]) if rows else None

    def update_status(self, run_id: str, status: str, *, error: Optional[str] = None) -> None:
        from backend.db.client import get_supabase

        patch: dict = {"status": status}
        if error is not None:
            patch["error"] = error
        get_supabase().table("astra_runs").update(patch).eq("id", run_id).execute()


class SupabaseRunEventRepository:
    def append(self, run_id: str, event_type: str, payload: dict) -> int:
        from backend.db.client import get_supabase

        # astra_append_run_event() locks the astra_runs row and assigns the
        # sequence atomically -- never compute it here. Raises (via
        # postgrest's error surface) if run_id has no matching astra_runs
        # row (FK violation) -- callers must have created the run first via
        # SupabaseRunRepository.create(), and should treat this as
        # best-effort (catch and log, never let it break the live run).
        result = get_supabase().rpc(
            "astra_append_run_event",
            {"p_run_id": run_id, "p_event_type": event_type, "p_payload": payload},
        ).execute()
        return int(result.data)

    def list_since(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        from backend.db.client import get_supabase

        rows = (
            get_supabase().table("astra_run_events")
            .select("*")
            .eq("run_id", run_id)
            .gte("sequence", after_sequence)
            .order("sequence")
            .execute()
            .data
        )
        return [
            RunEvent(
                run_id=row["run_id"], sequence=row["sequence"], event_type=row["event_type"],
                payload=row.get("payload") or {}, created_at=row.get("created_at"),
                published_at=row.get("published_at"),
            )
            for row in rows
        ]


async def durable_create_run(run: Run) -> None:
    """Best-effort, never raises. Call once when a run/session starts."""
    try:
        await asyncio.to_thread(SupabaseRunRepository().create, run)
    except Exception as exc:
        logger.warning("durable_create_run failed for run_id=%s: %s", run.id, exc)


async def durable_append_event(run_id: str, event_type: str, payload: dict) -> None:
    """Best-effort, never raises. Call alongside every backend.core.events.publish()."""
    try:
        await asyncio.to_thread(SupabaseRunEventRepository().append, run_id, event_type, payload)
    except Exception as exc:
        logger.debug("durable_append_event failed for run_id=%s type=%s: %s", run_id, event_type, exc)

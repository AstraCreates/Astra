"""Backfill: map existing legacy sessions into astra_runs, one-for-one,
preserving the existing session_id as astra_runs.id.

NOT executed anywhere automatically -- this module has no import-time side
effects and is not imported by any app-startup path. Run deliberately:

    python -m backend.control_plane.backfill [--dry-run]

Maps backend/core/session_store.py's meta.json shape (register_session())
onto the Run contract. Reads-only against the legacy session store; writes
would go through get_supabase() once a human decides to actually run this
against the real project -- left as a clear TODO rather than wired up, since
this task is scaffolding only, not a live migration.
"""
from __future__ import annotations

import argparse
import logging

from backend.control_plane.models import Run

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "running": "running",
    "loading": "running",
    "done": "succeeded",
    "error": "failed",
    "stalled": "awaiting_approval",
    "killed": "cancelled",
}


def _legacy_status_to_run_status(status: str) -> str:
    return _STATUS_MAP.get(status, "queued")


def build_run_from_session_meta(meta: dict) -> Run:
    """Pure mapping, no I/O -- the part that's actually worth unit testing."""
    return Run(
        id=meta["session_id"],
        owner_id=meta.get("founder_id", ""),
        org_id=meta.get("founder_id", ""),  # legacy sessions have no separate org concept yet
        company_id=meta.get("company_id") or None,
        workspace_id=meta.get("workspace_id") or None,
        chapter_id=meta.get("chapter_id") or None,
        parent_run_id=meta.get("parent_session_id") or None,
        goal=meta.get("goal", ""),
        stack_id=meta.get("stack_id") or None,
        engine="legacy",
        status=_legacy_status_to_run_status(meta.get("status", "")),
        created_at=meta.get("created_at"),
        completed_at=meta.get("completed_at"),
        metadata={"backfilled_from": "session_store", "kind": meta.get("kind", "")},
    )


def iter_legacy_runs(founder_id: str | None = None, limit: int = 100000):
    from backend.core.session_store import get_session_meta, list_sessions

    for entry in list_sessions(founder_id=founder_id, limit=limit):
        meta = get_session_meta(entry["session_id"]) or entry
        yield build_run_from_session_meta(meta)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True,
                         help="Print what would be written without touching Supabase (default: on).")
    parser.add_argument("--apply", action="store_true",
                         help="Actually write to Supabase via get_supabase(). Requires --dry-run to be off.")
    args = parser.parse_args()

    count = 0
    for run in iter_legacy_runs():
        count += 1
        if args.apply:
            # TODO(coordinator, deliberate step): insert into astra_runs via
            # backend.db.client.get_supabase() once migrations 0001-0013 have
            # actually been applied to the real project. Not wired up here on
            # purpose -- this script is reviewed code, not a live migration.
            raise NotImplementedError(
                "backfill --apply is intentionally not wired to a live Supabase write yet; "
                "review build_run_from_session_meta()'s output first, then wire the insert deliberately."
            )
        else:
            logger.info("[dry-run] would backfill run %s (status=%s, owner=%s)", run.id, run.status, run.owner_id)

    logger.info("backfill complete: %d legacy sessions mapped", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

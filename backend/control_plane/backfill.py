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
from collections.abc import Callable, Iterable
from dataclasses import dataclass

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


@dataclass(frozen=True)
class BackfillResult:
    scanned: int
    written: int
    dry_run: bool


def backfill_runs(
    runs: Iterable[Run] | None = None,
    *,
    founder_id: str | None = None,
    limit: int = 100000,
    dry_run: bool = True,
    writer: Callable[[Run], None] | None = None,
) -> BackfillResult:
    planned_runs = runs if runs is not None else iter_legacy_runs(founder_id=founder_id, limit=limit)

    scanned = 0
    written = 0
    if not dry_run and writer is None:
        raise NotImplementedError(
            "backfill apply requires an explicit writer callable; "
            "wire the real Supabase insert deliberately before using --apply."
        )

    for run in planned_runs:
        scanned += 1
        if dry_run:
            logger.info("[dry-run] would backfill run %s (status=%s, owner=%s)", run.id, run.status, run.owner_id)
            continue
        writer(run)
        written += 1
        logger.info("backfilled run %s (status=%s, owner=%s)", run.id, run.status, run.owner_id)

    logger.info(
        "backfill complete: scanned=%d written=%d dry_run=%s",
        scanned,
        written,
        dry_run,
    )
    return BackfillResult(scanned=scanned, written=written, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--founder-id", help="Only backfill sessions for one founder.")
    parser.add_argument("--limit", type=int, default=100000, help="Maximum number of legacy sessions to scan.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write using an injected writer. Without this flag the command is a dry run.",
    )
    args = parser.parse_args()

    backfill_runs(founder_id=args.founder_id, limit=args.limit, dry_run=not args.apply)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

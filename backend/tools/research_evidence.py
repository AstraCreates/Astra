"""Best-effort persistence of research Evidence rows as control-plane
Artifacts (Wave 5.3 — Research Engine V2).

This lets downstream code (and, later, a Temporal activity that wraps deep
research) inspect what evidence backed a research claim without re-running
research. Writing an artifact is entirely optional and non-blocking: any
failure here is swallowed and logged, never raised — a Supabase hiccup must
never take down a research tool call.

Repository selection mirrors the pattern in
backend.control_plane.action_executor.get_default_repo_bundle(): Supabase-
backed when settings.supabase_url/supabase_key are configured, otherwise an
in-memory Fake (dev/test).
"""
import logging
import threading
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_artifact_repo = None
_artifact_repo_lock = threading.Lock()


def _get_artifact_repo():
    global _artifact_repo
    if _artifact_repo is None:
        with _artifact_repo_lock:
            if _artifact_repo is None:
                from backend.config import settings

                if settings.supabase_url and settings.supabase_key:
                    from backend.control_plane.supabase_repositories import (
                        SupabaseArtifactRepository,
                    )

                    _artifact_repo = SupabaseArtifactRepository()
                else:
                    from backend.control_plane.fakes import FakeArtifactRepository

                    _artifact_repo = FakeArtifactRepository()
    return _artifact_repo


def write_evidence_artifact(run_id: Optional[str], step_id: Optional[str], evidence: dict) -> None:
    """Persist one Evidence dict (see research_schema.Evidence) as an
    Artifact row with key=f"evidence:{evidence['evidence_id']}" and
    metadata={"kind": "research_evidence", **evidence}.

    No-op if run_id is falsy — research tool calls don't always have run
    context available today (see web_search.deep_research's optional
    run_id/step_id kwargs; most existing callers don't pass them, and that's
    fine, this is purely additive). Never raises.
    """
    if not run_id:
        return
    evidence_id = (evidence or {}).get("evidence_id") or ""
    if not evidence_id:
        return
    try:
        from backend.control_plane.models import Artifact

        repo = _get_artifact_repo()
        artifact = Artifact(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_id=step_id,
            key=f"evidence:{evidence_id}",
            metadata={"kind": "research_evidence", **evidence},
        )
        repo.upsert(artifact)
    except Exception:
        logger.warning(
            "write_evidence_artifact failed (non-fatal) run_id=%s step_id=%s evidence_id=%s",
            run_id, step_id, evidence_id, exc_info=True,
        )

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
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_artifact_repo = None
_artifact_repo_lock = threading.Lock()


def validate_deep_research(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate tool-produced evidence before any synthesis or artifact write."""
    sources = [item for item in (payload.get("sources") or []) if isinstance(item, Mapping)]
    urls = []
    for source in sources:
        url = str(source.get("url") or source.get("source_url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(url)
    domains = {urlparse(url).netloc.lower() for url in urls}
    structured = payload.get("structured") or {}
    evidence_rows = (structured.get("evidence") if isinstance(structured, Mapping) else None) or payload.get("evidence") or []
    if isinstance(structured, Mapping) and not evidence_rows:
        evidence_rows = [row for item in structured.values() if isinstance(item, Mapping)
                         for row in (item.get("evidence") or []) if isinstance(row, Mapping)]
    search_count = int(payload.get("search_count") or payload.get("queries_run") or 0)
    content = str(payload.get("combined_formatted") or payload.get("formatted") or "").strip()
    gaps: list[str] = []
    if search_count < 1:
        gaps.append("no successful search or fetch call")
    if not urls:
        gaps.append("no usable source URL")
    if not evidence_rows and not content:
        gaps.append("empty evidence payload")
    if any(not item.get("retrieved_at") for item in sources):
        # Browser research may expose retrieval time in structured Evidence;
        # require it somewhere in the returned tool evidence.
        if not any(isinstance(item, Mapping) and item.get("retrieved_at") for item in evidence_rows):
            gaps.append("source retrieval metadata is missing")
    coverage = payload.get("coverage") or {}
    if coverage and coverage.get("ready") is False:
        gaps.extend(str(gap) for gap in coverage.get("gaps") or [] if str(gap) not in gaps)
    return {"ok": not gaps, "gaps": gaps, "source_urls": list(dict.fromkeys(urls)),
            "source_count": len(set(urls)), "domain_count": len(domains),
            "search_count": search_count, "evidence_count": len(evidence_rows),
            "validated_at": datetime.now(timezone.utc).isoformat()}


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

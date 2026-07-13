"""Wave 6.3: ACL-enforced brain retrieval with Graphiti + fallback.

Orchestrates the 6-step flow:
  1. Authorize caller access to company_id
  2. Query Graphiti for candidate record IDs
  3. Recheck every candidate against Supabase ACLs
  4. Fetch canonical source text
  5. Rerank by relevance
  6. Return citations + temporal validity
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from backend.control_plane.repositories import BrainAclRepository, BrainRecordRepository

logger = logging.getLogger(__name__)


class GraphitiClient:
    """Protocol for querying the Graphiti vector graph."""
    def search(self, query: str, top_k: int = 10, company_id: Optional[str] = None) -> dict[str, Any]: ...


def query_brain_authorized(
    company_id: str,
    caller_user_id: str,
    caller_role: str,
    query: str,
    top_k: int = 10,
    brain_record_repo: Optional[BrainRecordRepository] = None,
    brain_acl_repo: Optional[BrainAclRepository] = None,
    graphiti: Optional[GraphitiClient] = None,
) -> list[dict[str, Any]]:
    """Query brain with ACL enforcement: authorize, fetch from Graphiti, recheck ACLs, rerank, return.

    Args:
        company_id: Company scope for the query
        caller_user_id: User making the query
        caller_role: Role of the user (owner, admin, operator, viewer)
        query: Search query string
        top_k: Number of results to return
        brain_record_repo: Optional injected repo for testing
        brain_acl_repo: Optional injected repo for testing
        graphiti: Optional injected client for testing

    Returns:
        List of authorized brain records with metadata, or empty list if unauthorized/no results
    """
    started_at = time.time()

    # Step 1: Authorize caller access to company_id
    if not _authorize_caller(company_id, caller_user_id, caller_role):
        logger.warning(
            "query_brain_authorized: unauthorized user_id=%s role=%s company_id=%s",
            caller_user_id, caller_role, company_id,
        )
        return []

    # Get repo instances (use injected or default fakes)
    if brain_record_repo is None:
        brain_record_repo = _get_brain_record_repository()
    if brain_acl_repo is None:
        brain_acl_repo = _get_brain_acl_repository()
    if graphiti is None:
        graphiti = _get_graphiti_client()

    candidate_ids: list[str] = []
    graphiti_failed = False

    # Step 2: Query Graphiti for candidate record IDs (with fallback on timeout/error)
    try:
        graphiti_result = graphiti.search(query, top_k=top_k, company_id=company_id)
        candidate_ids = graphiti_result.get("record_ids", [])
        logger.info(
            "query_brain_authorized: graphiti returned %d candidates for query=%r company_id=%s",
            len(candidate_ids), query, company_id,
        )
    except Exception as exc:
        graphiti_failed = True
        logger.warning(
            "query_brain_authorized: graphiti search failed (falling back to direct search): %s",
            exc,
        )
        # Step 2b: Fallback to direct Supabase content search
        fallback_records = brain_record_repo.search_content(company_id, query, limit=top_k)
        candidate_ids = [_record_id(record) for record in fallback_records if _record_id(record)]
        logger.info(
            "query_brain_authorized: fallback search returned %d candidates",
            len(candidate_ids),
        )

    if not candidate_ids:
        return []

    # Step 3: Recheck every candidate against Supabase ACLs
    authorized_ids: list[str] = []
    for record_id in candidate_ids:
        try:
            if brain_acl_repo.has_access(record_id, caller_role, caller_user_id):
                authorized_ids.append(record_id)
        except Exception as exc:
            logger.warning(
                "query_brain_authorized: acl check failed for record_id=%s: %s",
                record_id, exc,
            )
            # Fail open on ACL check errors: drop the record (safer than leaking access)
            continue

    logger.info(
        "query_brain_authorized: %d/%d candidates passed acl check",
        len(authorized_ids), len(candidate_ids),
    )

    # Top up from canonical search when the shared graph does not cover all
    # accessible records (for example user- or role-scoped records intentionally
    # excluded from the company-wide graph namespace).
    if len(authorized_ids) < top_k and not graphiti_failed:
        fallback_records = brain_record_repo.search_content(company_id, query, limit=top_k)
        for record in fallback_records:
            record_id = _record_id(record)
            if not record_id or record_id in authorized_ids:
                continue
            try:
                if brain_acl_repo.has_access(record_id, caller_role, caller_user_id):
                    authorized_ids.append(record_id)
            except Exception as exc:
                logger.warning(
                    "query_brain_authorized: acl check failed during top-up for record_id=%s: %s",
                    record_id,
                    exc,
                )
            if len(authorized_ids) >= top_k:
                break

    # Step 4: Fetch canonical source text from Supabase
    records = brain_record_repo.list_by_ids(authorized_ids)

    # Step 5: Rerank by relevance (simple keyword matching for now)
    # TODO(ponytail): replace with learned reranker if performance requires
    ranked = _rerank_by_relevance([_record_to_payload(record) for record in records], query)

    # Step 6: Return citations + temporal validity
    elapsed_ms = (time.time() - started_at) * 1000
    results = [
        {
            "record_id": r.get("id", ""),
            "company_id": r.get("company_id", ""),
            "source": r.get("source", ""),
            "external_id": r.get("external_id", ""),
            "content": r.get("content", ""),
            "confidence": r.get("confidence", 0.8),
            "retrieved_at": r.get("created_at", ""),
            "temporal_validity": _compute_temporal_validity(r),
        }
        for r in ranked[: max(1, min(top_k, 20))]
    ]

    logger.info(
        "query_brain_authorized: returned %d results in %.1fms",
        len(results), elapsed_ms,
    )

    return results


def _authorize_caller(company_id: str, caller_user_id: str, caller_role: str) -> bool:
    """Check if the caller can access this company namespace."""
    if not caller_role or not caller_user_id or not company_id:
        return False
    try:
        from backend.accounts import get_or_create_org
        from backend.core.workspace_store import get_workspace

        workspace = get_workspace(company_id)
        if workspace is None:
            return caller_user_id == company_id

        founder_id = str(workspace.get("founder_id") or "").strip()
        if not founder_id:
            return False
        if caller_user_id == founder_id:
            return True

        org = get_or_create_org(founder_id, founder_id)
        member = (org.get("members") or {}).get(caller_user_id) or {}
        actual_role = "owner" if org.get("owner_id") == caller_user_id else str(member.get("role") or "")
        active = caller_user_id == org.get("owner_id") or str(member.get("status") or "") == "active"
        allowed = {"viewer": 1, "operator": 2, "admin": 3, "owner": 4}
        return bool(active and allowed.get(actual_role, 0) >= allowed["viewer"])
    except Exception:
        logger.warning(
            "query_brain_authorized: company access lookup failed for user_id=%s company_id=%s",
            caller_user_id,
            company_id,
            exc_info=True,
        )
        return False


def _get_brain_record_repository() -> BrainRecordRepository:
    """Lazily load the real or fake brain record repository."""
    try:
        from backend.control_plane.supabase_repositories import SupabaseBrainRecordRepository
        return SupabaseBrainRecordRepository()
    except Exception:
        # Fallback to fake for local dev/test
        from backend.control_plane.fakes import FakeBrainRecordRepository
        return FakeBrainRecordRepository()


def _get_brain_acl_repository() -> BrainAclRepository:
    """Lazily load the real or fake brain ACL repository."""
    try:
        from backend.control_plane.supabase_repositories import SupabaseBrainAclRepository
        return SupabaseBrainAclRepository()
    except Exception:
        # Fallback to fake for local dev/test
        from backend.control_plane.fakes import FakeBrainAclRepository
        return FakeBrainAclRepository()


def _get_graphiti_client() -> GraphitiClient:
    """Lazily load the Graphiti client."""
    try:
        from backend.control_plane.graphiti_adapter import GraphitiBrainClient

        return GraphitiBrainClient()
    except Exception:
        # Fallback to fake for local dev/test
        from backend.control_plane.fakes import FakeGraphitiClient
        return FakeGraphitiClient()


def _rerank_by_relevance(records: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Simple keyword-based rerank: higher score for query term matches in title/content."""
    import re
    import json

    terms = [t.lower() for t in re.findall(r"\b\w{3,}\b", query) if len(t) > 2]
    if not terms:
        return records

    scored = []
    for rec in records:
        title = (rec.get("title") or "").lower()
        raw_content = rec.get("content") or ""
        if isinstance(raw_content, str):
            content = raw_content.lower()
        else:
            content = json.dumps(raw_content, sort_keys=True, default=str).lower()
        score = sum(title.count(t) * 2 for t in terms)  # Title matches count double
        score += sum(content.count(t) for t in terms)
        scored.append((float(score), rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [rec for _, rec in scored]


def _compute_temporal_validity(record: dict[str, Any]) -> str:
    """Compute if this record is fresh, stale, or deprecated.

    Returns: "fresh" | "stale" | "deprecated"
    """
    from datetime import datetime, timezone

    status = str(record.get("status") or "active").lower()
    if status in {"deprecated", "superseded"} or record.get("superseded_by") or record.get("tombstoned_at"):
        return "deprecated"

    created_at = record.get("created_at") or record.get("retrieved_at")
    if not created_at:
        return "fresh"
    try:
        raw = str(created_at).replace("Z", "+00:00")
        created = datetime.fromisoformat(raw)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days
        if age_days >= 90:
            return "stale"
    except Exception:
        pass
    return "fresh"


def _record_to_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    provenance = record.provenance if isinstance(getattr(record, "provenance", None), dict) else {}
    content = provenance.get("content") if isinstance(provenance, dict) else {}
    return {
        "id": getattr(record, "id", ""),
        "company_id": getattr(record, "company_id", ""),
        "source": getattr(record, "source", ""),
        "external_id": getattr(record, "external_id", ""),
        "content": content if content is not None else {},
        "title": str((content or {}).get("title") or ""),
        "created_at": getattr(record, "created_at", ""),
        "tombstoned_at": getattr(record, "tombstoned_at", None),
        "status": "superseded" if (provenance or {}).get("superseded_by") else "active",
        "superseded_by": (provenance or {}).get("superseded_by"),
    }


def _record_id(record: Any) -> str:
    if isinstance(record, dict):
        return str(record.get("id") or "").strip()
    return str(getattr(record, "id", "") or "").strip()

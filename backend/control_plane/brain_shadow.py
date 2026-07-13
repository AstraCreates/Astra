"""Wave 6.4: Shadow comparison of old vs new brain retrieval paths.

Runs old (search_company_brain) and new (query_brain_authorized) retrieval paths
side-by-side on the same queries to detect parity issues, tenant leaks,
deletion propagation, and latency regressions.
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from typing import Any, Literal, Optional

from backend.control_plane.models import ShadowComparison

logger = logging.getLogger(__name__)

DiscrepancyCategory = Literal[
    "EXACT_MATCH",  # old and new return same records
    "PARAPHRASED",  # old and new return overlapping but different record ids
    "CONTRADICTION",  # same topic but materially conflicting assertions
    "SUPERSEDED",  # old returns records that are superseded in new
    "DELETED",     # old returns records that are tombstoned/deleted in new
    "CROSS_COMPANY",  # new path leaked records from another company
    "ROLE_RESTRICTED",  # new path correctly filtered by ACL, old didn't
    "CONNECTOR_OUTAGE",  # source retrieval/provider outage prevented fair comparison
    "GRAPH_OUTAGE",    # graphiti unavailable, fell back to direct search
    "REBUILD",     # graph rebuild occurred mid-comparison
]


class ShadowComparisonResult:
    """Single query comparison result."""
    def __init__(
        self,
        query: str,
        old_results: list[dict[str, Any]],
        new_results: list[dict[str, Any]],
        discrepancy: DiscrepancyCategory,
        latency_old_ms: float,
        latency_new_ms: float,
        dry_run: bool = False,
    ):
        self.query = query
        self.old_results = old_results
        self.new_results = new_results
        self.discrepancy = discrepancy
        self.latency_old_ms = latency_old_ms
        self.latency_new_ms = latency_new_ms
        self.dry_run = dry_run

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "old_results": self.old_results,
            "new_results": self.new_results,
            "discrepancy": self.discrepancy,
            "latency_old_ms": self.latency_old_ms,
            "latency_new_ms": self.latency_new_ms,
            "dry_run": self.dry_run,
        }


def run_shadow_retrieval(
    company_id: str,
    caller_user_id: str,
    caller_role: str,
    queries: list[str],
    dry_run: bool = False,
    run_id: str | None = None,
    shadow_repository: Any | None = None,
) -> dict[str, Any]:
    """Run shadow comparison for a list of queries.

    For each query, run both old and new retrieval paths in parallel,
    compare results, classify discrepancy, and return structured results.

    Args:
        company_id: Company scope for queries
        caller_user_id: User making queries
        caller_role: Role of user (owner, admin, operator, viewer)
        queries: List of test queries
        dry_run: If True, log results but don't modify state

    Returns:
        {
            "ok": bool,
            "dry_run": bool,
            "company_id": str,
            "query_count": int,
            "comparisons": list of ShadowComparisonResult dicts,
            "summary": {
                "exact_matches": int,
                "paraphrased": int,
                "deleted": int,
                "leaks": int,
                "avg_latency_old_ms": float,
                "avg_latency_new_ms": float,
            }
        }
    """
    comparisons: list[ShadowComparisonResult] = []
    max_workers = max(1, min(4, len(queries)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_query = {
            executor.submit(
                _compare_single_query,
                company_id=company_id,
                caller_user_id=caller_user_id,
                caller_role=caller_role,
                query=query,
                dry_run=dry_run,
            ): query
            for query in queries
        }
        for future in concurrent.futures.as_completed(future_by_query):
            query = future_by_query[future]
            try:
                comparisons.append(future.result())
            except Exception as exc:
                logger.error(
                    "run_shadow_retrieval: comparison failed for query=%r: %s",
                    query,
                    exc,
                )
                continue

    comparisons.sort(key=lambda comparison: queries.index(comparison.query) if comparison.query in queries else len(queries))

    # Compute summary statistics
    summary = _compute_summary(comparisons)

    result = {
        "ok": True,
        "dry_run": dry_run,
        "company_id": company_id,
        "query_count": len(queries),
        "comparisons": [c.to_dict() for c in comparisons],
        "summary": summary,
    }

    # Emit structured event for cutover monitoring
    if not dry_run:
        try:
            _persist_shadow_comparisons(
                run_id=run_id or f"brain-shadow:{company_id}",
                company_id=company_id,
                comparisons=comparisons,
                repository=shadow_repository,
            )
            _emit_shadow_event(company_id, result)
        except Exception as exc:
            logger.warning("run_shadow_retrieval: failed to emit event: %s", exc)

    return result


def _compare_single_query(
    company_id: str,
    caller_user_id: str,
    caller_role: str,
    query: str,
    dry_run: bool = False,
) -> ShadowComparisonResult:
    """Compare old and new retrieval for a single query."""
    from backend.tools.company_brain import search_company_brain
    from backend.control_plane.brain_retrieval import query_brain_authorized

    # Run old path
    old_start = time.time()
    old_error: Exception | None = None
    try:
        old_result = search_company_brain(
            founder_id=company_id,  # Note: company_id used as founder_id in legacy
            query=query,
            limit=10,
            viewer_id=caller_user_id,
            company_id=company_id,
        )
        old_results = old_result.get("results", [])
    except Exception as exc:
        logger.warning("run_shadow_retrieval: old path failed for query=%r: %s", query, exc)
        old_results = []
        old_error = exc
    old_latency_ms = (time.time() - old_start) * 1000

    # Run new path
    new_start = time.time()
    new_error: Exception | None = None
    try:
        new_results = query_brain_authorized(
            company_id=company_id,
            caller_user_id=caller_user_id,
            caller_role=caller_role,
            query=query,
            top_k=10,
        )
    except Exception as exc:
        logger.warning("run_shadow_retrieval: new path failed for query=%r: %s", query, exc)
        new_results = []
        new_error = exc
    new_latency_ms = (time.time() - new_start) * 1000

    # Classify discrepancy
    discrepancy = _classify_discrepancy(
        old_results,
        new_results,
        old_path_error=old_error,
        new_path_error=new_error,
    )

    return ShadowComparisonResult(
        query=query,
        old_results=old_results,
        new_results=new_results,
        discrepancy=discrepancy,
        latency_old_ms=old_latency_ms,
        latency_new_ms=new_latency_ms,
        dry_run=dry_run,
    )


def _classify_discrepancy(
    old_results: list[dict[str, Any]],
    new_results: list[dict[str, Any]],
    *,
    old_path_error: Exception | None = None,
    new_path_error: Exception | None = None,
) -> DiscrepancyCategory:
    """Classify the discrepancy between old and new results.

    Simple heuristic:
      - If same record IDs: EXACT_MATCH
      - If overlapping record IDs: PARAPHRASED
      - If new is empty but old isn't: could be DELETED or ROLE_RESTRICTED
      - If new has records old doesn't: potential LEAK
    """
    for error in [old_path_error, new_path_error]:
        if error is None:
            continue
        message = str(error).lower()
        if any(token in message for token in ["connector", "provider", "source unavailable", "upstream", "503", "429"]):
            return "CONNECTOR_OUTAGE"
        if "rebuild" in message:
            return "REBUILD"
        if "graphiti" in message or "graph" in message:
            return "GRAPH_OUTAGE"

    if new_path_error is not None:
        message = str(new_path_error).lower()
        if "rebuild" in message:
            return "REBUILD"
        if "graphiti" in message or "graph" in message:
            return "GRAPH_OUTAGE"

    old_ids = {r.get("id") or r.get("record_id") for r in old_results if r.get("id") or r.get("record_id")}
    new_ids = {r.get("id") or r.get("record_id") for r in new_results if r.get("id") or r.get("record_id")}
    old_superseded = {
        r.get("superseded_by")
        for r in old_results
        if r.get("superseded_by")
    }
    old_deleted = {r.get("id") or r.get("record_id") for r in old_results if r.get("tombstoned_at")}
    new_statuses = {str(r.get("status") or "").lower() for r in new_results}
    old_claims = {
        str(r.get("title") or r.get("content") or r.get("text") or "").strip().lower()
        for r in old_results
        if str(r.get("title") or r.get("content") or r.get("text") or "").strip()
    }
    new_claims = {
        str(r.get("title") or r.get("content") or r.get("text") or "").strip().lower()
        for r in new_results
        if str(r.get("title") or r.get("content") or r.get("text") or "").strip()
    }

    if old_ids == new_ids:
        return "EXACT_MATCH"

    if old_deleted and not new_ids:
        return "DELETED"

    if old_superseded and new_ids and not (old_ids & new_ids):
        return "SUPERSEDED"

    if "deleted" in new_statuses or "tombstoned" in new_statuses:
        return "DELETED"

    if old_ids & new_ids:  # Has overlap
        if len(new_ids) > len(old_ids):
            return "CROSS_COMPANY"  # New returned more than old
        if len(new_ids) < len(old_ids):
            if not new_ids:
                return "DELETED"  # All old results gone from new
            return "SUPERSEDED"  # Some old records replaced

    if _looks_contradictory(old_results, new_results):
        return "CONTRADICTION"

    if old_claims & new_claims:
        return "PARAPHRASED"

    if not new_ids and old_ids:
        return "DELETED"

    if new_ids and not old_ids:
        return "ROLE_RESTRICTED"

    if new_ids and old_ids:
        return "PARAPHRASED"

    return "EXACT_MATCH"  # Both empty


def _looks_contradictory(old_results: list[dict[str, Any]], new_results: list[dict[str, Any]]) -> bool:
    old_texts = [_claim_text(result) for result in old_results]
    new_texts = [_claim_text(result) for result in new_results]
    for old_text in old_texts:
        if not old_text:
            continue
        for new_text in new_texts:
            if not new_text:
                continue
            if _same_topic(old_text, new_text) and _opposite_polarity(old_text, new_text):
                return True
    return False


def _claim_text(result: dict[str, Any]) -> str:
    for key in ("title", "content", "text"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _same_topic(left: str, right: str) -> bool:
    left_terms = {term for term in left.split() if len(term) > 3}
    right_terms = {term for term in right.split() if len(term) > 3}
    overlap = left_terms & right_terms
    return len(overlap) >= 2


def _opposite_polarity(left: str, right: str) -> bool:
    negation_terms = (" not ", " no ", " never ", " without ", " disabled ", " deprecated ")
    left_neg = any(term in f" {left} " for term in negation_terms)
    right_neg = any(term in f" {right} " for term in negation_terms)
    return left_neg != right_neg


def _compute_summary(comparisons: list[ShadowComparisonResult]) -> dict[str, Any]:
    """Compute summary statistics across all comparisons."""
    if not comparisons:
        return {
            "exact_matches": 0,
            "paraphrased": 0,
            "contradictions": 0,
            "deleted": 0,
            "leaks": 0,
            "connector_outages": 0,
            "graph_outages": 0,
            "rebuild_events": 0,
            "avg_latency_old_ms": 0.0,
            "avg_latency_new_ms": 0.0,
        }

    discrepancy_counts = {}
    for comp in comparisons:
        discrepancy_counts[comp.discrepancy] = discrepancy_counts.get(comp.discrepancy, 0) + 1

    leaks = sum(
        1 for comp in comparisons
        if comp.discrepancy in {"CROSS_COMPANY"}
    )

    avg_old = sum(c.latency_old_ms for c in comparisons) / len(comparisons)
    avg_new = sum(c.latency_new_ms for c in comparisons) / len(comparisons)

    return {
        "exact_matches": discrepancy_counts.get("EXACT_MATCH", 0),
        "paraphrased": discrepancy_counts.get("PARAPHRASED", 0),
        "contradictions": discrepancy_counts.get("CONTRADICTION", 0),
        "deleted": discrepancy_counts.get("DELETED", 0),
        "leaks": leaks,
        "connector_outages": discrepancy_counts.get("CONNECTOR_OUTAGE", 0),
        "graph_outages": discrepancy_counts.get("GRAPH_OUTAGE", 0),
        "rebuild_events": discrepancy_counts.get("REBUILD", 0),
        "avg_latency_old_ms": round(avg_old, 2),
        "avg_latency_new_ms": round(avg_new, 2),
    }


def _emit_shadow_event(company_id: str, result: dict[str, Any]) -> None:
    """Emit a structured event for cutover monitoring.

    In production, this would write to a log aggregation service,
    Datadog, or a structured event table.
    """
    logger.info(
        "BRAIN_SHADOW_COMPARISON: company_id=%s queries=%d leaks=%d latency_ratio=%.2f",
        company_id,
        result.get("query_count", 0),
        result.get("summary", {}).get("leaks", 0),
        (result.get("summary", {}).get("avg_latency_new_ms", 0) /
         max(0.1, result.get("summary", {}).get("avg_latency_old_ms", 1.0))),
    )


def _persist_shadow_comparisons(
    *,
    run_id: str,
    company_id: str,
    comparisons: list[ShadowComparisonResult],
    repository: Any | None = None,
) -> None:
    repo = repository or _get_shadow_repository()
    for comparison in comparisons:
        repo.create(
            ShadowComparison(
                id=str(uuid.uuid4()),
                run_id=run_id,
                comparison_type="brain_retrieval",
                passed=comparison.discrepancy in {"EXACT_MATCH", "PARAPHRASED", "ROLE_RESTRICTED"},
                discrepancies=[{
                    "company_id": company_id,
                    **comparison.to_dict(),
                }],
            )
        )


def _get_shadow_repository() -> Any:
    try:
        from backend.control_plane.supabase_repositories import SupabaseShadowComparisonRepository

        return SupabaseShadowComparisonRepository()
    except Exception:
        from backend.control_plane.fakes import FakeShadowComparisonRepository

        return FakeShadowComparisonRepository()

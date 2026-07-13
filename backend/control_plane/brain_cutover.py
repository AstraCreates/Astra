"""Cutover criteria helpers for W6.3-6.4 brain retrieval enforcement.

Validates shadow comparison results against cutover requirements:
  - No tenant leaks (ACL enforcement correct)
  - Correct deletion propagation
  - Accuracy >= 95%
  - P95 latency acceptable
"""
from __future__ import annotations

from typing import Any


def check_no_tenant_leaks(shadow_results: list[dict[str, Any]]) -> bool:
    """Scan all shadow results, confirm no record appears in new_results but not in old_results
    for a cross-company query.

    Tenant leak = new path returning data the old path didn't, violating ACLs.

    Returns: False if any leak detected, True if all clear.
    """
    for result in shadow_results:
        discrepancy = result.get("discrepancy")
        if discrepancy == "CROSS_COMPANY":
            # This is the primary leak indicator
            return False

        # Also check if new returned more records than old without a valid reason
        new_count = len(result.get("new_results", []))
        old_count = len(result.get("old_results", []))

        # If new > old, could indicate a leak (unless it's a valid expansion like PARAPHRASED)
        if new_count > old_count and discrepancy not in {"PARAPHRASED", "ROLE_RESTRICTED"}:
            # Could be a leak; be conservative
            return False

    return True


def check_deletion_propagation(shadow_results: list[dict[str, Any]]) -> bool:
    """Verify that deleted records don't leak through to new results.

    When a record is deleted, it should:
      - Appear in old_results (because old path hasn't seen deletion)
      - NOT appear in new_results (new path filters tombstoned records)

    This check verifies: for DELETED discrepancies, the records that are
    in old but not new should indeed not appear in new (no leaks).

    Returns: False if deleted records leak through, True if all clear.
    """
    for result in shadow_results:
        discrepancy = result.get("discrepancy")

        # For DELETED discrepancy, some records were in old but not new.
        # Check that the NEW results don't contain records that should have been deleted.
        if discrepancy == "DELETED":
            new_ids = {r.get("id") or r.get("record_id") for r in result.get("new_results", [])}
            deleted_old_ids = {
                r.get("id") or r.get("record_id")
                for r in result.get("old_results", [])
                if r.get("tombstoned_at") or str(r.get("status") or "").lower() in {"deleted", "tombstoned"}
            }
            if deleted_old_ids & new_ids:
                return False

    return True


def estimate_accuracy_improvement(shadow_results: list[dict[str, Any]]) -> float:
    """Estimate retrieval accuracy based on discrepancy types.

    Rough heuristic: accuracy = % of EXACT_MATCH cases.
    Cutover requires >= 95%.

    Returns: accuracy as float in [0.0, 1.0]
    """
    if not shadow_results:
        return 0.0

    exact_matches = sum(
        1 for r in shadow_results
        if r.get("discrepancy") == "EXACT_MATCH"
    )

    # Also count PARAPHRASED as "acceptable" (overlapping records)
    acceptable = exact_matches + sum(
        1 for r in shadow_results
        if r.get("discrepancy") in {"PARAPHRASED", "ROLE_RESTRICTED"}
    )

    accuracy = acceptable / len(shadow_results)
    return round(accuracy, 3)


def estimate_p95_latency(shadow_results: list[dict[str, Any]]) -> tuple[float, float]:
    """Estimate p95 latency for old and new paths.

    Returns: (old_p95_ms, new_p95_ms)
    Cutover allows new_p95_ms <= old_p95_ms * 1.2 (20% slower acceptable).
    """
    if not shadow_results:
        return (0.0, 0.0)

    old_latencies = sorted([r.get("latency_old_ms", 0) for r in shadow_results])
    new_latencies = sorted([r.get("latency_new_ms", 0) for r in shadow_results])

    # Compute 95th percentile
    idx = max(0, int(len(old_latencies) * 0.95) - 1)
    old_p95 = float(old_latencies[idx]) if old_latencies else 0.0
    new_p95 = float(new_latencies[idx]) if new_latencies else 0.0

    return (round(old_p95, 2), round(new_p95, 2))


def evaluate_cutover_readiness(shadow_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate if the new retrieval path is ready for cutover.

    Cutover gates:
      1. No tenant leaks (check_no_tenant_leaks)
      2. Correct deletion propagation (check_deletion_propagation)
      3. Accuracy >= 95% (estimate_accuracy_improvement)
      4. P95 latency acceptable (estimate_p95_latency)

    Returns:
        {
            "ready_for_cutover": bool,
            "no_tenant_leaks": bool,
            "deletion_propagation_correct": bool,
            "accuracy": float,
            "accuracy_acceptable": bool,
            "p95_latency_old_ms": float,
            "p95_latency_new_ms": float,
            "latency_acceptable": bool,
            "blockers": list[str],
        }
    """
    no_leaks = check_no_tenant_leaks(shadow_results)
    deletion_ok = check_deletion_propagation(shadow_results)
    accuracy = estimate_accuracy_improvement(shadow_results)
    old_p95, new_p95 = estimate_p95_latency(shadow_results)
    contradiction_count = sum(1 for result in shadow_results if result.get("discrepancy") == "CONTRADICTION")
    connector_outage_count = sum(1 for result in shadow_results if result.get("discrepancy") == "CONNECTOR_OUTAGE")
    graph_outage_count = sum(1 for result in shadow_results if result.get("discrepancy") == "GRAPH_OUTAGE")
    rebuild_count = sum(1 for result in shadow_results if result.get("discrepancy") == "REBUILD")

    accuracy_ok = accuracy >= 0.95
    latency_ok = new_p95 <= old_p95 * 1.2 if old_p95 > 0 else True
    contradictions_ok = contradiction_count == 0
    outages_ok = connector_outage_count == 0 and graph_outage_count == 0 and rebuild_count == 0

    blockers = []
    if not no_leaks:
        blockers.append("Tenant leaks detected in shadow results")
    if not deletion_ok:
        blockers.append("Deleted records still visible in new path")
    if not contradictions_ok:
        blockers.append(f"Contradictions detected in {contradiction_count} shadow comparisons")
    if connector_outage_count:
        blockers.append(f"Connector outages affected {connector_outage_count} shadow comparisons")
    if graph_outage_count:
        blockers.append(f"Graph outages affected {graph_outage_count} shadow comparisons")
    if rebuild_count:
        blockers.append(f"Graph rebuilds affected {rebuild_count} shadow comparisons")
    if not accuracy_ok:
        blockers.append(f"Accuracy {accuracy:.1%} below 95% threshold")
    if not latency_ok:
        blockers.append(
            f"P95 latency {new_p95}ms exceeds threshold {old_p95 * 1.2:.1f}ms "
            f"({(new_p95 / old_p95):.1%} of old)"
        )

    ready = no_leaks and deletion_ok and contradictions_ok and outages_ok and accuracy_ok and latency_ok

    return {
        "ready_for_cutover": ready,
        "no_tenant_leaks": no_leaks,
        "deletion_propagation_correct": deletion_ok,
        "contradictions_detected": contradiction_count,
        "connector_outages": connector_outage_count,
        "graph_outages": graph_outage_count,
        "rebuild_events": rebuild_count,
        "accuracy": round(accuracy, 3),
        "accuracy_acceptable": accuracy_ok,
        "p95_latency_old_ms": old_p95,
        "p95_latency_new_ms": new_p95,
        "latency_acceptable": latency_ok,
        "blockers": blockers,
    }

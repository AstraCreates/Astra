"""Cross-company pattern learning.

Astra runs the same stack templates for many founders. The run ledger
(backend/run_ledger.py) already records outcome/artifact counts for every
session across every founder — this just aggregates that existing data per
stack template so a company can see how it's doing relative to every other
company that ran the same playbook. No founder identity is ever exposed,
only aggregate counts.
"""
from __future__ import annotations

from typing import Any

from backend import run_ledger


def _percentile_rank(value: float, others: list[float]) -> int:
    if not others:
        return 50
    below_or_equal = sum(1 for o in others if o <= value)
    return round(100 * below_or_equal / len(others))


def get_stack_benchmark(stack_id: str, session_id: str = "") -> dict[str, Any]:
    """Aggregate outcome/artifact stats across every completed company run of
    this stack template, plus this session's percentile if given."""
    if not stack_id:
        return {"available": False, "sample_size": 0}

    rows = [
        r for r in run_ledger.list_runs(limit=1000)
        if r.get("stack_id") == stack_id and r.get("status") == "done"
    ]
    if len(rows) < 2:
        return {"available": False, "sample_size": len(rows)}

    outcome_counts = [int(r.get("outcome_count") or 0) for r in rows]
    artifact_counts = [int(r.get("artifact_count") or 0) for r in rows]

    result: dict[str, Any] = {
        "available": True,
        "sample_size": len(rows),
        "avg_outcome_count": round(sum(outcome_counts) / len(outcome_counts), 1),
        "avg_artifact_count": round(sum(artifact_counts) / len(artifact_counts), 1),
    }

    if session_id:
        this_row = next((r for r in rows if r.get("session_id") == session_id), None)
        if this_row is not None:
            own = int(this_row.get("outcome_count") or 0)
            others = [c for r, c in zip(rows, outcome_counts) if r.get("session_id") != session_id]
            result["your_outcome_count"] = own
            result["percentile"] = _percentile_rank(own, others)

    return result


def get_session_benchmark(session_id: str) -> dict[str, Any]:
    """Look up a session's stack and benchmark it against every other
    company's completed run of that same stack."""
    run = run_ledger.get_run(session_id)
    if not run or not run.get("stack_id"):
        return {"available": False, "sample_size": 0}
    return get_stack_benchmark(run["stack_id"], session_id=session_id)

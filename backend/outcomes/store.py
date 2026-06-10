"""Durable outcome ledger per company.

Tracks: produced (tool output), approved (founder OK), executed (sent/deployed),
verified (external confirmation). Each outcome: {id, company_id, run_id, agent,
metric, value, unit, state, evidence, credits_cost, at}.

Deduped by content hash — prevents draft/duplicate inflation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _root() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "outcomes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: str, fallback: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", "."})[:120] or fallback


def _ledger_path(founder_id: str, company_id: str | None = None) -> Path:
    safe_founder = _safe_id(founder_id, "founder")
    resolved_company = company_id or founder_id
    if resolved_company == founder_id:
        return _root() / f"{safe_founder}.jsonl"
    company_dir = _root() / safe_founder
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"{_safe_id(resolved_company, 'company')}.jsonl"


def _content_hash(outcome: dict) -> str:
    """Hash outcome content for dedup (excludes id/state/timestamp)."""
    key_data = {
        "company_id": outcome.get("company_id"),
        "run_id": outcome.get("run_id"),
        "agent": outcome.get("agent"),
        "metric": outcome.get("metric"),
        "value": outcome.get("value"),
        "evidence": outcome.get("evidence"),
    }
    return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()


def add_outcome(
    founder_id: str,
    company_id: str | None = None,
    *,
    run_id: str,
    agent: str,
    metric: str,
    value: int | float,
    unit: str,
    evidence: dict | None = None,
    credits_cost: float = 0.0,
) -> dict[str, Any]:
    """Append outcome to ledger. Auto-dedup by content hash."""
    resolved_company = company_id or founder_id
    outcome = {
        "id": str(uuid.uuid4()),
        "company_id": resolved_company,
        "run_id": run_id,
        "agent": agent,
        "metric": metric,
        "value": value,
        "unit": unit,
        "state": "produced",
        "evidence": evidence or {},
        "credits_cost": float(credits_cost),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        content_hash = _content_hash(outcome)

        # Check for existing identical outcome (dedup)
        if path.exists():
            try:
                for line in path.read_text().splitlines():
                    if not line.strip():
                        continue
                    existing = json.loads(line)
                    if _content_hash(existing) == content_hash:
                        logger.debug("Outcome deduped: %s", content_hash)
                        return existing
            except Exception as e:
                logger.warning("Dedup check failed: %s", e)

        # Append new outcome
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(outcome, separators=(",", ":")) + "\n")

        return outcome


def list_outcomes(
    founder_id: str,
    company_id: str | None = None,
    since: str | None = None,
    states: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load outcomes from ledger, optionally filtered by state + time."""
    resolved_company = company_id or founder_id
    results = []

    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        if not path.exists():
            return []

        try:
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                outcome = json.loads(line)

                if since and outcome.get("at", "") < since:
                    continue
                if states and outcome.get("state") not in states:
                    continue

                results.append(outcome)
        except Exception as e:
            logger.warning("Failed to load outcomes: %s", e)

    return results


def update_outcome_state(
    founder_id: str,
    outcome_id: str,
    new_state: str,
    company_id: str | None = None,
) -> bool:
    """Transition outcome state: produced → approved → executed → verified."""
    resolved_company = company_id or founder_id
    valid_states = {"produced", "approved", "executed", "verified"}
    if new_state not in valid_states:
        return False

    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        if not path.exists():
            return False

        try:
            lines = path.read_text().splitlines()
            updated = False
            with path.open("w") as f:
                for line in lines:
                    if not line.strip():
                        continue
                    outcome = json.loads(line)
                    if outcome.get("id") == outcome_id:
                        outcome["state"] = new_state
                        updated = True
                    f.write(json.dumps(outcome, separators=(",", ":")) + "\n")
            return updated
        except Exception as e:
            logger.warning("Failed to update outcome: %s", e)
            return False


def weekly_rollup(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate this week's outcomes by metric + state."""
    import datetime

    resolved_company = company_id or founder_id
    now = datetime.datetime.utcnow()
    week_ago = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    outcomes = list_outcomes(founder_id, resolved_company, since=week_ago)

    by_metric: dict[str, dict] = {}
    total_credits = 0.0
    for outcome in outcomes:
        metric = outcome.get("metric", "unknown")
        state = outcome.get("state", "produced")
        value = outcome.get("value", 0)
        credits = outcome.get("credits_cost", 0.0)

        if metric not in by_metric:
            by_metric[metric] = {
                "produced": 0,
                "approved": 0,
                "executed": 0,
                "verified": 0,
                "total_value": 0,
                "total_credits": 0.0,
            }

        by_metric[metric][state] += 1
        by_metric[metric]["total_value"] += value
        by_metric[metric]["total_credits"] += credits
        total_credits += credits

    return {
        "week_start": week_ago,
        "week_end": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by_metric": by_metric,
        "total_outcomes": len(outcomes),
        "total_credits_cost": total_credits,
    }

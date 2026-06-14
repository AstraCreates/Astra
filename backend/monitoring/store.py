"""Time-series monitoring ledger per company.

Append-only JSONL of every health check Astra runs on a shipped artifact after the
build — "deploy still 200?", "research still fresh?" — plus auto-heal records. Mirrors
backend/outcomes/store.py (lock + atomic append). This is what powers the "Live"
dashboard and the per-day auto-heal cap.

Record: {id, company_id, session_id, artifact_key, artifact_type, check_type,
         status: up|stale|down|unknown, metadata, checked_at}
check_type is "health" for routine checks and "auto_heal" for repair attempts.
"""
from __future__ import annotations

import datetime
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
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "monitoring"
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


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def add_monitoring_check(
    founder_id: str,
    company_id: str | None = None,
    *,
    session_id: str = "",
    artifact_key: str,
    artifact_type: str = "",
    check_type: str = "health",
    status: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one monitoring check to the company's time-series."""
    resolved_company = company_id or founder_id
    record = {
        "id": str(uuid.uuid4()),
        "company_id": resolved_company,
        "session_id": session_id,
        "artifact_key": artifact_key,
        "artifact_type": artifact_type,
        "check_type": check_type,
        "status": status,
        "metadata": metadata or {},
        "checked_at": _now_iso(),
    }
    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def list_monitoring_checks(
    founder_id: str,
    company_id: str | None = None,
    artifact_key: str | None = None,
    check_type: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Load checks, optionally filtered by artifact, type, or time."""
    resolved_company = company_id or founder_id
    rows: list[dict[str, Any]] = []
    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        if not path.exists():
            return []
        try:
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if artifact_key and rec.get("artifact_key") != artifact_key:
                    continue
                if check_type and rec.get("check_type") != check_type:
                    continue
                if since and rec.get("checked_at", "") < since:
                    continue
                rows.append(rec)
        except Exception as exc:
            logger.warning("Failed to load monitoring checks: %s", exc)
    return rows


def latest_status(founder_id: str, company_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Most recent health check per artifact_key."""
    latest: dict[str, dict[str, Any]] = {}
    for rec in list_monitoring_checks(founder_id, company_id, check_type="health"):
        latest[rec.get("artifact_key", "")] = rec  # later rows overwrite
    return latest


def uptime_percent(founder_id: str, company_id: str, artifact_key: str, days: int = 7) -> float:
    """Share of health checks in the window where the artifact was 'up'."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    checks = [c for c in list_monitoring_checks(founder_id, company_id, artifact_key=artifact_key,
                                                check_type="health", since=since)]
    if not checks:
        return 100.0
    up = sum(1 for c in checks if c.get("status") == "up")
    return round(100.0 * up / len(checks), 1)


def heals_today(founder_id: str, company_id: str | None = None) -> int:
    """Count of auto-heal attempts since midnight UTC (for the per-day cap)."""
    midnight = datetime.datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")
    return len(list_monitoring_checks(founder_id, company_id, check_type="auto_heal", since=midnight))


def last_content_check(founder_id: str, company_id: str, artifact_key: str) -> str | None:
    """ISO timestamp of the most recent content-freshness check for an artifact."""
    rows = [c for c in list_monitoring_checks(founder_id, company_id, artifact_key=artifact_key,
                                              check_type="health")
            if (c.get("metadata") or {}).get("kind") == "content"]
    return rows[-1]["checked_at"] if rows else None

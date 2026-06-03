"""
PII Vault — SSN data lifecycle management.

Two guarantees enforced here:
  1. SSN patterns are scrubbed from every string before it enters any
     data pipeline (vector DB, storage mirror, genome).
  2. When SSN data is received via the LLC filing flow a receipt is
     logged (no actual value stored) and a 30-day deletion deadline is
     set. A daily background job calls purge_expired() to enforce it.

Usage:
    from backend.core.pii_vault import scrub, scrub_dict, record_ssn_receipt, purge_expired
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

RETENTION_DAYS = 30
_RETENTION_SECONDS = RETENTION_DAYS * 86_400

# Matches US SSN formats: 123-45-6789 | 123 45 6789 | 123456789
SSN_PATTERN = re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")

# In-memory receipt log: "{founder_id}:ssn" → receipt dict.
# In production replace with a Redis hash with a 30-day TTL so receipts
# survive restarts and are shared across replicas.
_receipts: dict[str, dict[str, Any]] = {}


# ── Scrubbing ─────────────────────────────────────────────────────────────────

def scrub(text: str) -> str:
    """Replace every SSN-like pattern in *text* with [SSN REDACTED]."""
    if not text:
        return text
    result, n = SSN_PATTERN.subn("[SSN REDACTED]", text)
    if n:
        logger.warning(
            "[PII_GUARD] Scrubbed %d SSN pattern(s) from text before pipeline write.", n
        )
    return result


def scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub SSN patterns from all string values in a dict."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = scrub(v)
        elif isinstance(v, dict):
            out[k] = scrub_dict(v)
        elif isinstance(v, list):
            out[k] = [
                scrub(i) if isinstance(i, str)
                else scrub_dict(i) if isinstance(i, dict)
                else i
                for i in v
            ]
        else:
            out[k] = v
    return out


# ── Receipt logging ───────────────────────────────────────────────────────────

def record_ssn_receipt(founder_id: str, session_id: Optional[str] = None) -> None:
    """
    Record that SSN data was received for this founder.

    The actual SSN value is NEVER stored — only the metadata required
    for the 30-day deletion audit trail.
    """
    key = f"{founder_id}:ssn"
    received_at = time.time()
    delete_by = received_at + _RETENTION_SECONDS
    _receipts[key] = {
        "founder_id": founder_id,
        "pii_type": "ssn",
        "session_id": session_id,
        "received_at": received_at,
        "delete_by": delete_by,
    }
    logger.info(
        "[PII_VAULT] SSN receipt recorded — founder: %s  session: %s  "
        "deletion deadline: %s",
        founder_id[:8] + "...",
        (session_id or "unknown")[:12],
        time.strftime("%Y-%m-%d", time.gmtime(delete_by)),
    )


# ── 30-day purge ──────────────────────────────────────────────────────────────

def purge_expired() -> int:
    """
    Delete all PII receipts that have passed their 30-day retention window.

    Called once per day by the startup background scheduler in main.py.
    Returns the number of records purged.
    """
    now = time.time()
    expired = [k for k, v in _receipts.items() if v["delete_by"] <= now]
    for k in expired:
        rec = _receipts.pop(k)
        age_days = round((now - rec["received_at"]) / 86_400, 1)
        logger.info(
            "[PII_VAULT] Purged expired SSN receipt — founder: %s  "
            "age: %s days  session: %s",
            rec["founder_id"][:8] + "...",
            age_days,
            (rec.get("session_id") or "unknown")[:12],
        )
    if expired:
        logger.info("[PII_VAULT] Daily purge complete — %d record(s) deleted.", len(expired))
    return len(expired)


# ── Audit ─────────────────────────────────────────────────────────────────────

def get_audit_report() -> list[dict[str, Any]]:
    """
    Return active PII receipts for compliance review.
    Contains only metadata — no actual PII values.
    """
    now = time.time()
    return [
        {
            **v,
            "days_remaining": max(0.0, round((v["delete_by"] - now) / 86_400, 1)),
            "overdue": v["delete_by"] < now,
        }
        for v in _receipts.values()
    ]

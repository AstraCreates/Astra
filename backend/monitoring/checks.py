"""Per-artifact health checks for the live-monitoring scheduler.

Built on the durable receipts a company already has: each receipt knows the artifact,
its owning agent, the originating session, and (for deployables) the live URL captured
at build time. We re-probe URLs for liveness and treat content artifacts as stale once
they age past a freshness window.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.stacks import probe_live_url
from backend.verification.receipt_store import list_receipts

logger = logging.getLogger(__name__)

CONTENT_FRESHNESS_DAYS = 7


def artifacts_for_company(founder_id: str, company_id: str) -> list[dict[str, Any]]:
    """Latest receipt per artifact — the set we monitor for this company."""
    return list_receipts(founder_id, company_id, latest_only=True)


def _receipt_url(receipt: dict[str, Any]) -> str:
    return ((receipt.get("evidence") or {}).get("executable") or {}).get("url") or ""


def _age_days(iso_ts: str) -> float:
    try:
        then = datetime.datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ")
        return (datetime.datetime.utcnow() - then).total_seconds() / 86400.0
    except Exception:
        return 0.0


async def check_artifact(record: dict[str, Any], *, do_content: bool) -> dict[str, Any] | None:
    """Run the appropriate health check for one artifact receipt record.

    Returns {status, kind, metadata} or None when this artifact isn't due this tick
    (e.g. a content artifact on an hourly URL-only tick). status ∈ up|stale|down|unknown.
    """
    receipt = record.get("receipt") or {}
    url = _receipt_url(receipt)
    if url:
        ev = await probe_live_url(url)
        status = "up" if ev.get("ok") else "down"
        return {"status": status, "kind": "url",
                "metadata": {"kind": "url", "url": url, "http_status": ev.get("status"),
                             "bytes": ev.get("bytes"), "error": ev.get("error")}}
    # Content/doc artifact: freshness only, and only on the (weekly) content tick.
    if not do_content:
        return None
    checked_at = receipt.get("checked_at") or record.get("at") or ""
    age = _age_days(checked_at)
    status = "stale" if age > CONTENT_FRESHNESS_DAYS else "up"
    return {"status": status, "kind": "content",
            "metadata": {"kind": "content", "age_days": round(age, 1),
                         "threshold_days": CONTENT_FRESHNESS_DAYS}}

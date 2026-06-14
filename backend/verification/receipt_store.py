"""Durable, shareable verification receipts per company.

Every verified artifact gets a receipt — a compact, human-readable trail of what was
checked, the results, and the evidence ("fetched 200, cites 14 sources, passed 3/3
levels after 1 attempt"). This is the trust wedge: competitors output a wall of text
and hope; Astra keeps the proof and can show it.

Append-only JSONL per company, mirroring backend/outcomes/store.py: latest write for a
given (session_id, artifact_key) wins on read (we keep history, collapse on list).
"""
from __future__ import annotations

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
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "receipts"
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


def add_receipt(
    founder_id: str,
    company_id: str | None = None,
    *,
    session_id: str,
    artifact_key: str,
    artifact_title: str = "",
    agent: str = "",
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Append a verification receipt for one artifact."""
    resolved_company = company_id or founder_id
    record = {
        "id": str(uuid.uuid4()),
        "company_id": resolved_company,
        "session_id": session_id,
        "artifact_key": artifact_key,
        "artifact_title": artifact_title,
        "agent": agent,
        "status": receipt.get("status", "passed"),
        "receipt": receipt,
        "at": _now_iso(),
    }
    with _lock:
        path = _ledger_path(founder_id, resolved_company)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def list_receipts(
    founder_id: str,
    company_id: str | None = None,
    session_id: str | None = None,
    artifact_key: str | None = None,
    latest_only: bool = True,
) -> list[dict[str, Any]]:
    """Load receipts, optionally filtered. With latest_only, collapse to the most
    recent receipt per (session_id, artifact_key)."""
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
                if session_id and rec.get("session_id") != session_id:
                    continue
                if artifact_key and rec.get("artifact_key") != artifact_key:
                    continue
                rows.append(rec)
        except Exception as exc:
            logger.warning("Failed to load receipts: %s", exc)
            return []
    if not latest_only:
        return rows
    collapsed: dict[tuple, dict] = {}
    for rec in rows:
        collapsed[(rec.get("session_id"), rec.get("artifact_key"))] = rec  # later overwrites
    return list(collapsed.values())

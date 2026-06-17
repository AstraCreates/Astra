"""Durable structured company Genome store.

Each company's Genome lives at:
  $OBSIDIAN_VAULT/company_genomes/{founder_id}/{company_id}.json

Structure: sections (profile, stage, industry, product, ICP, personas, positioning,
offers, pricing, competitors, brand_voice, objections, metrics, risks, decisions,
goals). Each fact: {value, source: run_id|founder|import, confidence, updated_at}.
Conflicts flagged for manual founder review.
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
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "company_genomes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: str, fallback: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", "."})[:120] or fallback


def _genome_path(founder_id: str, company_id: str | None = None) -> Path:
    safe_founder = _safe_id(founder_id, "founder")
    resolved_company = company_id or founder_id
    if resolved_company == founder_id:
        return _root() / f"{safe_founder}.json"
    company_dir = _root() / safe_founder
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"{_safe_id(resolved_company, 'company')}.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_genome(founder_id: str, company_id: str | None = None) -> dict[str, Any] | None:
    """Load company genome."""
    with _lock:
        path = _genome_path(founder_id, company_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning("Failed to load genome for %s/%s: %s", founder_id, company_id, e)
            return None


def _empty_genome(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    resolved_company = company_id or founder_id
    return {
        "founder_id": founder_id,
        "company_id": resolved_company,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "sections": {
            "profile": {},
            "stage": {},
            "industry": {},
            "product": {},
            "icp": {},
            "personas": {},
            "positioning": {},
            "offers": {},
            "pricing": {},
            "competitors": {},
            "brand_voice": {},
            "branding": {},
            "objections": {},
            "metrics": {},
            "risks": {},
            "decisions": {},
            "goals": {},
        },
        "conflicts": [],
        "history": [],
    }


def set_fact(
    founder_id: str,
    section: str,
    key: str,
    value: Any,
    *,
    source: str = "founder",
    confidence: float = 1.0,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Set a fact in a genome section. Tracks source + confidence. Flags conflicts."""
    resolved_company = company_id or founder_id
    with _lock:
        path = _genome_path(founder_id, resolved_company)
        genome = get_genome(founder_id, resolved_company) or _empty_genome(founder_id, resolved_company)

        if section not in genome["sections"]:
            genome["sections"][section] = {}

        old_value = genome["sections"][section].get(key, {}).get("value")
        fact = {
            "value": value,
            "source": source,
            "confidence": min(1.0, max(0.0, confidence)),
            "updated_at": _now_iso(),
        }
        genome["sections"][section][key] = fact

        # Detect conflicts: same key, different value, both high confidence
        if old_value is not None and old_value != value:
            old_fact = genome["sections"][section][key]
            if old_fact.get("confidence", 0.8) > 0.6 and confidence > 0.6:
                conflict = {
                    "id": str(uuid.uuid4()),
                    "section": section,
                    "key": key,
                    "old_value": old_value,
                    "old_source": old_fact.get("source", "unknown"),
                    "new_value": value,
                    "new_source": source,
                    "status": "needs_review",
                    "flagged_at": _now_iso(),
                }
                if conflict not in genome["conflicts"]:
                    genome["conflicts"].append(conflict)

        # Append to history
        genome["history"].append({
            "section": section,
            "key": key,
            "action": "set",
            "value": value,
            "source": source,
            "at": _now_iso(),
        })

        genome["updated_at"] = _now_iso()
        path.write_text(json.dumps(genome, indent=2, sort_keys=True))
        return genome


def resolve_conflict(
    founder_id: str,
    company_id: str | None = None,
    conflict_id: str | None = None,
    keep_value: Any | None = None,
) -> bool:
    """Founder resolves a conflict by choosing the value to keep."""
    resolved_company = company_id or founder_id
    with _lock:
        genome = get_genome(founder_id, resolved_company)
        if not genome or not conflict_id:
            return False

        conflict = next((c for c in genome.get("conflicts", []) if c["id"] == conflict_id), None)
        if not conflict:
            return False

        section = conflict["section"]
        key = conflict["key"]
        kept = keep_value if keep_value is not None else conflict["new_value"]

        # Mark conflict resolved and update fact
        conflict["status"] = "resolved"
        conflict["resolved_to"] = kept
        conflict["resolved_at"] = _now_iso()

        genome["sections"][section][key]["value"] = kept
        genome["updated_at"] = _now_iso()

        path = _genome_path(founder_id, resolved_company)
        path.write_text(json.dumps(genome, indent=2, sort_keys=True))
        return True


def get_conflicts(founder_id: str, company_id: str | None = None) -> list[dict]:
    """Return unresolved conflicts."""
    genome = get_genome(founder_id, company_id)
    if not genome:
        return []
    return [c for c in genome.get("conflicts", []) if c.get("status") != "resolved"]


def get_section(
    founder_id: str,
    section: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Get all facts in a section."""
    genome = get_genome(founder_id, company_id)
    if not genome:
        return {}
    return genome.get("sections", {}).get(section, {})

"""Canonical structured research result schema (Wave 5.3 — Research Engine V2).

Astra runs research in two tiers:
  1. browser_research.py — Astra's own cheap native-search first pass
     (run_research_pipeline / deep_research's recursive crw search).
  2. web_search.py — open_deep_research, used only as a deep escalation
     when the first pass leaves coverage gaps.

Both tiers previously returned their own ad-hoc dict shapes. This module
defines one canonical `ResearchResult` shape that both tiers can emit (via
thin adapters), so downstream synthesis/artifact/UI code has a single
contract to consume regardless of which tier produced the answer.

Everything here is a plain TypedDict (== a plain dict at runtime), so a
`ResearchResult` is trivially JSON-serializable and safe to pass across a
Temporal activity boundary or a tool-call boundary — there is no custom
object, no non-serializable state.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional, TypedDict
from urllib.parse import urlparse, urlunparse


class Claim(TypedDict):
    claim_id: str          # stable id, e.g. sha256(query_id + claim_text)[:12]
    text: str               # the atomic claim
    evidence_ids: list[str] # references into `evidence` list below
    confidence: float       # 0-1
    contradicted: bool      # true if a later/other source disputes it
    contradiction_note: str # empty if not contradicted


class Evidence(TypedDict):
    evidence_id: str
    source_url: str
    title: str
    domain: str
    published_at: Optional[str]  # ISO date if known, else None
    retrieved_at: str            # ISO timestamp, always set (now())
    excerpt: str                 # the supporting quote/snippet


class ResearchResult(TypedDict):
    query_id: str
    question: str
    claims: list[Claim]
    evidence: list[Evidence]
    coverage_gaps: list[str]    # unanswered sub-questions
    escalation_decision: str    # "sufficient" | "escalate_to_deep" | "escalated"


def now_iso() -> str:
    """Current UTC timestamp, ISO-8601. Shared so every Evidence's
    retrieved_at is stamped consistently."""
    return datetime.now(timezone.utc).isoformat()


def new_query_id(question: str) -> str:
    """Stable id derived from the question text (sha256-based) so the same
    question re-asked across research rounds/retries maps to the same id."""
    normalized = (question or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:16]


def new_evidence_id(url: str, excerpt: str) -> str:
    """Stable id derived from (url, excerpt) so re-fetching the same
    source/quote pair produces the same evidence_id."""
    digest = hashlib.sha256(f"{url or ''}|{excerpt or ''}".encode("utf-8")).hexdigest()
    return digest[:16]


def new_claim_id(query_id: str, claim_text: str) -> str:
    """Stable id for a claim: sha256(query_id + claim_text)[:12]."""
    digest = hashlib.sha256(f"{query_id or ''}{claim_text or ''}".encode("utf-8")).hexdigest()
    return digest[:12]


def _normalize_url_for_dedup(url: str) -> str:
    """Normalize a URL purely for evidence de-duplication purposes: lowercase
    the host, strip query params and fragment, drop a trailing slash.

    This is intentionally NOT the same normalizer browser_research.py uses
    for display/citation purposes (that one preserves query params so two
    distinct pages on the same path can be disambiguated) — here we want an
    aggressive dedupe key so the same article fetched via two tracking-param
    variants collapses to one Evidence row.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip().lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def deduplicate_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Dedupe by normalized URL (strip query params/fragments, lowercase
    host), keeping the first occurrence."""
    seen: set[str] = set()
    deduped: list[Evidence] = []
    for item in evidence:
        key = _normalize_url_for_dedup(item.get("source_url", ""))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)
    return deduped


def _coerce_claim(raw: dict) -> Claim:
    return {
        "claim_id": str(raw.get("claim_id") or ""),
        "text": str(raw.get("text") or ""),
        "evidence_ids": [str(e) for e in (raw.get("evidence_ids") or []) if str(e)],
        "confidence": float(raw.get("confidence") or 0.0),
        "contradicted": bool(raw.get("contradicted") or False),
        "contradiction_note": str(raw.get("contradiction_note") or ""),
    }


def _coerce_evidence(raw: dict) -> Evidence:
    return {
        "evidence_id": str(raw.get("evidence_id") or ""),
        "source_url": str(raw.get("source_url") or ""),
        "title": str(raw.get("title") or ""),
        "domain": str(raw.get("domain") or ""),
        "published_at": raw.get("published_at") if raw.get("published_at") else None,
        "retrieved_at": str(raw.get("retrieved_at") or now_iso()),
        "excerpt": str(raw.get("excerpt") or ""),
    }


def dict_to_research_result(raw: dict) -> ResearchResult:
    """Coerce an arbitrary dict (e.g. deserialized JSON from a tool-call
    boundary) into a well-formed ResearchResult, filling missing fields with
    safe defaults rather than raising on partial/legacy payloads."""
    raw = raw or {}
    claims = [_coerce_claim(c) for c in (raw.get("claims") or []) if isinstance(c, dict)]
    evidence = [_coerce_evidence(e) for e in (raw.get("evidence") or []) if isinstance(e, dict)]
    escalation_decision = str(raw.get("escalation_decision") or "sufficient")
    if escalation_decision not in {"sufficient", "escalate_to_deep", "escalated"}:
        escalation_decision = "sufficient"
    return {
        "query_id": str(raw.get("query_id") or ""),
        "question": str(raw.get("question") or ""),
        "claims": claims,
        "evidence": evidence,
        "coverage_gaps": [str(g) for g in (raw.get("coverage_gaps") or [])],
        "escalation_decision": escalation_decision,
    }


def research_result_to_dict(result: ResearchResult) -> dict:
    """Reverse of dict_to_research_result — makes the JSON-safety boundary
    explicit at tool-call/artifact-write sites. TypedDicts are already plain
    dicts at runtime, but returning fresh copies here means callers can't
    accidentally mutate the original result via the dict they got back."""
    result = result or {}
    return {
        "query_id": result.get("query_id", ""),
        "question": result.get("question", ""),
        "claims": [dict(c) for c in result.get("claims", [])],
        "evidence": [dict(e) for e in result.get("evidence", [])],
        "coverage_gaps": list(result.get("coverage_gaps", [])),
        "escalation_decision": result.get("escalation_decision", "sufficient"),
    }

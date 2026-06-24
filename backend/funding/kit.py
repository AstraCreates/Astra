"""Auto-generated funding kit: pitch deck, executive summary, and one-pager.

Reads the company genome, calls the LLM once to produce structured slide
content, renders each document as a PDF (via the existing generate_pdf tool),
and stores everything in the founder's library so it's always current.

Automatically marks itself stale when the genome changes — call
`mark_stale(founder_id)` from the genome-update route, then the next
`get_status` call returns `needs_refresh: True`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any



logger = logging.getLogger(__name__)

_FUNDING_DEPT = "Finance"


# ── Status persistence ──────────────────────────────────────────────────────────

def _status_path(founder_id: str) -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    p = Path(vault) / "funding" / founder_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "status.json"


def _load_status(founder_id: str) -> dict[str, Any]:
    p = _status_path(founder_id)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _save_status(founder_id: str, status: dict[str, Any]) -> None:
    _status_path(founder_id).write_text(json.dumps(status, indent=2))


def _genome_hash(genome: dict[str, Any]) -> str:
    raw = json.dumps(genome, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_status(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    from backend.genome.store import get_genome
    status = _load_status(founder_id)
    genome = get_genome(founder_id, company_id) or {}
    current_hash = _genome_hash(genome)
    stored_hash = status.get("genome_hash", "")
    needs_refresh = (
        not status.get("generated_at")
        or current_hash != stored_hash
        or status.get("needs_refresh", False)
    )
    return {
        "generated_at": status.get("generated_at"),
        "genome_hash": current_hash,
        "needs_refresh": needs_refresh,
        "generating": status.get("generating", False),
        "documents": status.get("documents", []),
        "error": status.get("error"),
    }


def mark_stale(founder_id: str) -> None:
    status = _load_status(founder_id)
    status["needs_refresh"] = True
    _save_status(founder_id, status)


# ── LLM helper ─────────────────────────────────────────────────────────────────

def _call_llm(prompt: str) -> str:
    from backend.core.llm_client import get_or_client
    client = get_or_client(settings.openrouter_base_url, get_openrouter_key() or settings.agent_model_api_key)
    resp = client.chat.completions.create(
        model=settings.highoutput_model_name,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()


# ── Generation ─────────────────────────────────────────────────────────────────

_PITCH_DECK_PROMPT = """You are a startup pitch deck writer helping a founder prepare investor materials.

Company genome (all known facts):
{genome_json}

Write a complete pitch deck with these exact slide sections. For each section output substantive,
investor-ready content — not placeholders. Use the genome data directly. If data is missing for a
section, write what a strong founder would say given the stage/context, marked with [ASSUMED].

Respond with a JSON array only — no prose outside the array:
[
  {{"heading": "Problem", "body": "..."}},
  {{"heading": "Solution", "body": "..."}},
  {{"heading": "Market Opportunity", "body": "..."}},
  {{"heading": "Product", "body": "..."}},
  {{"heading": "Business Model", "body": "..."}},
  {{"heading": "Traction", "body": "..."}},
  {{"heading": "Team", "body": "..."}},
  {{"heading": "Financials", "body": "..."}},
  {{"heading": "The Ask", "body": "..."}},
  {{"heading": "Vision", "body": "..."}}
]"""

_EXEC_SUMMARY_PROMPT = """Write a 1-page executive summary for investors based on this company genome:

{genome_json}

Format as a JSON array of sections:
[
  {{"heading": "Company Overview", "body": "..."}},
  {{"heading": "Problem & Solution", "body": "..."}},
  {{"heading": "Market & Traction", "body": "..."}},
  {{"heading": "Business Model", "body": "..."}},
  {{"heading": "Team", "body": "..."}},
  {{"heading": "Funding Ask", "body": "..."}}
]

Be concise, factual, investor-ready. Use genome data directly. Mark gaps as [TBD]."""


def _parse_sections(raw: str) -> list[dict]:
    raw = raw.strip()
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except Exception:
        return [{"heading": "Content", "body": raw}]


def _get_branding(genome: dict, founder_id: str) -> dict:
    """Extract branding (name, colors, logo) from genome."""
    from backend.tools.pptx_generator import _extract_branding
    branding = _extract_branding(genome)
    # Also scan vault for a logo file if genome has no logo
    if not branding.get("logo_url") and not branding.get("logo_path"):
        vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
        for ext in ("png", "jpg", "jpeg"):
            candidate = Path(vault) / f"logo.{ext}"
            if candidate.exists():
                branding["logo_path"] = str(candidate)
                break
    return branding


def _save_to_library(
    founder_id: str, file_result: dict, label: str, company_name: str, content_desc: str,
) -> dict:
    from backend.library.store import create_file, list_files
    file_path = file_result.get("path", "")
    if not file_path:
        return {}
    existing = {f.get("source_path") for f in list_files(founder_id)}
    if file_path not in existing:
        return create_file(
            founder_id=founder_id,
            department=_FUNDING_DEPT,
            filename=file_result.get("filename", label),
            content=f"{content_desc} Auto-generated from company genome.",
            is_canonical=True,
            source_path=file_path,
            source_tag="Funding Kit",
        )
    return next((f for f in list_files(founder_id) if f.get("source_path") == file_path), {})


def generate_funding_kit(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    """Generate pitch deck (PPTX) + executive summary (PDF), save to library. Blocking — run in thread."""
    import time
    from backend.genome.store import get_genome
    from backend.tools.pptx_generator import generate_pptx
    from backend.tools.pdf_generator import generate_pdf

    status = _load_status(founder_id)
    status["generating"] = True
    status.pop("error", None)
    _save_status(founder_id, status)

    try:
        genome = get_genome(founder_id, company_id) or {}
        branding = _get_branding(genome, founder_id)
        company_name = (
            branding.get("company_name")
            or (genome.get("sections", {}).get("profile", {}) or {}).get("name", {})
            or "Company"
        )
        if isinstance(company_name, dict):
            company_name = company_name.get("value") or "Company"
        company_name = str(company_name).strip() or "Company"

        genome_json = json.dumps(genome, indent=2, default=str)[:8000]
        documents = []
        safe_name = company_name.lower().replace(" ", "_").encode("ascii", "ignore").decode()

        # ── Pitch Deck (PowerPoint) ───────────────────────────────────────────
        raw_deck = _call_llm(_PITCH_DECK_PROMPT.format(genome_json=genome_json))
        deck_sections = _parse_sections(raw_deck)
        deck_result = generate_pptx(
            title=f"{company_name} — Investor Pitch Deck",
            slides=deck_sections,
            company_name=company_name,
            primary_color=branding.get("primary_color", ""),
            accent_color=branding.get("accent_color", ""),
            logo_url=branding.get("logo_url", ""),
            logo_path=branding.get("logo_path", ""),
            filename=f"{safe_name}_pitch_deck.pptx",
        )
        rec = _save_to_library(founder_id, deck_result, "pitch_deck.pptx", company_name,
                               f"Investor pitch deck for {company_name}.")
        if deck_result.get("path"):
            documents.append({
                "type": "pitch_deck",
                "label": "Investor Pitch Deck",
                "file_id": rec.get("id", ""),
                "filename": deck_result.get("filename", "pitch_deck.pptx"),
                "source_path": deck_result.get("path", ""),
            })

        # ── Executive Summary (PDF) ───────────────────────────────────────────
        raw_exec = _call_llm(_EXEC_SUMMARY_PROMPT.format(genome_json=genome_json))
        exec_sections = _parse_sections(raw_exec)
        exec_result = generate_pdf(
            title=f"{company_name} — Executive Summary",
            sections=exec_sections,
            filename=f"{safe_name}_exec_summary.pdf",
            company_name=company_name,
            primary_color=branding.get("primary_color", ""),
            logo_url=branding.get("logo_url", ""),
            logo_path=branding.get("logo_path", ""),
        )
        rec2 = _save_to_library(founder_id, exec_result, "exec_summary.pdf", company_name,
                                f"Executive summary for {company_name}.")
        if exec_result.get("path"):
            documents.append({
                "type": "exec_summary",
                "label": "Executive Summary",
                "file_id": rec2.get("id", ""),
                "filename": exec_result.get("filename", "exec_summary.pdf"),
                "source_path": exec_result.get("path", ""),
            })

        genome_hash = _genome_hash(genome)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        new_status = {
            "generated_at": now,
            "genome_hash": genome_hash,
            "needs_refresh": False,
            "generating": False,
            "documents": documents,
        }
        _save_status(founder_id, new_status)
        return new_status

    except Exception as exc:
        logger.error("generate_funding_kit failed founder=%s: %s", founder_id, exc, exc_info=True)
        status = _load_status(founder_id)
        status["generating"] = False
        status["error"] = str(exc)
        _save_status(founder_id, status)
        raise

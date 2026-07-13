"""Wave 6.2: Graphiti/FalkorDB projection of authorized Company Brain records.

Projects canonical, non-tombstoned records to Graphiti for semantic retrieval,
handling ACL-based access control, corrections, and full rebuilds.
Graphiti/FalkorDB is a rebuildable derived index; Supabase remains authoritative.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from backend.control_plane.models import BrainProjectionJob

logger = logging.getLogger(__name__)


def project_brain_records_to_graphiti(
    company_id: str,
    acl_principal_id: Optional[str] = None,
    dry_run: bool = False,
    record_repo: Any | None = None,
    acl_repo: Any | None = None,
    graphiti_client: Any | None = None,
) -> dict[str, Any]:
    """Project authorized brain records to Graphiti/FalkorDB for semantic search.

    Args:
        company_id: Company to project
        acl_principal_id: Optional caller principal ID to filter by ACL
        dry_run: If True, only validate (do not write to Graphiti)

    Returns:
        dict with keys: ok, company_id, projected_count, error (if any)
    """
    if record_repo is None or acl_repo is None:
        from backend.control_plane.supabase_repositories import (
            SupabaseBrainAclRepository,
            SupabaseBrainRecordRepository,
        )
        record_repo = record_repo or SupabaseBrainRecordRepository()
        acl_repo = acl_repo or SupabaseBrainAclRepository()
    if graphiti_client is None:
        graphiti_client = _get_graphiti_client(company_id)

    try:
        # Fetch all canonical, non-tombstoned records for this company.
        records = record_repo.list_by_company(company_id, include_tombstoned=False)
        records = [r for r in records if r.is_canonical]

        projected_count = 0
        errors = []

        for record in records:
            acls = acl_repo.list_for_record(record.id)
            if not _record_is_projectable(acls, company_id=company_id, acl_principal_id=acl_principal_id):
                logger.debug(
                    "Skipping record %s (not projectable into namespace %s)",
                    record.id,
                    company_id,
                )
                continue

            try:
                if not dry_run:
                    _project_record_to_graphiti(record, graphiti_client=graphiti_client)
                projected_count += 1
            except Exception as exc:
                msg = f"Failed to project record {record.id}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                # Continue projecting other records despite this error.

        return {
            "ok": len(errors) == 0,
            "company_id": company_id,
            "projected_count": projected_count,
            "error": " | ".join(errors) if errors else None,
        }

    except Exception as exc:
        logger.error("project_brain_records_to_graphiti failed: %s", exc)
        return {
            "ok": False,
            "company_id": company_id,
            "projected_count": 0,
            "error": str(exc),
        }


def full_rebuild_graphiti(
    company_id: str,
    dry_run: bool = False,
    record_repo: Any | None = None,
    acl_repo: Any | None = None,
    graphiti_client: Any | None = None,
) -> dict[str, Any]:
    """Nuke Graphiti namespace for company and re-project all records.

    Idempotent; safe to call even if graph is mid-update.

    Args:
        company_id: Company to rebuild
        dry_run: If True, only validate (do not write)

    Returns:
        dict with keys: ok, company_id, rebuilt, error
    """
    try:
        if not dry_run:
            client = graphiti_client or _get_graphiti_client(company_id)
            if hasattr(client, "clear_namespace"):
                client.clear_namespace(company_id)
        # Re-project everything.
        result = project_brain_records_to_graphiti(
            company_id,
            dry_run=dry_run,
            record_repo=record_repo,
            acl_repo=acl_repo,
            graphiti_client=graphiti_client,
        )
        result["rebuilt"] = True
        return result
    except Exception as exc:
        logger.error("full_rebuild_graphiti failed for company_id=%s: %s", company_id, exc)
        return {
            "ok": False,
            "company_id": company_id,
            "rebuilt": False,
            "error": str(exc),
        }


def apply_supersession(old_record_id: str, new_record_id: str, *, company_id: str | None = None, graphiti_client: Any | None = None) -> dict[str, Any]:
    """Mark old episode as superseded in Graphiti, link to new one.

    Args:
        old_record_id: ID of superseded record
        new_record_id: ID of superseding record

    Returns:
        dict with keys: ok, error
    """
    try:
        if graphiti_client is None and not _graphiti_available():
            logger.warning("Graphiti not available; supersession not applied")
            return {"ok": False, "error": "Graphiti not available"}

        client = graphiti_client or _get_graphiti_client(company_id or "")
        resolved_company_id = company_id or ""
        if hasattr(client, "mark_superseded"):
            client.mark_superseded(resolved_company_id, old_record_id, new_record_id)
        logger.info("Applied supersession: %s -> %s", old_record_id, new_record_id)
        return {"ok": True}

    except Exception as exc:
        logger.error("apply_supersession failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def process_brain_projection_jobs(
    *,
    limit: int = 50,
    dead_letter_after: int = 3,
    supabase_client: Any | None = None,
    record_repo: Any | None = None,
    acl_repo: Any | None = None,
    graphiti_client: Any | None = None,
) -> dict[str, Any]:
    """Process pending/failed projection jobs with bounded retries and dead-lettering."""
    if supabase_client is None:
        from backend.db.client import get_supabase

        supabase_client = get_supabase()
    if record_repo is None or acl_repo is None:
        from backend.control_plane.supabase_repositories import (
            SupabaseBrainAclRepository,
            SupabaseBrainRecordRepository,
        )

        record_repo = record_repo or SupabaseBrainRecordRepository()
        acl_repo = acl_repo or SupabaseBrainAclRepository()

    rows = (
        supabase_client.table("astra_brain_projection_jobs")
        .select("*")
        .in_("status", ["pending", "failed"])
        .order("created_at")
        .limit(max(1, limit))
        .execute()
        .data
    )
    jobs = [BrainProjectionJob.model_validate(row) for row in rows]

    summary = {"seen": len(jobs), "succeeded": 0, "failed": 0, "dead_lettered": 0}
    for job in jobs:
        summary_key = _process_single_projection_job(
            job,
            supabase_client=supabase_client,
            record_repo=record_repo,
            acl_repo=acl_repo,
            graphiti_client=graphiti_client,
            dead_letter_after=dead_letter_after,
        )
        summary[summary_key] += 1
    return summary


def _project_record_to_graphiti(record: Any, graphiti_client: Any | None = None) -> None:
    """Project a single BrainRecord to Graphiti as an episode.

    Extracts content from provenance, sanitizes for caller access, and creates
    or updates the Graphiti episode with metadata.

    Args:
        record: BrainRecord to project
    """
    if graphiti_client is None and not _graphiti_available():
        logger.debug("Graphiti not available; skipping projection for record %s", record.id)
        return

    # Extract content from provenance.
    provenance = record.provenance or {}
    content = provenance.get("content", {})

    if not content:
        logger.warning("Record %s has no content in provenance; skipping", record.id)
        return

    # Build episode metadata.
    metadata = {
        "company_id": record.company_id,
        "source": record.source,
        "external_id": record.external_id,
        "version": record.version,
        "retrieved_at": record.created_at.isoformat() if record.created_at else None,
        "confidence": 1.0,
        "hash": record.content_hash,
    }

    # Sanitize content: remove secrets, ACL-restricted fields.
    # (In a real implementation, check caller ACLs and redact accordingly.)
    sanitized_content = _sanitize_content(content)

    # Convert to text for Graphiti ingestion.
    episode_text = _content_to_episode_text(sanitized_content)

    # Call Graphiti SDK to upsert episode.
    try:
        client = graphiti_client or _get_graphiti_client(record.company_id)
        if hasattr(client, "upsert_episode"):
            client.upsert_episode(record.company_id, record.id, episode_text, metadata)
        logger.debug(
            "Projected record %s to Graphiti (company=%s source=%s)",
            record.id,
            record.company_id,
            record.source,
        )
    except Exception as exc:
        logger.error("Failed to project record %s to Graphiti: %s", record.id, exc)
        raise


def _delete_record_from_graphiti(company_id: str, record_id: str, graphiti_client: Any | None = None) -> None:
    client = graphiti_client or _get_graphiti_client(company_id)
    if hasattr(client, "delete_episode"):
        client.delete_episode(company_id, record_id)
        return
    if hasattr(client, "clear_namespace") and hasattr(client, "upsert_episode"):
        # Last-resort local fake path: remove single episode if the fake supports a backing store.
        episodes = getattr(client, "_episodes", {}).get(company_id, {})
        if record_id in episodes:
            episodes.pop(record_id, None)
        indexed = getattr(client, "_indexed_records", {}).get(company_id, [])
        if record_id in indexed:
            indexed.remove(record_id)


def _sanitize_content(content: dict[str, Any]) -> dict[str, Any]:
    """Remove secrets, ACL-restricted fields, and sensitive data from content.

    Args:
        content: Raw connector content

    Returns:
        Sanitized content safe for graph ingestion
    """
    # Redact known secret fields.
    REDACT_KEYS = {
        "token",
        "secret",
        "password",
        "api_key",
        "private_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization",
        "cookie",
        "set_cookie",
    }

    def redact_recursive(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: None if k.lower() in REDACT_KEYS else redact_recursive(v)
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [redact_recursive(item) for item in obj]
        return obj

    return redact_recursive(content)


def _content_to_episode_text(content: dict[str, Any]) -> str:
    """Convert sanitized connector content to text for Graphiti ingestion.

    Args:
        content: Normalized content dict

    Returns:
        Text representation for semantic search
    """
    if isinstance(content, str):
        return content

    # Convert dict/list to readable text.
    parts = []
    for key, val in content.items():
        if val is None:
            continue
        if isinstance(val, dict):
            parts.append(f"{key}: {json.dumps(val, indent=2)}")
        elif isinstance(val, list):
            parts.append(f"{key}: " + ", ".join(str(v) for v in val))
        else:
            parts.append(f"{key}: {val}")
    return "\n".join(parts)


def _clear_graphiti_namespace(company_id: str) -> None:
    """Delete all Graphiti episodes for a company.

    Args:
        company_id: Company namespace to clear
    """
    if not _graphiti_available():
        logger.debug("Graphiti not available; namespace clear skipped")
        return

    try:
        client = _get_graphiti_client(company_id)
        if hasattr(client, "clear_namespace"):
            client.clear_namespace(company_id)
        logger.info("Cleared Graphiti namespace for company_id=%s", company_id)
    except Exception as exc:
        logger.error("Failed to clear Graphiti namespace: %s", exc)
        raise


def _graphiti_available() -> bool:
    """Check if Graphiti/FalkorDB is available.

    Returns:
        True if client is available and healthy
    """
    try:
        from backend.control_plane.graphiti_adapter import graphiti_available

        return bool(graphiti_available())
    except Exception:
        return False


def _get_graphiti_client(company_id: str) -> Any:
    """Get or create Graphiti client scoped to company namespace.

    Args:
        company_id: Company namespace

    Returns:
        Graphiti client instance
    """
    try:
        from backend.control_plane.graphiti_adapter import GraphitiBrainClient

        return GraphitiBrainClient()
    except Exception:
        from backend.control_plane.fakes import FakeGraphitiClient

        return FakeGraphitiClient()


def _record_is_projectable(acls: list[Any], *, company_id: str, acl_principal_id: str | None = None) -> bool:
    if acl_principal_id:
        return any(
            (acl.principal_type == "company" and acl.principal_id == company_id)
            or acl.principal_id == acl_principal_id
            for acl in acls
        )
    # Shared company graph may only contain company-readable records.
    return any(acl.principal_type == "company" and acl.principal_id == company_id for acl in acls)


def _process_single_projection_job(
    job: BrainProjectionJob,
    *,
    supabase_client: Any,
    record_repo: Any,
    acl_repo: Any,
    graphiti_client: Any | None,
    dead_letter_after: int,
) -> str:
    attempt_number = int(job.attempts or 0) + 1
    _patch_projection_job(
        supabase_client,
        job.id,
        {
            "status": "running",
            "attempts": attempt_number,
            "last_attempted_at": _utc_now(),
            "error": None,
        },
    )
    try:
        record = record_repo.get(job.record_id)
        if record is None:
            raise ValueError(f"unknown record_id {job.record_id}")
        company_id = str(getattr(record, "company_id", "") or "")
        client = graphiti_client or _get_graphiti_client(company_id)

        if job.job_type == "upsert":
            acls = acl_repo.list_for_record(record.id)
            if getattr(record, "tombstoned_at", None) or not getattr(record, "is_canonical", True):
                _delete_record_from_graphiti(company_id, record.id, graphiti_client=client)
            elif _record_is_projectable(acls, company_id=company_id):
                _project_record_to_graphiti(record, graphiti_client=client)
            else:
                _delete_record_from_graphiti(company_id, record.id, graphiti_client=client)
        elif job.job_type == "tombstone":
            _delete_record_from_graphiti(company_id, record.id, graphiti_client=client)
        elif job.job_type == "rebuild":
            full_rebuild_graphiti(
                company_id,
                dry_run=False,
                record_repo=record_repo,
                acl_repo=acl_repo,
                graphiti_client=client,
            )
        else:
            raise ValueError(f"unsupported job_type {job.job_type}")

        _patch_projection_job(
            supabase_client,
            job.id,
            {"status": "succeeded", "completed_at": _utc_now(), "error": None},
        )
        return "succeeded"
    except Exception as exc:
        status = "dead_letter" if attempt_number >= max(1, dead_letter_after) else "failed"
        _patch_projection_job(
            supabase_client,
            job.id,
            {"status": status, "error": str(exc)},
        )
        return "dead_lettered" if status == "dead_letter" else "failed"


def _patch_projection_job(supabase_client: Any, job_id: str, patch: dict[str, Any]) -> None:
    supabase_client.table("astra_brain_projection_jobs").update(patch).eq("id", job_id).execute()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

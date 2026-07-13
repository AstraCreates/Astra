"""Wave 6.1: Company Brain canonical ingestion from connectors.

Normalizes connector content into astra_brain_records with SHA-256 hashing,
supersession detection, and durable outbox enqueuing for Graphiti projection.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from backend.control_plane.models import BrainAcl, BrainRecord
from backend.control_plane.supabase_repositories import (
    SupabaseBrainAclRepository,
    SupabaseBrainRecordRepository,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_content_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hash of content JSON for change detection."""
    json_str = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def _sanitize_provenance(provenance: Optional[dict[str, Any]]) -> dict[str, Any]:
    redact_keys = {
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

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: None if key.lower() in redact_keys else scrub(inner)
                for key, inner in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(dict(provenance or {}))


def ingest_brain_record(
    company_id: str,
    source: str,
    external_id: str,
    content: dict[str, Any],
    version: int = 1,
    acl_groups: Optional[list[str]] = None,
    provenance: Optional[dict[str, Any]] = None,
) -> BrainRecord:
    """Normalize and persist a single connector record to astra_brain_records.

    Args:
        company_id: Company identifier
        source: Connector source (github, slack, linear, notion, etc.)
        external_id: External ID from the connector (e.g., GitHub issue #123)
        content: Normalized connector content dict
        version: Record version (for supersession tracking)
        acl_groups: List of group/role IDs that can access this record
        provenance: Optional provenance metadata (source_account, retrieved_at, etc.)

    Returns:
        Persisted BrainRecord

    Raises:
        ValueError: If content is invalid or Supabase write fails after retries
    """
    content_hash = _compute_content_hash(content)

    # Check for supersession: if a newer version exists for this (company, source, external_id),
    # mark the prior as superseded.
    record_repo = SupabaseBrainRecordRepository()
    prior_records = record_repo.list_by_external_id(company_id, source, external_id)
    exact_existing = next(
        (
            r
            for r in prior_records
            if int(r.version or 0) == int(version)
            and (r.content_hash or "") == content_hash
            and not r.tombstoned_at
        ),
        None,
    )
    if exact_existing is not None:
        logger.debug(
            "Brain ingest idempotent hit company_id=%s source=%s external_id=%s version=%s record_id=%s",
            company_id,
            source,
            external_id,
            version,
            exact_existing.id,
        )
        return exact_existing

    prior_canonical = next((r for r in prior_records if r.is_canonical and not r.tombstoned_at), None)

    record_id = str(uuid4())
    record = BrainRecord(
        id=record_id,
        company_id=company_id,
        source=source,
        external_id=external_id,
        version=version,
        content_hash=content_hash,
        provenance={
            **_sanitize_provenance(provenance),
            "content": content,
        },
        is_canonical=True,
        tombstoned_at=None,
        created_at=_now(),
    )

    # Persist the new record.
    try:
        persisted = record_repo.create(record)
    except Exception as exc:
        logger.error(
            "Failed to ingest brain record company_id=%s source=%s external_id=%s: %s",
            company_id,
            source,
            external_id,
            exc,
        )
        raise ValueError(f"Failed to persist brain record: {exc}") from exc

    # If a prior canonical record exists, mark it as superseded.
    if prior_canonical:
        try:
            record_repo.mark_superseded(prior_canonical.id, record_id)
            logger.debug(
                "Marked prior record %s as superseded by %s",
                prior_canonical.id,
                record_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to mark prior record as superseded: %s; continuing anyway",
                exc,
            )

    # Create ACL entries for authorized groups.
    if acl_groups:
        acl_repo = SupabaseBrainAclRepository()
        for group_id in acl_groups:
            try:
                acl = BrainAcl(
                    id=str(uuid4()),
                    record_id=record_id,
                    principal_type="role",
                    principal_id=group_id,
                    access_level="read",
                    created_at=_now(),
                )
                acl_repo.create(acl)
            except Exception as exc:
                logger.warning(
                    "Failed to create ACL for record %s group %s: %s",
                    record_id,
                    group_id,
                    exc,
                )

    # Enqueue projection job via outbox (durable event).
    try:
        _enqueue_projection_job(company_id, record_id, "upsert")
    except Exception as exc:
        logger.warning(
            "Failed to enqueue projection job for record %s: %s; "
            "record persisted but may not project until retry",
            record_id,
            exc,
        )

    return persisted


def ingest_tombstone(company_id: str, source: str, external_id: str) -> None:
    """Mark a record as deleted and enqueue its removal from Graphiti.

    Args:
        company_id: Company identifier
        source: Connector source
        external_id: External ID to tombstone
    """
    record_repo = SupabaseBrainRecordRepository()
    canonical = next(
        (
            r
            for r in record_repo.list_by_external_id(company_id, source, external_id)
            if r.is_canonical and not r.tombstoned_at
        ),
        None,
    )

    if not canonical:
        logger.warning(
            "Attempted to tombstone non-existent record: "
            "company_id=%s source=%s external_id=%s",
            company_id,
            source,
            external_id,
        )
        return

    try:
        record_repo.mark_tombstone(canonical.id)
        logger.info(
            "Tombstoned record %s (company_id=%s source=%s external_id=%s)",
            canonical.id,
            company_id,
            source,
            external_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to tombstone record %s: %s",
            canonical.id,
            exc,
        )
        raise

    # Enqueue projection job.
    try:
        _enqueue_projection_job(company_id, canonical.id, "tombstone")
    except Exception as exc:
        logger.warning(
            "Failed to enqueue tombstone projection job: %s",
            exc,
        )


def _enqueue_projection_job(company_id: str, record_id: str, action: str) -> None:
    """Enqueue a brain projection job via the durable outbox.

    This ensures the projection task is retried if Graphiti is temporarily unavailable.
    Ingest remains fast (Supabase write) and projection is decoupled.

    Args:
        company_id: Company identifier
        record_id: Record to project
        action: "upsert", "supersede", or "tombstone"
    """
    from backend.db.client import get_supabase

    job_id = str(uuid4())
    payload = {
        "company_id": company_id,
        "record_id": record_id,
        "action": action,
    }

    try:
        get_supabase().table("astra_brain_projection_jobs").insert({
            "id": job_id,
            "record_id": record_id,
            "job_type": action,
            "status": "pending",
            "created_at": _now().isoformat(),
        }).execute()
        logger.debug("Enqueued projection job %s for record %s (action=%s)", job_id, record_id, action)
    except Exception as exc:
        logger.warning("Failed to enqueue projection job: %s", exc)
        raise

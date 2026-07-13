"""Tests for Wave 6.1 Company Brain ingestion and normalization."""
import json
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.control_plane.brain_ingestion import (
    ingest_brain_record,
    ingest_tombstone,
    _compute_content_hash,
)
from backend.control_plane.models import BrainAcl, BrainRecord
from backend.control_plane.fakes import FakeBrainAclRepository, FakeBrainRecordRepository


def _fake_repositories():
    """Create fake repositories for testing."""
    return FakeBrainRecordRepository(), FakeBrainAclRepository()


def test_compute_content_hash():
    """Content hash is deterministic and consistent."""
    content = {"title": "Test", "body": "Content"}
    hash1 = _compute_content_hash(content)
    hash2 = _compute_content_hash(content)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex


def test_compute_content_hash_order_independent():
    """Content hash ignores key order (JSON canonical form)."""
    content1 = {"a": 1, "b": 2}
    content2 = {"b": 2, "a": 1}
    assert _compute_content_hash(content1) == _compute_content_hash(content2)


def test_compute_content_hash_different_content():
    """Different content produces different hashes."""
    content1 = {"title": "A"}
    content2 = {"title": "B"}
    assert _compute_content_hash(content1) != _compute_content_hash(content2)


def test_ingest_normalizes_and_hashes_content():
    """Ingest normalizes content, computes hash, and persists record."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {
        "id": "123",
        "title": "Bug report",
        "body": "There is a bug",
        "state": "open",
    }

    # Mock Supabase repositories to use fakes.
    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                record = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                    version=1,
                )

    assert record.company_id == company_id
    assert record.source == source
    assert record.external_id == external_id
    assert record.version == 1
    assert record.content_hash == _compute_content_hash(content)
    assert record.is_canonical
    assert record.tombstoned_at is None
    assert "content" in record.provenance

    # Verify persisted in fake repo.
    persisted = record_repo.get(record.id)
    assert persisted is not None
    assert persisted.id == record.id


def test_ingest_sanitizes_sensitive_provenance_fields():
    record_repo, acl_repo = _fake_repositories()

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                record = ingest_brain_record(
                    company_id="company_1",
                    source="slack",
                    external_id="thread-123",
                    content={"title": "Launch", "body": "Notes"},
                    provenance={"token": "secret", "nested": {"authorization": "Bearer abc"}},
                )

    assert record.provenance["token"] is None
    assert record.provenance["nested"]["authorization"] is None
    assert record.provenance["content"] == {"title": "Launch", "body": "Notes"}


def test_ingest_detects_supersession():
    """Ingest a new version and confirm prior is marked superseded."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"

    # Create version 1.
    v1_content = {"title": "Original"}
    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                v1 = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=v1_content,
                    version=1,
                )

    assert v1.is_canonical

    # Create version 2.
    v2_content = {"title": "Updated"}
    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                v2 = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=v2_content,
                    version=2,
                )

    assert v2.is_canonical

    # Verify v1 is no longer canonical and has supersession metadata.
    v1_updated = record_repo.get(v1.id)
    assert v1_updated is not None
    assert not v1_updated.is_canonical
    assert v2.id in v1_updated.provenance.get("superseded_by", "")


def test_ingest_is_idempotent_for_same_version_and_content():
    """Repeated ingest of the same connector version/content returns the existing record."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {"title": "Original", "body": "Same content"}

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job") as mock_enqueue:
                first = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                    version=1,
                )
                second = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                    version=1,
                )

    assert second.id == first.id
    assert len(record_repo.list_by_external_id(company_id, source, external_id)) == 1
    mock_enqueue.assert_called_once()


def test_ingest_with_acl_groups():
    """Ingest with ACL groups creates access control entries."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {"title": "Test"}
    acl_groups = ["engineering", "backend"]

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                record = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                    acl_groups=acl_groups,
                )

    # Verify ACL entries created.
    acls = acl_repo.list_for_record(record.id)
    assert len(acls) == 2
    assert all(acl.record_id == record.id for acl in acls)
    assert all(acl.access_level == "read" for acl in acls)
    assert {acl.principal_id for acl in acls} == {"engineering", "backend"}


def test_tombstone_marks_record_deleted():
    """Tombstone marks a record as deleted and non-canonical."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {"title": "Test"}

    # Ingest a record.
    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                record = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                )

    assert record.tombstoned_at is None
    assert record.is_canonical

    # Tombstone it.
    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
            ingest_tombstone(company_id, source, external_id)

    # Verify it's marked tombstoned and non-canonical.
    tombstoned = record_repo.get(record.id)
    assert tombstoned is not None
    assert tombstoned.tombstoned_at is not None
    assert not tombstoned.is_canonical


def test_tombstone_nonexistent_record_logs_warning():
    """Tombstoning a non-existent record logs a warning."""
    record_repo, acl_repo = _fake_repositories()

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.logger") as mock_logger:
            ingest_tombstone("company_1", "github", "nonexistent")

    mock_logger.warning.assert_called()


def test_ingest_projection_job_enqueue():
    """Ingest enqueues a projection job for async processing."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {"title": "Test"}

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_insert = MagicMock()
    mock_table.insert.return_value = mock_insert
    mock_insert.execute.return_value = MagicMock()

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job") as mock_enqueue:
                record = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                )

    # Verify projection job enqueue was called.
    mock_enqueue.assert_called_once()
    call_args = mock_enqueue.call_args[0]
    assert call_args[0] == company_id  # company_id
    assert call_args[1] == record.id   # record_id
    assert call_args[2] == "upsert"    # action


def test_ingest_handles_supabase_error():
    """Ingest raises ValueError if Supabase write fails."""
    record_repo = MagicMock()
    record_repo.create.side_effect = Exception("Supabase connection error")

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository"):
            with pytest.raises(ValueError, match="Failed to persist"):
                ingest_brain_record(
                    company_id="company_1",
                    source="github",
                    external_id="issue-123",
                    content={"title": "Test"},
                )


def test_ingest_provenance_preservation():
    """Ingest preserves custom provenance and adds content."""
    record_repo, acl_repo = _fake_repositories()

    company_id = "company_1"
    source = "github"
    external_id = "issue-123"
    content = {"title": "Test"}
    custom_provenance = {
        "source_account": "org/repo",
        "retrieved_at": "2025-01-01T00:00:00Z",
    }

    with patch("backend.control_plane.brain_ingestion.SupabaseBrainRecordRepository", return_value=record_repo):
        with patch("backend.control_plane.brain_ingestion.SupabaseBrainAclRepository", return_value=acl_repo):
            with patch("backend.control_plane.brain_ingestion._enqueue_projection_job"):
                record = ingest_brain_record(
                    company_id=company_id,
                    source=source,
                    external_id=external_id,
                    content=content,
                    provenance=custom_provenance,
                )

    # Verify custom provenance is preserved.
    assert record.provenance["source_account"] == "org/repo"
    assert record.provenance["retrieved_at"] == "2025-01-01T00:00:00Z"
    assert record.provenance["content"] == content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

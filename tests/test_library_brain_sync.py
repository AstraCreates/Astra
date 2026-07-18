"""Library documents must stay mirrored into Company Brain: create indexes it,
content updates revise it (not duplicate it), and delete fully removes it.

Requested directly: "make sure documents in the library update company brain".
Before this, backend/library/store.py had zero interaction with company_brain --
uploading, editing, or deleting a Library file never touched the brain agents
actually read from at runtime.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))


def test_create_file_syncs_into_company_brain():
    from backend.library import store
    from backend.tools.company_brain import get_company_brain

    founder = "founder_create"
    rec = store.create_file(founder, "research", "notes.md", "Real substantial market findings content, long enough to count as meaningful for the brain to index and retrieve later on.")

    assert rec.get("brain_record_id"), "create_file must link a brain record"
    brain = get_company_brain(founder)
    linked = [r for r in brain["records"] if r.get("metadata", {}).get("library_file_id") == rec["id"]]
    assert len(linked) == 1
    assert linked[0]["status"] == "active"


def test_create_file_with_empty_content_does_not_sync():
    from backend.library import store

    rec = store.create_file("founder_empty", "research", "blank.md", "   ")
    assert not rec.get("brain_record_id")


def test_update_file_content_revises_not_duplicates_brain_record():
    from backend.library import store
    from backend.tools.company_brain import get_company_brain

    founder = "founder_update"
    rec = store.create_file(founder, "research", "notes.md", "Original substantial findings about the market and target customer segment for this product line.")
    original_brain_id = rec["brain_record_id"]

    updated = store.update_file(founder, rec["id"], content="Revised substantial findings: new pricing data and a named competitor emerged from further research.")
    assert updated["brain_record_id"]
    assert updated["brain_record_id"] != original_brain_id  # revision creates a new version id

    brain = get_company_brain(founder)
    active = [r for r in brain["records"] if r.get("metadata", {}).get("library_file_id") == rec["id"] and r.get("status", "active") == "active"]
    assert len(active) == 1, "must have exactly one active record after a content revision, not a duplicate"
    assert "pricing data" in active[0]["content"]


def test_update_file_metadata_only_does_not_touch_brain():
    from backend.library import store

    founder = "founder_meta_only"
    rec = store.create_file(founder, "research", "notes.md", "Substantial original content for this brain sync regression test to verify metadata-only updates are skipped.")
    original_brain_id = rec["brain_record_id"]

    updated = store.update_file(founder, rec["id"], filename="renamed.md")
    assert updated["brain_record_id"] == original_brain_id


def test_delete_file_removes_linked_brain_record():
    from backend.library import store
    from backend.tools.company_brain import get_company_brain

    founder = "founder_delete"
    rec = store.create_file(founder, "research", "notes.md", "Substantial content that will shortly be deleted along with its mirrored company brain record entirely.")
    assert rec.get("brain_record_id")

    assert store.delete_file(founder, rec["id"]) is True

    brain = get_company_brain(founder)
    remaining = [r for r in brain["records"] if r.get("metadata", {}).get("library_file_id") == rec["id"]]
    assert remaining == []

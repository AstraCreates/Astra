"""Tests for Wave 6.2 brain projection and rebuild behavior."""

from backend.control_plane.brain_projection import (
    apply_supersession,
    full_rebuild_graphiti,
    process_brain_projection_jobs,
    project_brain_records_to_graphiti,
)
from backend.control_plane.fakes import (
    FakeBrainAclRepository,
    FakeBrainRecordRepository,
    FakeGraphitiClient,
)
from backend.control_plane.models import BrainAcl, BrainRecord


def _record(record_id: str, company_id: str, content: dict, *, canonical: bool = True, tombstoned: bool = False) -> BrainRecord:
    from datetime import datetime, timezone

    return BrainRecord(
        id=record_id,
        company_id=company_id,
        source="manual",
        external_id=record_id,
        version=1,
        content_hash="h",
        provenance={"content": content},
        is_canonical=canonical,
        tombstoned_at=datetime.now(timezone.utc) if tombstoned else None,
        created_at=datetime.now(timezone.utc),
    )


def test_project_brain_records_projects_only_authorized_canonical_records():
    company_id = "company_w6"
    record_repo = FakeBrainRecordRepository()
    acl_repo = FakeBrainAclRepository()
    graphiti = FakeGraphitiClient()

    record_repo.create(_record("r1", company_id, {"title": "Alpha", "body": "Shared"}))
    record_repo.create(_record("r2", company_id, {"title": "Beta", "body": "Hidden"}, canonical=False))
    record_repo.create(_record("r3", company_id, {"title": "Gamma", "body": "Gone"}, tombstoned=True))

    acl_repo.create(BrainAcl(id="a1", record_id="r1", principal_type="company", principal_id=company_id, access_level="read"))
    acl_repo.create(BrainAcl(id="a2", record_id="r2", principal_type="company", principal_id=company_id, access_level="read"))
    acl_repo.create(BrainAcl(id="a3", record_id="r3", principal_type="company", principal_id=company_id, access_level="read"))

    result = project_brain_records_to_graphiti(
        company_id,
        record_repo=record_repo,
        acl_repo=acl_repo,
        graphiti_client=graphiti,
    )

    assert result["ok"] is True
    assert result["projected_count"] == 1
    assert graphiti.get_episode(company_id, "r1") is not None
    assert graphiti.get_episode(company_id, "r2") is None
    assert graphiti.get_episode(company_id, "r3") is None


def test_project_brain_records_excludes_user_only_records_from_shared_graph():
    company_id = "company_w6_acl_scope"
    record_repo = FakeBrainRecordRepository()
    acl_repo = FakeBrainAclRepository()
    graphiti = FakeGraphitiClient()

    record_repo.create(_record("company_visible", company_id, {"title": "Shared", "body": "Company readable"}))
    record_repo.create(_record("user_only", company_id, {"title": "Private", "body": "Restricted"}))

    acl_repo.create(BrainAcl(id="a1", record_id="company_visible", principal_type="company", principal_id=company_id, access_level="read"))
    acl_repo.create(BrainAcl(id="a2", record_id="user_only", principal_type="user", principal_id="user_1", access_level="read"))

    result = project_brain_records_to_graphiti(
        company_id,
        record_repo=record_repo,
        acl_repo=acl_repo,
        graphiti_client=graphiti,
    )

    assert result["ok"] is True
    assert result["projected_count"] == 1
    assert graphiti.get_episode(company_id, "company_visible") is not None
    assert graphiti.get_episode(company_id, "user_only") is None


def test_full_rebuild_clears_and_reprojects_company_namespace():
    company_id = "company_w6_rebuild"
    record_repo = FakeBrainRecordRepository()
    acl_repo = FakeBrainAclRepository()
    graphiti = FakeGraphitiClient()

    record_repo.create(_record("r1", company_id, {"title": "Alpha", "body": "One"}))
    acl_repo.create(BrainAcl(id="a1", record_id="r1", principal_type="company", principal_id=company_id, access_level="read"))
    graphiti.upsert_episode(company_id, "stale", "stale episode", {"company_id": company_id})

    result = full_rebuild_graphiti(
        company_id,
        dry_run=False,
        record_repo=record_repo,
        acl_repo=acl_repo,
        graphiti_client=graphiti,
    )

    assert result["rebuilt"] is True
    assert graphiti.get_episode(company_id, "stale") is None


def test_apply_supersession_marks_old_episode_metadata():
    company_id = "company_w6_supersession"
    graphiti = FakeGraphitiClient()
    graphiti.upsert_episode(company_id, "old", "old episode", {"company_id": company_id})

    result = apply_supersession("old", "new", company_id=company_id, graphiti_client=graphiti)

    episode = graphiti.get_episode(company_id, "old")
    assert result["ok"] is True
    assert episode is not None
    assert episode["metadata"]["superseded_by"] == "new"
    assert episode["metadata"]["status"] == "superseded"


class _FakeProjectionQuery:
    def __init__(self, rows, updates):
        self._rows = rows
        self._updates = updates
        self._patch = None
        self._job_id = None

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, _field, value):
        self._job_id = value
        return self

    def execute(self):
        if self._patch is None:
            return type("Resp", (), {"data": list(self._rows)})()
        self._updates.append((self._job_id, dict(self._patch)))
        return type("Resp", (), {"data": []})()


class _FakeProjectionSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, name):
        assert name == "astra_brain_projection_jobs"
        return _FakeProjectionQuery(self.rows, self.updates)


def test_process_projection_jobs_upserts_and_tombstones_records():
    company_id = "company_w6_jobs"
    record_repo = FakeBrainRecordRepository()
    acl_repo = FakeBrainAclRepository()
    graphiti = FakeGraphitiClient()

    visible = record_repo.create(_record("visible", company_id, {"title": "Shared", "body": "ok"}))
    deleted = record_repo.create(_record("deleted", company_id, {"title": "Deleted", "body": "gone"}))
    record_repo.mark_tombstone(deleted.id)

    acl_repo.create(BrainAcl(id="a1", record_id=visible.id, principal_type="company", principal_id=company_id, access_level="read"))
    acl_repo.create(BrainAcl(id="a2", record_id=deleted.id, principal_type="company", principal_id=company_id, access_level="read"))
    graphiti.upsert_episode(company_id, deleted.id, "stale", {"company_id": company_id})

    jobs = [
        {"id": "job_upsert", "record_id": visible.id, "job_type": "upsert", "status": "pending", "attempts": 0},
        {"id": "job_tombstone", "record_id": deleted.id, "job_type": "tombstone", "status": "pending", "attempts": 0},
    ]
    supabase = _FakeProjectionSupabase(jobs)

    summary = process_brain_projection_jobs(
        supabase_client=supabase,
        record_repo=record_repo,
        acl_repo=acl_repo,
        graphiti_client=graphiti,
    )

    assert summary == {"seen": 2, "succeeded": 2, "failed": 0, "dead_lettered": 0}
    assert graphiti.get_episode(company_id, visible.id) is not None
    assert graphiti.get_episode(company_id, deleted.id) is None
    assert any(job_id == "job_upsert" and patch["status"] == "succeeded" for job_id, patch in supabase.updates)
    assert any(job_id == "job_tombstone" and patch["status"] == "succeeded" for job_id, patch in supabase.updates)


def test_process_projection_jobs_dead_letters_after_retry_limit():
    jobs = [
        {"id": "job_missing", "record_id": "missing_record", "job_type": "upsert", "status": "failed", "attempts": 2},
    ]
    supabase = _FakeProjectionSupabase(jobs)

    summary = process_brain_projection_jobs(
        supabase_client=supabase,
        record_repo=FakeBrainRecordRepository(),
        acl_repo=FakeBrainAclRepository(),
        graphiti_client=FakeGraphitiClient(),
        dead_letter_after=3,
    )

    assert summary == {"seen": 1, "succeeded": 0, "failed": 0, "dead_lettered": 1}
    assert any(job_id == "job_missing" and patch["status"] == "dead_letter" for job_id, patch in supabase.updates)

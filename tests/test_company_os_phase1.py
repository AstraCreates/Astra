import hashlib

import pytest

from backend import company_os, company_os_phase1 as phase1


def _setup(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    phase1.configure_internal_test_cohort("acme", root=root, metadata={"cohort": "fixed-test"})
    return root


def _fixture():
    return {
        "fixture_id": "launch-fixture",
        "activities": [
            {"type": "initiative.created", "id": "i1", "name": "Launch"},
            {"type": "squad.created", "id": "s1", "initiative_id": "i1", "name": "Growth"},
            {"type": "mission.created", "id": "m1", "initiative_id": "i1", "squad_id": "s1", "name": "Prepare launch"},
            {"type": "task.created", "id": "t1", "initiative_id": "i1", "squad_id": "s1", "mission_id": "m1", "name": "Draft brief", "state": "pending"},
            {"type": "task.updated", "task_id": "t1", "state": "done"},
            {"type": "artifact.created", "id": "a1", "name": "brief.md", "content": "ship it"},
        ],
    }


def test_registry_is_local_atomic_and_gates_dual_write(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    with pytest.raises(PermissionError):
        phase1.dual_write_legacy_activity("acme", {"type": "initiative", "id": "i1", "name": "Launch"}, root=root)
    entry = phase1.configure_internal_test_cohort("acme", root=root, metadata={"cohort": "fixed"})
    assert entry["enabled"] is True
    assert phase1.is_internal_test_cohort("acme", root=root)
    assert phase1.list_internal_test_cohort(root=root)[0]["company_id"] == "acme"
    assert phase1.configure_internal_test_cohort("acme", enabled=False, root=root)["enabled"] is False
    assert not phase1.is_internal_test_cohort("acme", root=root)


def test_dual_write_is_idempotent_and_records_audited_receipt(tmp_path):
    root = _setup(tmp_path)
    activity = {"type": "initiative.created", "id": "i1", "name": "Launch"}
    first = phase1.dual_write_legacy_activity("acme", activity, root=root)
    second = phase1.dual_write_legacy_activity("acme", activity, root=root)
    assert first["status"] == "written"
    assert second["status"] == "duplicate"
    state = company_os.get_company_os("acme", root=root)
    assert [item["initiative_id"] for item in state["initiatives"]] == ["i1"]
    assert state["artifacts"][0]["phase1_kind"] == "phase1_dual_write_receipt"
    assert len(company_os.replay_events("acme", root=root)) == 2


def test_assessment_checks_event_artifact_and_replayed_task_state(tmp_path):
    root = _setup(tmp_path)
    fixture = _fixture()
    result = phase1.dual_write_legacy_fixture("acme", fixture, root=root)
    assert result["written"] == len(fixture["activities"])
    assessment = phase1.assess_parity("acme", fixture, root=root)
    assert assessment["passed"] is True
    assert assessment["event_count"]["actual"] == len(fixture["activities"])
    assert assessment["record"]["phase1_kind"] == "phase1_parity_assessment"
    assert company_os.get_company_os("acme", root=root)["tasks"][0]["state"] == "done"


def test_assessment_reports_missing_receipts_hashes_and_task_state(tmp_path):
    root = _setup(tmp_path)
    fixture = _fixture()
    phase1.dual_write_legacy_fixture("acme", fixture, root=root)
    changed = _fixture()
    changed["activities"][-1]["content"] = "different content"
    changed["activities"][4]["state"] = "blocked"
    changed["activities"].append({"type": "message.created", "id": "missing", "message": "not written"})
    assessment = phase1.assess_parity("acme", changed, root=root)
    assert assessment["passed"] is False
    assert assessment["event_count"]["missing_activity_ids"] == ["message:missing"]
    assert assessment["artifact_content_hash"]["mismatches"]["a1"]["expected"] == hashlib.sha256(b"different content").hexdigest()
    assert assessment["replay_task_state"]["mismatches"]["t1"]["actual"] == "done"

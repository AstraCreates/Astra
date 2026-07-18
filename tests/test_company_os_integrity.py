import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import company_os, company_os_integrity


def _at(hours: int) -> str:
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "founder", "Acme", root=root)
    company_os.create_initiative("acme", "Launch", initiative_id="i1", root=root)
    return root


def test_recovery_drill_uses_snapshot_and_checksum_replay_and_records_evidence(tmp_path):
    root = _seed(tmp_path)

    drill = company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(0))

    assert drill["passed"] is True
    assert drill["snapshot_recovery_passed"] is True
    assert drill["checksum_replay_passed"] is True
    assert company_os_integrity.read_integrity_evidence("acme", root=root) == [drill]

    company_os.create_initiative("acme", "After snapshot", initiative_id="i2", root=root)
    event_path = next((root / "acme").glob("events-*.jsonl"))
    lines = event_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    event["payload"]["name"] = "tampered"
    event_path.write_text(lines[0] + "\n" + json.dumps(event) + "\n", encoding="utf-8")
    failed = company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(1))
    assert failed["passed"] is False
    assert "checksum" in failed["error"]


def test_phase_gate_requires_all_parity_and_a_full_failure_free_72_hour_soak(tmp_path):
    root = _seed(tmp_path)
    company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(0))
    company_os_integrity.record_parity_evidence(
        "acme",
        source_event_count=3,
        company_os_event_count=3,
        source_artifacts={"a1": "hash"},
        company_os_artifacts=[{"artifact_id": "a1", "content_hash": "hash"}],
        source_task_states={"t1": "done"},
        company_os_task_states=[{"task_id": "t1", "state": "done"}],
        root=root,
        observed_at=_at(72),
    )

    gate = company_os_integrity.evaluate_phase_1_gate("acme", root=root, now=_at(72))
    assert gate["phase_2_allowed"] is True
    assert gate["cutover_allowed"] is True
    assert company_os_integrity.require_phase_1_gate("acme", root=root, now=_at(72))["phase"] == 1

    company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(73))
    company_os_integrity.record_parity_evidence(
        "acme", source_event_count=4, company_os_event_count=3,
        source_artifacts={}, company_os_artifacts={}, source_task_states={}, company_os_task_states={},
        root=root, observed_at=_at(73),
    )
    blocked = company_os_integrity.evaluate_phase_1_gate("acme", root=root, now=_at(73))
    assert blocked["phase_2_allowed"] is False
    assert "event_count_parity" in blocked["blocked_reasons"]
    with pytest.raises(PermissionError, match="Phase 1 gate is closed"):
        company_os_integrity.require_phase_1_gate("acme", root=root, now=_at(73))


def test_failure_inside_soak_window_blocks_gate_even_when_latest_drill_passes(tmp_path):
    root = _seed(tmp_path)
    company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(0))
    company_os.create_initiative("acme", "After snapshot", initiative_id="i2", root=root)
    event_path = next((root / "acme").glob("events-*.jsonl"))
    original = event_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    event = json.loads(lines[-1])
    event["payload"]["name"] = "tampered"
    event_path.write_text(lines[0] + "\n" + json.dumps(event) + "\n", encoding="utf-8")
    company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(12))

    # Restore a valid event so the newest drill passes; the old failure remains evidence.
    event_path.write_text(original, encoding="utf-8")
    assert company_os_integrity.run_recovery_drill("acme", root=root, observed_at=_at(24))["passed"] is True
    company_os_integrity.record_parity_evidence(
        "acme", source_event_count=1, company_os_event_count=1,
        source_artifacts={}, company_os_artifacts={}, source_task_states={}, company_os_task_states={},
        root=root, observed_at=_at(72),
    )
    soak = company_os_integrity.evaluate_soak_eligibility("acme", root=root, now=_at(72))
    assert soak["eligible"] is False
    assert len(soak["recovery_failures"]) == 1

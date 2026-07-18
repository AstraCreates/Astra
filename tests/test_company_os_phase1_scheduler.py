import asyncio

from backend import company_os, company_os_phase1 as phase1
from backend.company_os_phase1_scheduler import run_phase_1_integrity_tick


def test_integrity_tick_only_processes_explicit_internal_cohort(tmp_path, monkeypatch):
    root = tmp_path / "workspace" / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    phase1.configure_internal_test_cohort("acme", root=root)
    monkeypatch.chdir(tmp_path)
    result = run_phase_1_integrity_tick()
    assert result[0]["company_id"] == "acme"
    assert result[0]["ok"] is True

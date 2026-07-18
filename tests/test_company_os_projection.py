import json
import subprocess
import sys
from pathlib import Path

from backend import company_os
from backend.company_os_projection import rebuild_all_company_projections, rebuild_company_projections


def _create_company(root: Path, company_id: str) -> None:
    company_os.create_company_os(company_id, "founder", f"{company_id} Inc", root=root)
    initiative = company_os.create_initiative(company_id, "Launch", initiative_id="initiative_1", root=root)
    squad = company_os.create_squad(company_id, initiative["initiative_id"], "Growth", squad_id="squad_1", root=root)
    company_os.create_task(company_id, initiative["initiative_id"], squad["squad_id"], "Draft brief", task_id="task_1", root=root)
    company_os.append_message(company_id, "Copilot is working", root=root, author="copilot")
    company_os.add_context_record(company_id, "voice", "direct", root=root)


def test_projection_rebuild_is_hashed_atomic_and_sourced_from_company_os(tmp_path):
    company_root = tmp_path / "company"
    projection_root = tmp_path / "projections"
    _create_company(company_root, "acme")

    first = rebuild_company_projections("acme", company_root=company_root, projection_root=projection_root)
    second = rebuild_company_projections("acme", company_root=company_root, projection_root=projection_root)
    assert first == second
    assert first["source"] == "company_os_local"
    assert first["projections"]["graphiti"]["record_count"] == 5

    directory = projection_root / "acme"
    supabase = json.loads((directory / "supabase.json").read_text())
    graphiti = [json.loads(line) for line in (directory / "graphiti.jsonl").read_text().splitlines()]
    assert supabase["tables"]["conversation"][0]["message"] == "Copilot is working"
    assert {record["entity_type"] for record in graphiti} == {"initiatives", "squads", "tasks", "conversation", "context_records"}
    assert all(len(record["content_hash"]) == 64 for record in graphiti)
    assert not any(path.suffix == ".tmp" for path in directory.iterdir())


def test_all_company_and_cli_rebuild_do_not_need_legacy_data(tmp_path):
    company_root = tmp_path / "company"
    projection_root = tmp_path / "projections"
    _create_company(company_root, "beta")
    _create_company(company_root, "acme")
    manifests = rebuild_all_company_projections(company_root=company_root, projection_root=projection_root)
    assert [manifest["company_id"] for manifest in manifests] == ["acme", "beta"]

    script = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_company_os_projections.py"
    result = subprocess.run(
        [sys.executable, str(script), "--company-id", "acme", "--company-root", str(company_root), "--projection-root", str(projection_root)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout)["company_id"] == "acme"

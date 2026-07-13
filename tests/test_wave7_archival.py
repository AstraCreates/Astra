import io
import zipfile
from pathlib import Path

from backend.control_plane.wave7_archival import (
    build_legacy_retirement_manifest,
    export_wave7_archival_snapshot,
)


def test_export_wave7_archival_snapshot_writes_manifest_and_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".astra/workflows").mkdir(parents=True)
    (tmp_path / ".astra/approvals").mkdir(parents=True)
    (tmp_path / ".astra/workflows/run.json").write_text('{"ok": true}')
    (tmp_path / ".astra/approvals/approval.json").write_text('{"approved": false}')

    result = export_wave7_archival_snapshot(output_path=str(tmp_path / "archive.zip"))

    assert result["ok"] is True
    archive_path = Path(result["path"])
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "workflows/run.json" in names
        assert "approvals/approval.json" in names
        assert "manifest.json" in names


def test_build_legacy_retirement_manifest_reports_existing_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    approvals_dir = tmp_path / ".astra/approvals"
    approvals_dir.mkdir(parents=True)
    (approvals_dir / "waiting.json").write_text("{}")

    manifest = build_legacy_retirement_manifest()

    approval_item = next(item for item in manifest["items"] if item["key"] == "process_local_approval_waiters")
    assert approval_item["exists"] is True
    assert approval_item["entries"] >= 1
    assert approval_item["retirement_ready"] is False
    assert manifest["ready_for_delete_last"] is False

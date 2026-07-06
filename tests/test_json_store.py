import json
from pathlib import Path

import pytest

from backend.core import json_store


def test_json_file_lock_is_per_path(tmp_path: Path):
    first = tmp_path / "a.json"
    same = tmp_path / "." / "a.json"
    other = tmp_path / "b.json"

    assert json_store.json_file_lock(first) is json_store.json_file_lock(same)
    assert json_store.json_file_lock(first) is not json_store.json_file_lock(other)


def test_write_json_atomic_preserves_existing_file_when_replace_fails(tmp_path: Path, monkeypatch):
    path = tmp_path / "store.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(src, dst):
        assert Path(src).exists()
        raise OSError("replace failed")

    monkeypatch.setattr(json_store.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        json_store.write_json_atomic(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob(".store.json.*.tmp")) == []


def test_read_json_quarantines_corrupt_file(tmp_path: Path):
    path = tmp_path / "store.json"
    path.write_text("{not-json", encoding="utf-8")

    assert json_store.read_json(path, {"fallback": True}) == {"fallback": True}
    assert not path.exists()

    quarantined = list(tmp_path.glob("store.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not-json"

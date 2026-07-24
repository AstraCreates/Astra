"""list_files() must serve from the cached index.json, not re-glob and
re-parse every file's full content on every call -- that full-directory
rescan running unconditionally on every list was the actual reason Library
pages were slow to load.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))


def test_list_files_does_not_rebuild_when_index_is_present(monkeypatch):
    from backend.library import store

    founder = "founder_perf"
    store.create_file(founder, "research", "a.md", "some content")
    store.create_file(founder, "research", "b.md", "more content")

    calls = []
    real_rebuild = store._rebuild_index

    def spy(founder_id):
        calls.append(founder_id)
        return real_rebuild(founder_id)

    monkeypatch.setattr(store, "_rebuild_index", spy)

    files = store.list_files(founder)

    assert len(files) == 2
    assert calls == [], "list_files must not rebuild the index when a cached one already exists"


def test_list_files_falls_back_to_rebuild_when_index_missing(tmp_path):
    from backend.library import store

    founder = "founder_recover"
    rec = store.create_file(founder, "research", "a.md", "content")
    # Simulate a corrupted/missing index -- the per-file record on disk is
    # still the source of truth and must be recoverable.
    store._index_path(founder).unlink()

    files = store.list_files(founder)

    assert len(files) == 1
    assert files[0]["id"] == rec["id"]
    # Recovery must persist so the next call is fast again.
    assert store._index_path(founder).exists()


def test_list_files_reflects_updates_and_deletes():
    from backend.library import store

    founder = "founder_crud"
    rec = store.create_file(founder, "research", "a.md", "v1")
    store.update_file(founder, rec["id"], content="v2")
    assert store.list_files(founder)[0]["size_bytes"] == len(b"v2")

    store.delete_file(founder, rec["id"])
    assert store.list_files(founder) == []

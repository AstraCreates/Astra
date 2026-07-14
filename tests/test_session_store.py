import json
import time

from backend.core.session_store import (
    append_event,
    events_path,
    get_session_meta,
    list_sessions,
    load_events,
    reconcile_orphaned_sessions,
    register_session,
    update_session_status,
)


def test_load_events_recovers_split_json_string(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    path = events_path("split_session")
    event = {
        "id": 1,
        "event": {
            "type": "agent_action_result",
            "agent": "legal",
            "result": {"body": "line one\nline two"},
        },
    }
    serialized = json.dumps(event, separators=(",", ":")).replace("\\n", "\n")
    path.write_text(serialized + "\n")

    loaded = load_events("split_session")

    assert loaded == [(1, event["event"])]


def test_update_session_status_persists_error_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    register_session("s1", "founder_1", "goal")
    update_session_status("s1", "error", error="provider timeout")
    meta = get_session_meta("s1")
    assert meta["status"] == "error"
    assert meta["error"] == "provider timeout"


def test_append_event_goal_error_populates_meta_error_field(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    register_session("s2", "founder_1", "goal")
    append_event("s2", 1, {"type": "goal_error", "error": "Run stopped by user."})
    meta = get_session_meta("s2")
    assert meta["status"] == "error"
    assert meta["error"] == "Run stopped by user."


def test_reconcile_orphaned_sessions_marks_stale_running_as_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    register_session("stale1", "founder_1", "goal")
    # Backdate created_at past the staleness window without touching status.
    meta_path_stale = tmp_path / "sessions" / "stale1" / "meta.json"
    meta = json.loads(meta_path_stale.read_text())
    meta["created_at"] = "2020-01-01T00:00:00Z"
    meta_path_stale.write_text(json.dumps(meta))
    from backend.core.session_store import _load_index, _save_index
    index = _load_index()
    index["stale1"]["created_at"] = "2020-01-01T00:00:00Z"
    _save_index(index)

    register_session("fresh1", "founder_1", "goal")  # created just now, must be left alone

    reconciled = reconcile_orphaned_sessions(stale_seconds=3600)

    assert reconciled == ["stale1"]
    stale_meta = get_session_meta("stale1")
    assert stale_meta["status"] == "error"
    assert "Orphaned" in stale_meta["error"]
    fresh_meta = get_session_meta("fresh1")
    assert fresh_meta["status"] == "running"


def test_reconcile_orphaned_sessions_leaves_terminal_sessions_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    register_session("done1", "founder_1", "goal")
    update_session_status("done1", "done")
    from backend.core.session_store import _load_index, _save_index
    index = _load_index()
    index["done1"]["created_at"] = "2020-01-01T00:00:00Z"
    _save_index(index)

    reconciled = reconcile_orphaned_sessions(stale_seconds=3600)

    assert reconciled == []
    assert get_session_meta("done1")["status"] == "done"

import json

from backend.core.session_store import events_path, load_events


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

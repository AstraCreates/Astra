import pytest

from backend import copilot


@pytest.mark.asyncio
async def test_copilot_library_tools_create_read_update_append_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_library_copilot"
    session_id = "sess_library"

    created = await copilot._tool_create_library_item(
        founder_id,
        session_id,
        {"filename": "operator-brief.md", "department": "ops", "content": "Initial brief."},
    )
    assert created["ok"] is True
    file_id = created["file"]["id"]
    assert created["file"]["source_tag"] == "copilot"
    assert created["file"]["source_session_id"] == session_id

    listed = await copilot._tool_get_library(founder_id, session_id, {})
    assert listed["files"][0]["id"] == file_id

    read = await copilot._tool_read_library_item(founder_id, session_id, {"file_id": file_id})
    assert read["content"] == "Initial brief."

    updated = await copilot._tool_update_library_item(
        founder_id,
        session_id,
        {"file_id": file_id, "content": "Revised brief.", "is_canonical": True},
    )
    assert updated["ok"] is True
    assert updated["file"]["content"] == "Revised brief."
    assert updated["file"]["is_canonical"] is True

    appended = await copilot._tool_append_library_item(
        founder_id,
        session_id,
        {"file_id": file_id, "heading": "Next", "text": "Add this section."},
    )
    assert appended["ok"] is True
    assert "## Next\nAdd this section." in appended["file"]["content"]

    refused = await copilot._tool_delete_library_item(founder_id, session_id, {"file_id": file_id})
    assert refused["ok"] is False
    assert "confirm_delete" in refused["error"]

    deleted = await copilot._tool_delete_library_item(
        founder_id,
        session_id,
        {"file_id": file_id, "confirm_delete": True},
    )
    assert deleted == {"ok": True, "file_id": file_id, "deleted": True}

    missing = await copilot._tool_read_library_item(founder_id, session_id, {"file_id": file_id})
    assert missing["ok"] is False

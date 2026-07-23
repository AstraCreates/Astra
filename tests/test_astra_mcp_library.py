import json

from backend import astra_mcp


def _structured(response: dict) -> dict:
    assert response["jsonrpc"] == "2.0"
    assert "error" not in response
    return response["result"]["structuredContent"]


def _call(name: str, arguments: dict | None = None) -> dict:
    return _structured(astra_mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }))


def test_astra_mcp_exposes_library_tools():
    response = astra_mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in response["result"]["tools"]}

    assert {
        "astra_library_list",
        "astra_library_read",
        "astra_library_create",
        "astra_library_update",
        "astra_library_append",
        "astra_library_delete",
    }.issubset(names)


def test_astra_mcp_library_crud_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_library_mcp"

    created = _call("astra_library_create", {
        "founder_id": founder_id,
        "filename": "voice-notes.md",
        "department": "copilot",
        "content": "Original notes.",
        "is_canonical": True,
    })
    assert created["ok"] is True
    file_id = created["file"]["id"]
    assert created["file"]["brain_record_id"]

    listed = _call("astra_library_list", {"founder_id": founder_id})
    assert listed["count"] == 1
    assert listed["files"][0]["id"] == file_id
    assert "content" not in listed["files"][0]

    read = _call("astra_library_read", {"founder_id": founder_id, "file_id": file_id})
    assert read["file"]["content"] == "Original notes."

    updated = _call("astra_library_update", {
        "founder_id": founder_id,
        "file_id": file_id,
        "content": "Revised notes.",
        "filename": "voice-brief.md",
    })
    assert updated["ok"] is True
    assert updated["file"]["filename"] == "voice-brief.md"
    assert updated["file"]["content"] == "Revised notes."

    appended = _call("astra_library_append", {
        "founder_id": founder_id,
        "file_id": file_id,
        "heading": "Follow-up",
        "text": "Astra should read this too.",
    })
    assert "## Follow-up\nAstra should read this too." in appended["file"]["content"]

    refused = _call("astra_library_delete", {"founder_id": founder_id, "file_id": file_id})
    assert refused["ok"] is False
    assert "confirm_delete" in refused["error"]

    deleted = _call("astra_library_delete", {
        "founder_id": founder_id,
        "file_id": file_id,
        "confirm_delete": True,
    })
    assert deleted["ok"] is True
    assert deleted["deleted"] is True

    missing = _call("astra_library_read", {"founder_id": founder_id, "file_id": file_id})
    assert missing["ok"] is False


def test_astra_mcp_library_result_is_mcp_wrapped(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    response = astra_mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "astra_library_create",
            "arguments": {"founder_id": "founder_wrapped", "filename": "x.md", "content": "x"},
        },
    })

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert response["result"]["structuredContent"]["file"]["filename"] == "x.md"

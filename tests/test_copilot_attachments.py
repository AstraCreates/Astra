from backend.copilot import _attachment_context_block, _normalize_attachments


def test_copilot_normalizes_attachment_context_with_bounds():
    attachments = [
        {"filename": "plan.md", "kind": "text", "content": "x" * 7000, "library_id": "abc"},
        {"filename": "empty.txt", "kind": "text", "content": ""},
    ]

    normalized = _normalize_attachments(attachments, max_chars_each=100)

    assert len(normalized) == 1
    assert normalized[0]["filename"] == "plan.md"
    assert normalized[0]["content"] == "x" * 100
    assert normalized[0]["truncated"] is True
    assert normalized[0]["library_id"] == "abc"


def test_copilot_attachment_context_block_includes_file_metadata():
    block = _attachment_context_block([
        {
            "filename": "deck.pdf",
            "kind": "pdf",
            "library_id": "file_123",
            "truncated": True,
            "content": "Pitch deck text",
        }
    ])

    assert "UPLOADED FILE CONTEXT FOR THIS TURN" in block
    assert "deck.pdf (pdf), library_id=file_123, truncated" in block
    assert "Pitch deck text" in block

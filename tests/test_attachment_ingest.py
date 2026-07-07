from backend.tools.attachment_ingest import MAX_CHARS, ingest_attachment


def test_ingest_text_attachment_cleans_and_reports_size():
    result = ingest_attachment("notes.txt", "text/plain", b"\xef\xbb\xbfHello  \n\n\n\nworld\x00")

    assert result["kind"] == "text"
    assert result["content"] == "Hello\n\n\nworld"
    assert result["size_bytes"] == len(b"\xef\xbb\xbfHello  \n\n\n\nworld\x00")
    assert result["truncated"] is False


def test_ingest_empty_text_attachment_returns_meaningful_error():
    result = ingest_attachment("empty.txt", "text/plain", b"\x00\n  ")

    assert result["kind"] == "text"
    assert result["content"] == ""
    assert result["error"] == "This file did not contain readable text."


def test_ingest_text_attachment_truncates_large_content():
    result = ingest_attachment("large.md", "text/markdown", b"a" * (MAX_CHARS + 20))

    assert result["kind"] == "text"
    assert result["truncated"] is True
    assert len(result["content"]) > MAX_CHARS
    assert result["content"].endswith("\n…[truncated]")

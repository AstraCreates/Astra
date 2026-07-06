from backend.core.agent import _format_tool_result


def test_search_and_fetch_context_dedupes_repeated_source_content():
    seen: dict[str, object] = {}
    result = {
        "query": "competitor pricing",
        "results": [
            {
                "title": "Acme Pricing",
                "url": "https://example.com/pricing",
                "snippet": "Pricing starts at $20.",
                "content": "FULL PAGE CONTENT " + ("pricing details " * 800),
            }
        ],
        "sources": [{"title": "Acme Pricing", "url": "https://example.com/pricing"}],
    }

    first = _format_tool_result("search_and_fetch", result, seen)
    second = _format_tool_result("search_and_fetch", result, seen)

    assert "FULL PAGE CONTENT" in first
    assert "https://example.com/pricing" in first
    assert "FULL PAGE CONTENT" not in second
    assert "duplicate source omitted" in second
    assert "Pricing starts at $20." in second
    assert "https://example.com/pricing" in second


def test_tool_context_strips_large_base64_but_keeps_image_metadata():
    raw_b64 = "A" * 12_000
    result = {
        "prompt": "Cinematic ad image with product in frame",
        "base64": raw_b64,
        "url": "https://img.example/ad.png",
        "nested": {"image": f"data:image/png;base64,{raw_b64}"},
    }

    formatted = _format_tool_result("generate_ad_image", result, {})

    assert raw_b64 not in formatted
    assert "base64 omitted from agent context" in formatted
    assert "Cinematic ad image" in formatted
    assert "https://img.example/ad.png" in formatted

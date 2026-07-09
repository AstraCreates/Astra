from backend.core.agent import AgentContext
from backend.specialists.research import _make_resilient_research_tool


def _ctx():
    return AgentContext(goal="Validate the market for Goon", founder_id="f1", session_id="s1", shared={})


def test_resilient_search_and_fetch_preserves_url_kwarg():
    """Real production bug: a model call search_and_fetch(url=..., max_results=8)
    got its url silently overwritten with an unrelated auto-generated query
    (the raw task instruction text) because the backfill only checked for a
    missing `query` key, not other content-bearing kwargs like `url`."""
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "search_and_fetch", [_ctx()])
    wrapped(url="https://www.g2.com/products/goon/reviews", max_results=8)

    assert captured["url"] == "https://www.g2.com/products/goon/reviews"
    assert "query" not in captured


def test_resilient_search_and_fetch_still_backfills_when_truly_empty():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "search_and_fetch", [_ctx()])
    wrapped()

    assert captured.get("query")

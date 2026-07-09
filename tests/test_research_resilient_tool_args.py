from backend.core.agent import AgentContext
from backend.specialists import research
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


def test_resilient_pipeline_forces_deep_research(monkeypatch):
    calls = []

    def fake_pipeline(*, topic, focus, max_results_each=8):
        calls.append(("pipeline", topic, focus, max_results_each))
        return {
            "topic": topic,
            "focus": focus,
            "queries": [f"{topic} query 1", f"{topic} query 2"],
            "sources": [{"url": "https://discovery.example"}],
            "combined_formatted": "shallow discovery",
        }

    def fake_deep(queries):
        calls.append(("deep", list(queries)))
        return {
            "formatted": "deep synthesis",
            "sources": [{"url": "https://deep.example"}],
        }

    monkeypatch.setattr(research, "run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(research, "deep_research", fake_deep)

    wrapped = _make_resilient_research_tool(lambda **kwargs: None, "run_research_pipeline", [_ctx()], "research_customers")
    result = wrapped()

    assert calls == [
        ("pipeline", "Validate the market for Goon", "customers", 8),
        ("deep", ["Validate the market for Goon query 1", "Validate the market for Goon query 2"]),
    ]
    assert result["deep_research_used"] is True
    assert result["combined_formatted"] == "deep synthesis"
    assert result["sources"] == [{"url": "https://deep.example"}]

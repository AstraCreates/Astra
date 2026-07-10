from backend.core.agent import AgentContext
from backend.specialists.research import _make_resilient_research_tool, build_research_agent


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


def test_resilient_deep_research_backfills_missing_queries():
    """Real production bug: research_customers called deep_research() with no
    queries at all, hitting deep_research's hard "queries required" error
    repeatedly with zero backfill — unlike every other research tool
    (sonar_research, search_and_fetch, etc.), deep_research had no resilience
    wrapping despite the role prompt now telling agents to call it directly."""
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "deep_research", [_ctx()])
    wrapped()

    assert captured.get("queries")
    assert isinstance(captured["queries"], list)


def test_resilient_deep_research_converts_singular_query_kwarg():
    """The model sometimes passes the singular `query` string every other
    research tool uses instead of deep_research's actual plural `queries`
    list — recover that real intent instead of discarding it."""
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "deep_research", [_ctx()])
    wrapped(query="Goon competitor pricing 2025")

    assert captured["queries"] == ["Goon competitor pricing 2025"]
    assert "query" not in captured


def test_resilient_deep_research_preserves_real_queries_list():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "deep_research", [_ctx()])
    wrapped(queries=["real question one", "real question two"])

    assert captured["queries"] == ["real question one", "real question two"]


def test_resilient_news_search_backfills_empty_query():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(fake_tool, "news_search", [_ctx()], "research_gtm")
    wrapped()

    assert captured.get("query")


def test_resilient_pipeline_backfills_topic_from_founder_goal_not_lane_boilerplate():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    ctx = AgentContext(
        goal=(
            "Validate the market, target customer, pain severity, buying trigger.\n\n"
            "Founder goal: Business profile:\n"
            "Goon is a collaborative project management platform for remote product teams at early-stage startups.\n\n"
            "---\n"
            "Company/project name: Goon\n\n"
            "a collaborative project management platform for remote product teams at early-stage startups"
        ),
        founder_id="f1",
        session_id="s1",
        shared={},
    )

    wrapped = _make_resilient_research_tool(fake_tool, "run_research_pipeline", [ctx], "research_competitors")
    wrapped()

    assert captured["focus"] == "competitors"
    assert captured["topic"].startswith("Goon")
    assert "pain severity" not in captured["topic"]


def test_lane_specific_pipeline_overrides_wrong_focus_from_model():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(
        fake_tool,
        "run_research_pipeline",
        [_ctx()],
        "research_customers",
    )
    wrapped(topic="AtlasHaven", focus="market")

    assert captured["focus"] == "customers"


def test_general_research_pipeline_keeps_explicit_focus_choice():
    captured = {}

    def fake_tool(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    wrapped = _make_resilient_research_tool(
        fake_tool,
        "run_research_pipeline",
        [_ctx()],
        "research",
    )
    wrapped(topic="AtlasHaven", focus="competitors")

    assert captured["focus"] == "competitors"


def test_research_customers_toolset_stays_narrow():
    agent = build_research_agent("research_customers")

    assert "deep_research" in agent.tools
    assert "build_research_queries" in agent.tools
    assert "run_research_pipeline" in agent.tools
    assert "search_and_fetch" not in agent.tools
    assert "fetch_and_read" not in agent.tools
    assert "batch_search" not in agent.tools
    assert "news_search" not in agent.tools


def test_research_gtm_toolset_stays_narrow_but_keeps_pipeline():
    agent = build_research_agent("research_gtm")

    assert "deep_research" in agent.tools
    assert "build_research_queries" in agent.tools
    assert "run_research_pipeline" in agent.tools
    assert "search_and_fetch" not in agent.tools
    assert "fetch_and_read" not in agent.tools
    assert "batch_search" not in agent.tools


def test_research_toolset_prefers_pipeline_and_deep_research_without_raw_fetch_loops():
    agent = build_research_agent("research")

    assert "run_research_pipeline" in agent.tools
    assert "deep_research" in agent.tools
    assert "build_research_queries" in agent.tools
    assert "search_and_fetch" not in agent.tools
    assert "fetch_and_read" not in agent.tools
    assert "batch_search" not in agent.tools

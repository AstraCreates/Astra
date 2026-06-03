from backend.tools import browser_research


def test_batch_search_aggregates_unique_sources(monkeypatch):
    def fake_search_and_fetch(query, max_results):
        return {
            "query": query,
            "total": 2,
            "formatted": f"formatted {query}",
            "sources": [
                {"title": "Shared", "url": "https://example.com/report"},
                {"title": query, "url": f"https://example.com/{query}"},
            ],
        }

    monkeypatch.setattr(browser_research, "search_and_fetch", fake_search_and_fetch)

    result = browser_research.batch_search(["market", "pricing"], max_results_each=3)

    assert result["queries_run"] == 2
    assert set(result["results_by_query"]) == {"market", "pricing"}
    assert [s["url"] for s in result["sources"]] == [
        "https://example.com/report",
        "https://example.com/market",
        "https://example.com/pricing",
    ]


def test_normalize_url_strips_tracking_params():
    assert (
        browser_research._normalize_url("https://example.com/page?utm_source=x&keep=1&fbclid=abc#section")
        == "https://example.com/page?keep=1"
    )


def test_build_research_queries_market_focus():
    result = browser_research.build_research_queries("AI sales copilot", focus="market")

    assert result["recommended_tool"] == "batch_search"
    assert len(result["queries"]) >= 5
    assert any("TAM" in query for query in result["queries"])
    assert any("pricing" in query.lower() for query in result["queries"])
    assert all("AI sales copilot" in query for query in result["queries"])


def test_build_research_queries_competitor_focus():
    result = browser_research.build_research_queries("AI sales copilot", focus="competitors")

    joined = "\n".join(result["queries"]).lower()
    assert "competitors" in joined or "alternatives" in joined
    assert "g2.com" in joined
    assert "pricing" in joined


def test_build_research_queries_requires_topic():
    result = browser_research.build_research_queries("   ", focus="market")

    assert result["queries"] == []
    assert result["error"] == "topic is required"


def test_run_research_pipeline_uses_query_plan_and_batch_search(monkeypatch):
    calls = {}

    def fake_batch_search(queries, max_results_each):
        calls["queries"] = queries
        calls["max_results_each"] = max_results_each
        sources = [
            {"title": str(i), "url": f"https://source{i}.example/report"}
            for i in range(8)
        ]
        return {
            "queries_run": len(queries),
            "results_by_query": {query: {"total": 1, "formatted": query} for query in queries},
            "sources": sources,
            "combined_formatted": "evidence",
        }

    monkeypatch.setattr(browser_research, "batch_search", fake_batch_search)

    result = browser_research.run_research_pipeline("AI sales copilot", focus="market", max_results_each=4)

    assert result["focus"] == "market"
    assert result["queries_run"] == len(calls["queries"])
    assert calls["max_results_each"] == 4
    assert result["source_count"] == 8
    assert result["coverage"]["ready"] is True
    assert result["coverage"]["gaps"] == []
    assert "Synthesize findings" in result["next_step"]


def test_run_research_pipeline_reports_coverage_gaps(monkeypatch):
    def fake_batch_search(queries, max_results_each):
        return {
            "queries_run": len(queries),
            "results_by_query": {queries[0]: {"total": 1, "formatted": queries[0]}},
            "sources": [{"title": "Thin", "url": "https://same.example/report"}],
            "combined_formatted": "thin evidence",
        }

    monkeypatch.setattr(browser_research, "batch_search", fake_batch_search)

    result = browser_research.run_research_pipeline("AI sales copilot", focus="market")

    assert result["coverage"]["ready"] is False
    assert "source_count_below_8" in result["coverage"]["gaps"]
    assert "domain_diversity_below_4" in result["coverage"]["gaps"]
    assert "query_coverage_below_5" in result["coverage"]["gaps"]
    assert "Evidence is thin" in result["next_step"]

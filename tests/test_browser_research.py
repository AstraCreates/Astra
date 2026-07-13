from backend.tools import browser_research
from backend.config import settings
import types
import sys
import threading
import time


def test_search_and_fetch_url_kwarg_routes_to_fetch_and_read(monkeypatch):
    """Real production bug: the model called search_and_fetch(url=..., max_results=8)
    28 times in a row (confusing it with fetch_and_read). Since search_and_fetch
    had no `url` param, the arg silently got dropped by the tool-call filter and
    a generic auto-query was substituted instead — returning irrelevant results
    every single time. search_and_fetch must accept `url` and route it straight
    to fetch_and_read instead of losing the model's actual intent."""
    calls = []

    def fake_fetch_and_read(url):
        calls.append(url)
        return {"url": url, "title": "G2 Reviews", "content": "real page content"}

    monkeypatch.setattr(browser_research, "fetch_and_read", fake_fetch_and_read)

    result = browser_research.search_and_fetch(url="https://www.g2.com/products/goon/reviews", max_results=8)

    assert calls == ["https://www.g2.com/products/goon/reviews"]
    assert result["routed_to"] == "fetch_and_read"
    assert result["results"][0]["content"] == "real page content"


def test_search_and_fetch_still_requires_query_or_url():
    result = browser_research.search_and_fetch()
    assert "error" in result


def test_search_and_fetch_list_query_routes_to_batch_search(monkeypatch):
    calls = []

    def fake_batch_search(queries, max_results_each):
        calls.append((list(queries), max_results_each))
        return {"queries_run": len(queries), "results_by_query": {}, "sources": [], "combined_formatted": ""}

    monkeypatch.setattr(browser_research, "batch_search", fake_batch_search)

    result = browser_research.search_and_fetch(
        query=[" competitor pricing SaaS ", "competitor pricing saas", "gtm channels for saas consultancy"],
        max_results=6,
    )

    assert calls == [(["competitor pricing SaaS", "gtm channels for saas consultancy"], 6)]
    assert result["queries_run"] == 2


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


def test_batch_search_dedupes_repeated_queries_and_normalizes_source_urls(monkeypatch):
    calls = []

    def fake_search_and_fetch(query, max_results):
        calls.append((query, max_results))
        return {
            "query": query,
            "total": 1,
            "formatted": f"formatted {query}",
            "sources": [
                {"title": "Shared", "url": "https://example.com/report/?utm_source=newsletter"},
                {"title": query, "url": f"https://example.com/{query}?fbclid=123"},
            ],
        }

    monkeypatch.setattr(browser_research, "search_and_fetch", fake_search_and_fetch)

    result = browser_research.batch_search([" Market  ", "market", "pricing", "pricing  "], max_results_each=4)

    assert calls == [("Market", 4), ("pricing", 4)]
    assert list(result["results_by_query"]) == ["Market", "pricing"]
    assert [source["url"] for source in result["sources"]] == [
        "https://example.com/report",
        "https://example.com/Market",
        "https://example.com/pricing",
    ]


def test_normalize_url_strips_tracking_params():
    assert (
        browser_research._normalize_url("https://example.com/page?utm_source=x&keep=1&fbclid=abc#section")
        == "https://example.com/page?keep=1"
    )


def test_normalize_url_and_query_coerce_dict_inputs():
    assert (
        browser_research._normalize_url({"url": "https://example.com/page?utm_source=x&keep=1"})
        == "https://example.com/page?keep=1"
    )
    assert browser_research._canonicalize_search_query({"query": "AI sales copilot pricing"}) == "AI sales copilot pricing"


def test_canonicalize_search_query_compacts_natural_language_prompts():
    query = (
        "Identify the ICP for Goon: who are the real buyers (job titles, company size, stage, geography) "
        "for a collaborative project management platform for remote product teams at early-stage startups "
        "and small tech agencies"
    )

    normalized = browser_research._canonicalize_search_query(query)

    assert normalized.startswith("the real buyers")
    assert len(normalized) <= 180
    assert "(" not in normalized


def test_compact_research_evidence_prefers_late_relevant_numeric_sections():
    content = (
        ("Intro filler about generic collaboration workflows without specifics. " * 50)
        + "\n\n2025 pricing benchmark: enterprise plans start at $499/month with 18% YoY growth and 12% market share.\n\n"
        + ("Closing filler about team rituals and documentation habits. " * 30)
    )

    compacted = browser_research._compact_research_evidence(
        content,
        "enterprise pricing benchmark market share growth",
        max_chars=500,
    )

    assert "enterprise plans start at $499/month" in compacted
    assert "12% market share" in compacted
    assert len(compacted) <= 500


def test_search_and_fetch_formats_relevant_slice_not_just_prefix(monkeypatch):
    filler = "Intro filler about general software collaboration practices. " * 80
    late_signal = (
        "2025 TAM estimate is $3.2B, CAGR is 18%, and benchmark pricing lands at $299 per seat annually."
    )

    monkeypatch.setattr(
        browser_research,
        "_robust_search",
        lambda query, max_results: [{"href": "https://example.com/report", "title": "Report", "body": "Snippet"}],
    )
    monkeypatch.setattr(
        browser_research,
        "fetch_and_read",
        lambda url: {"url": url, "title": "Report", "content": filler + late_signal},
    )

    result = browser_research.search_and_fetch("pricing benchmark TAM CAGR", max_results=3)

    assert late_signal in result["formatted"]
    assert "Intro filler" not in result["formatted"]


def test_sonar_research_tolerates_dict_shaped_followup_queries(monkeypatch):
    calls = []

    def fake_batch_search(queries, max_results_each):
        calls.append(list(queries))
        return {
            "queries_run": len(queries),
            "results_by_query": {
                query: {
                    "total": 1,
                    "formatted": f"Query: {query}",
                    "sources": [{"title": f"Source for {query}", "url": f"https://example.com/{str(query).replace(' ', '-')}"}],
                }
                for query in queries
            },
            "sources": [{"title": "Shared", "url": "https://example.com/shared"}],
            "combined_formatted": "\n".join(map(str, queries)),
        }

    synth_outputs = iter([
        {
            "learnings": ["Initial finding"],
            "directions": [{"query": "enterprise pricing custom quote SaaS"}],
            "summary": "Round one findings",
        },
        {"queries": [{"query": "enterprise pricing custom quote SaaS"}]},
        {
            "learnings": ["Enterprise plans are custom quote"],
            "directions": [],
            "summary": "Round two findings",
        },
        {"answers": [
            {"query": "AI sales copilot market size", "answer": "Answer one", "support": ["a"]},
        ]},
    ])

    def fake_research_llm_json(prompt, max_tokens=900):
        return next(synth_outputs)

    monkeypatch.setattr(browser_research, "_crw_batch_search", fake_batch_search)
    monkeypatch.setattr(browser_research, "_research_llm_json", fake_research_llm_json)

    result = browser_research.sonar_research(["AI sales copilot market size"])

    assert calls[0] == ["AI sales copilot market size"]
    assert result["queries_run"] == 1
    assert result["results_by_query"]["AI sales copilot market size"]["answer"] == "Answer one"


def test_deep_research_uses_single_round_for_large_long_query_sets(monkeypatch):
    batch_calls = []

    def fake_batch_search(queries, max_results_each):
        batch_calls.append((list(queries), max_results_each))
        return {
            "queries_run": len(queries),
            "results_by_query": {
                query: {
                    "total": 1,
                    "formatted": f"Query: {query}",
                    "sources": [{"title": query, "url": f"https://example.com/{idx}"}],
                }
                for idx, query in enumerate(queries)
            },
            "sources": [{"title": "Shared", "url": "https://example.com/shared"}],
            "combined_formatted": "\n".join(queries),
        }

    llm_outputs = iter([
        {"learnings": ["Initial finding"], "directions": ["unused follow-up"], "summary": "Round one"},
        {"answers": [
            {"query": query, "answer": "Answer", "support": ["evidence"]}
            for query in [
                f"Identify the pricing benchmark for collaborative PM tools query {i}: collaborative PM pricing benchmark query {i} "
                f"for remote product teams at startups and agencies with examples and context"
                for i in range(6)
            ]
        ]},
    ])

    def fake_research_llm_json(prompt, max_tokens=900):
        return next(llm_outputs)

    monkeypatch.setattr(browser_research, "_crw_batch_search", fake_batch_search)
    monkeypatch.setattr(browser_research, "_research_llm_json", fake_research_llm_json)

    queries = [
        f"Identify the pricing benchmark for collaborative PM tools query {i}: collaborative PM pricing benchmark query {i} "
        f"for remote product teams at startups and agencies with examples and context"
        for i in range(6)
    ]
    result = browser_research.deep_research(queries)

    assert len(batch_calls) == 1
    assert batch_calls[0][1] == 5
    assert result["queries_run"] == 6


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


def test_build_research_queries_turns_product_pitch_into_resource_topic():
    result = browser_research.build_research_queries(
        "Goon is a $20/month subscription providing frontier and SOTA AI models replacing multiple subscriptions",
        focus="competitors",
    )

    assert "Goon" not in result["resource_topic"]
    assert "AI model aggregation" in result["resource_topic"]
    assert all("Goon" not in query for query in result["queries"])


def test_native_research_pass_uses_native_web_plugin_and_extracts_citations(monkeypatch):
    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(
                content="Resource evidence with citations.",
                annotations=[{"type": "url_citation", "url_citation": {"url": "https://example.com/report", "title": "Report"}}],
            )
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *args, **kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions())))
    monkeypatch.setattr("backend.core.key_rotator.get_openrouter_key", lambda: "test-key")
    monkeypatch.setattr("backend.core.llm_cache.openrouter_extra_body", lambda model, extra=None: extra or {})

    result = browser_research._native_research_pass(
        "AI model aggregation platforms",
        "competitors",
        ["AI model aggregation platform competitors pricing"],
    )

    assert captured["model"] == settings.native_research_model
    assert captured["extra_body"]["plugins"] == [{"id": "web", "engine": "native"}]
    assert result["sources"] == [{"id": "src_1", "url": "https://example.com/report", "title": "Report"}]
    assert result["results_by_query"]["AI model aggregation platform competitors pricing"]["citations"] == ["src_1"]


def test_build_research_queries_requires_topic():
    result = browser_research.build_research_queries("   ", focus="market")

    assert result["queries"] == []
    assert result["error"] == "topic is required"


def test_run_research_pipeline_uses_query_plan_and_batch_search(monkeypatch):
    monkeypatch.setattr(settings, "native_research_enabled", False)
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
    monkeypatch.setattr(settings, "native_research_enabled", False)
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


def test_to_research_result_writes_evidence_artifacts_when_run_context_present(monkeypatch):
    written = []

    def fake_write(run_id, step_id, evidence):
        written.append((run_id, step_id, evidence["evidence_id"]))

    monkeypatch.setattr(browser_research, "write_evidence_artifact", fake_write)

    result = browser_research.to_research_result(
        "query_1",
        "What is the pricing?",
        {
            "total": 1,
            "answer": "Pricing starts at $20.",
            "sources": [{"title": "Pricing", "url": "https://example.com/pricing"}],
        },
        run_id="run_123",
        step_id="step_456",
    )

    assert len(result["evidence"]) == 1
    assert written == [("run_123", "step_456", result["evidence"][0]["evidence_id"])]


def test_sonar_research_preserves_contract_with_recursive_synthesis(monkeypatch):
    calls = []

    def fake_batch_search(queries, max_results_each):
        calls.append(list(queries))
        return {
            "queries_run": len(queries),
            "results_by_query": {
                query: {
                    "total": 1,
                    "formatted": f"Query: {query}\n### Source\nURL: https://example.com/{query.replace(' ', '-')}\nFact for {query}",
                    "sources": [{"title": f"Source for {query}", "url": f"https://example.com/{query.replace(' ', '-')}"}],
                }
                for query in queries
            },
            "sources": [
                {"title": f"Source {index}", "url": f"https://example.com/{query.replace(' ', '-')}"}
                for index, query in enumerate(queries, start=1)
            ],
            "combined_formatted": "\n".join(queries),
        }

    synth_outputs = iter([
        {
            "learnings": ["Market is growing 18% CAGR", "Competitor pricing starts at $99/mo"],
            "directions": ["Need better evidence on enterprise pricing", "Find category leader market share"],
            "summary": "Round one findings",
        },
        {"queries": ["enterprise pricing custom quote SaaS", "category leader market share 2025"]},
        {
            "learnings": ["Enterprise plans are custom quote", "Leader has 12% market share"],
            "directions": [],
            "summary": "Round two findings",
        },
        {"answers": [
            {"query": "AI sales copilot market size", "answer": "Answer one", "support": ["a"]},
            {"query": "AI sales copilot competitor pricing", "answer": "Answer two", "support": ["b"]},
        ]},
    ])

    def fake_research_llm_json(prompt, max_tokens=900):
        return next(synth_outputs)

    monkeypatch.setattr(browser_research, "_crw_batch_search", fake_batch_search)
    monkeypatch.setattr(browser_research, "_research_llm_json", fake_research_llm_json)

    result = browser_research.sonar_research(["AI sales copilot market size", "AI sales copilot competitor pricing"])

    assert len(calls) == 2
    assert result["queries_run"] == 2
    assert set(result["results_by_query"]) == {
        "AI sales copilot market size",
        "AI sales copilot competitor pricing",
    }
    for value in result["results_by_query"].values():
        assert set(value) == {"answer", "citations", "claims", "total"}
        assert isinstance(value["answer"], str)
        assert isinstance(value["citations"], list)
        assert isinstance(value["claims"], list)
        assert isinstance(value["total"], int)
    assert result["combined_formatted"].count("## ") == 2
    assert result["sources"]


def test_crw_search_and_fetch_parses_response(monkeypatch):
    class FakeResponse:
        def json(self):
            return {
                "success": True,
                "data": [
                    {"url": "https://example.com/report?utm_source=x", "title": "Report", "snippet": "A report.", "markdown": "# Report\nReal content here."},
                    {"url": "https://example.com/no-content", "title": "No Content", "snippet": "Just a blurb."},
                ],
            }

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=lambda url, json, timeout: FakeResponse()))

    result = browser_research._crw_search_and_fetch("test query", max_results=5)

    assert result["query"] == "test query"
    assert result["total"] == 2
    # tracking params stripped by _normalize_url
    assert result["sources"][0]["url"] == "https://example.com/report"
    assert "Real content here" in result["formatted"]
    assert "[snippet only] Just a blurb." in result["formatted"]


def test_crw_search_and_fetch_parses_nested_results_response(monkeypatch):
    class FakeResponse:
        def json(self):
            return {
                "success": True,
                "data": {
                    "results": [
                        {
                            "url": "https://example.com/nested",
                            "title": "Nested Example",
                            "markdown": "Nested markdown body",
                            "snippet": "Nested snippet",
                        }
                    ]
                },
            }

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=lambda url, json, timeout: FakeResponse()))

    result = browser_research._crw_search_and_fetch("nested query", max_results=5)

    assert result["total"] == 1
    assert result["results"][0]["url"] == "https://example.com/nested"
    assert result["sources"] == [{"title": "Nested Example", "url": "https://example.com/nested"}]


def test_crw_search_and_fetch_handles_request_failure(monkeypatch):
    """On a crw request failure, _crw_search_and_fetch falls back to
    _ddgs_fallback_search (real, intentional resilience — see the "falling
    back to DDGS" log line) rather than just returning empty. That fallback
    itself makes a real network call unless mocked directly, which the
    previous version of this test didn't do — it only stubbed `httpx`, so
    _ddgs_fallback_search's own live DDGS search ran for real and returned
    real (non-empty) results, making `total == 0` a false assumption rather
    than the actual contract. Mock the fallback directly so the test verifies
    the real behavior (fallback invoked, its result returned, error recorded)
    without depending on network."""
    def raise_error(*args, **kwargs):
        raise ConnectionError("crw unreachable")

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=raise_error))
    monkeypatch.setattr(
        browser_research, "_ddgs_fallback_search",
        lambda query, max_results: {"query": query, "results": [], "formatted": "", "total": 0, "sources": []},
    )

    result = browser_research._crw_search_and_fetch("test query")

    assert result["total"] == 0
    assert result["results"] == []
    assert result["error"] == "crw unreachable"


def test_crw_search_and_fetch_uses_bounded_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        def json(self):
            return {
                "success": True,
                "data": [{"url": "https://example.com/report", "title": "Report", "snippet": "A report.", "markdown": "content"}],
            }

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=fake_post))

    result = browser_research._crw_search_and_fetch("timeout query", max_results=5)

    assert result["total"] == 1
    assert captured["timeout"] == browser_research._CRW_TIMEOUT_SECONDS


def test_crw_search_and_fetch_skips_crw_during_cooldown(monkeypatch):
    monkeypatch.setattr(browser_research, "_crw_disabled_until", browser_research._time.time() + 60)
    monkeypatch.setattr(
        browser_research,
        "_ddgs_fallback_search",
        lambda query, max_results: {"query": query, "results": [], "formatted": "", "total": 0, "sources": []},
    )

    result = browser_research._crw_search_and_fetch("cooldown query")

    assert result["error"] == "crw_cooldown_active"
    assert result["total"] == 0
    monkeypatch.setattr(browser_research, "_crw_disabled_until", 0.0)


def test_crw_search_and_fetch_falls_back_when_crw_returns_no_results(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"success": True, "data": {"results": []}}

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=lambda url, json, timeout: FakeResponse()))
    monkeypatch.setattr(
        browser_research,
        "search_and_fetch",
        lambda query, max_results=8: {
            "query": query,
            "results": [{"url": "https://fallback.example.com", "title": "Fallback", "snippet": "Snippet", "content": "Body"}],
            "formatted": "Query: fallback",
            "total": 1,
            "sources": [{"title": "Fallback", "url": "https://fallback.example.com"}],
        },
    )

    result = browser_research._crw_search_and_fetch("test query")

    assert result["total"] == 1
    assert result["sources"] == [{"title": "Fallback", "url": "https://fallback.example.com"}]


def test_crw_batch_search_aggregates_across_queries(monkeypatch):
    def fake_crw_search(query, max_results):
        return {
            "query": query,
            "results": [],
            "formatted": f"formatted {query}",
            "total": 1,
            "sources": [{"title": query, "url": f"https://example.com/{query.replace(' ', '-')}"}],
        }

    monkeypatch.setattr(browser_research, "_crw_search_and_fetch", fake_crw_search)

    result = browser_research._crw_batch_search(["alpha", "beta"], max_results_each=5)

    assert result["queries_run"] == 2
    assert set(result["results_by_query"]) == {"alpha", "beta"}
    assert len(result["sources"]) == 2


def test_crw_failures_open_cooldown(monkeypatch):
    monkeypatch.setattr(browser_research, "_crw_failures", 0)
    monkeypatch.setattr(browser_research, "_crw_disabled_until", 0.0)

    for _ in range(browser_research._CRW_FAILURE_THRESHOLD):
        browser_research._record_crw_result(False)

    assert browser_research._crw_disabled_until > browser_research._time.time()
    assert browser_research._crw_failures == 0
    monkeypatch.setattr(browser_research, "_crw_disabled_until", 0.0)

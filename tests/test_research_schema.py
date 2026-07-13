"""Tests for the Wave 5.3 Research Engine V2 canonical schema
(backend/tools/research_schema.py) and its two producers:
  - backend.tools.web_search._extract_claims_from_report (open_deep_research
    escalation tier)
  - backend.tools.browser_research.to_research_result (native-search first
    pass adapter)
"""
from backend.tools import research_schema as rs


# ---------------------------------------------------------------------------
# deduplicate_evidence
# ---------------------------------------------------------------------------

def _ev(url: str, evidence_id: str = "", title: str = "t") -> dict:
    return {
        "evidence_id": evidence_id or rs.new_evidence_id(url, ""),
        "source_url": url,
        "title": title,
        "domain": "",
        "published_at": None,
        "retrieved_at": rs.now_iso(),
        "excerpt": "",
    }


def test_deduplicate_evidence_strips_query_params_and_fragment():
    evidence = [
        _ev("https://Example.com/Page?utm_source=x&ref=y#section"),
        _ev("https://example.com/Page?utm_source=z"),
    ]
    deduped = rs.deduplicate_evidence(evidence)
    assert len(deduped) == 1
    # keeps the FIRST occurrence
    assert deduped[0]["source_url"] == evidence[0]["source_url"]


def test_deduplicate_evidence_keeps_distinct_urls():
    evidence = [_ev("https://a.com/one"), _ev("https://a.com/two"), _ev("https://b.com/one")]
    deduped = rs.deduplicate_evidence(evidence)
    assert len(deduped) == 3


def test_deduplicate_evidence_lowercases_host():
    evidence = [_ev("https://EXAMPLE.com/path"), _ev("https://example.com/path")]
    deduped = rs.deduplicate_evidence(evidence)
    assert len(deduped) == 1


def test_deduplicate_evidence_trailing_slash_equivalence():
    evidence = [_ev("https://example.com/path/"), _ev("https://example.com/path")]
    deduped = rs.deduplicate_evidence(evidence)
    assert len(deduped) == 1


def test_deduplicate_evidence_empty_list():
    assert rs.deduplicate_evidence([]) == []


# ---------------------------------------------------------------------------
# new_query_id / new_evidence_id / new_claim_id stability
# ---------------------------------------------------------------------------

def test_new_query_id_stable_for_same_question():
    a = rs.new_query_id("What is the market size for widgets?")
    b = rs.new_query_id("What is the market size for widgets?")
    assert a == b


def test_new_query_id_case_and_whitespace_insensitive():
    a = rs.new_query_id("  What is the Market Size?  ")
    b = rs.new_query_id("what is the market size?")
    assert a == b


def test_new_query_id_differs_for_different_questions():
    a = rs.new_query_id("Question A")
    b = rs.new_query_id("Question B")
    assert a != b


def test_new_evidence_id_stable_for_same_url_and_excerpt():
    a = rs.new_evidence_id("https://example.com/a", "some excerpt")
    b = rs.new_evidence_id("https://example.com/a", "some excerpt")
    assert a == b


def test_new_evidence_id_differs_by_excerpt():
    a = rs.new_evidence_id("https://example.com/a", "excerpt one")
    b = rs.new_evidence_id("https://example.com/a", "excerpt two")
    assert a != b


def test_new_evidence_id_differs_by_url():
    a = rs.new_evidence_id("https://example.com/a", "same")
    b = rs.new_evidence_id("https://example.com/b", "same")
    assert a != b


def test_new_claim_id_stable_and_matches_spec_formula():
    import hashlib
    query_id = rs.new_query_id("q")
    claim_text = "The market grew 20% year over year."
    claim_id = rs.new_claim_id(query_id, claim_text)
    expected = hashlib.sha256(f"{query_id}{claim_text}".encode("utf-8")).hexdigest()[:12]
    assert claim_id == expected
    # stable across repeated calls
    assert rs.new_claim_id(query_id, claim_text) == claim_id


def test_new_claim_id_differs_for_different_query_id():
    text = "Same claim text."
    assert rs.new_claim_id("q1", text) != rs.new_claim_id("q2", text)


# ---------------------------------------------------------------------------
# dict_to_research_result / research_result_to_dict round trip
# ---------------------------------------------------------------------------

def test_dict_to_research_result_fills_defaults_for_partial_input():
    result = rs.dict_to_research_result({"question": "Q?"})
    assert result["question"] == "Q?"
    assert result["claims"] == []
    assert result["evidence"] == []
    assert result["coverage_gaps"] == []
    assert result["escalation_decision"] == "sufficient"


def test_dict_to_research_result_rejects_invalid_escalation_decision():
    result = rs.dict_to_research_result({"escalation_decision": "not_a_real_value"})
    assert result["escalation_decision"] == "sufficient"


def test_research_result_to_dict_round_trip():
    original = rs.dict_to_research_result({
        "query_id": "q1",
        "question": "How big is the market?",
        "claims": [{
            "claim_id": "c1", "text": "It is big.", "evidence_ids": ["e1"],
            "confidence": 0.8, "contradicted": False, "contradiction_note": "",
        }],
        "evidence": [{
            "evidence_id": "e1", "source_url": "https://x.com", "title": "X",
            "domain": "x.com", "published_at": None, "retrieved_at": rs.now_iso(),
            "excerpt": "big market",
        }],
        "coverage_gaps": ["pricing unknown"],
        "escalation_decision": "escalate_to_deep",
    })
    as_dict = rs.research_result_to_dict(original)
    # JSON-safe: every value must survive a JSON round trip unchanged.
    import json
    round_tripped = json.loads(json.dumps(as_dict))
    assert round_tripped == as_dict
    assert rs.dict_to_research_result(round_tripped) == original


def test_research_result_to_dict_returns_independent_copies():
    original = rs.dict_to_research_result({
        "claims": [{"claim_id": "c1", "text": "t", "evidence_ids": [], "confidence": 0.0,
                     "contradicted": False, "contradiction_note": ""}],
    })
    as_dict = rs.research_result_to_dict(original)
    as_dict["claims"][0]["text"] = "mutated"
    assert original["claims"][0]["text"] == "t"


# ---------------------------------------------------------------------------
# _extract_claims_from_report (web_search.py — open_deep_research escalation tier)
# ---------------------------------------------------------------------------

def test_extract_claims_from_report_produces_claims_with_evidence_ids():
    from backend.tools import web_search

    report = (
        "The global widget market is projected to reach $12 billion by 2027, growing at a "
        "15% compound annual rate. Key competitors include Acme Corp and Widgetco, both of "
        "which have raised significant venture funding in the past two years."
    )
    sources = [
        {"url": "https://example.com/report", "title": "Market Report"},
        {"url": "https://example.com/report?utm_source=share", "title": "Market Report (dup)"},
        {"url": "https://news.example.org/widgets", "title": "Widget News"},
    ]
    query_id = rs.new_query_id("widget market size")
    result = web_search._extract_claims_from_report(query_id, "widget market size", report, sources)

    assert result["query_id"] == query_id
    assert result["escalation_decision"] == "escalated"
    assert result["coverage_gaps"] == []

    # Deduplication: the tracking-param duplicate collapses into the first source.
    assert len(result["evidence"]) == 2
    evidence_ids = {e["evidence_id"] for e in result["evidence"]}
    assert len(evidence_ids) == 2

    assert len(result["claims"]) >= 1
    for claim in result["claims"]:
        assert claim["evidence_ids"], f"claim {claim['text']!r} has no evidence_ids"
        assert set(claim["evidence_ids"]).issubset(evidence_ids)
        assert claim["confidence"] > 0
        assert claim["contradiction_note"] == ""


def test_extract_claims_from_report_labels_unsupported_claims_when_no_sources():
    from backend.tools import web_search

    report = "This is a long enough sentence to qualify as a substantive claim for the test."
    query_id = rs.new_query_id("no sources question")
    result = web_search._extract_claims_from_report(query_id, "no sources question", report, [])

    assert result["evidence"] == []
    assert len(result["claims"]) == 1
    claim = result["claims"][0]
    assert claim["evidence_ids"] == []
    assert claim["confidence"] == 0.0
    assert claim["contradiction_note"] == "unsupported: no evidence available"


def test_extract_claims_from_report_empty_report_yields_no_claims():
    from backend.tools import web_search

    query_id = rs.new_query_id("empty report question")
    result = web_search._extract_claims_from_report(query_id, "empty report question", "", [])
    assert result["claims"] == []
    assert result["evidence"] == []


def test_extract_claims_from_report_short_sentences_filtered_out():
    from backend.tools import web_search

    report = "Yes. No. Ok."  # every sentence is below the substantive-length threshold
    query_id = rs.new_query_id("short question")
    result = web_search._extract_claims_from_report(query_id, "short question", report, [])
    assert result["claims"] == []


# ---------------------------------------------------------------------------
# browser_research.to_research_result (native-search first pass adapter)
# ---------------------------------------------------------------------------

def test_to_research_result_native_pass_shape_with_inline_sources():
    from backend.tools import browser_research

    native_result = {
        "answer": "Company X raised $10M in Series A funding in 2024.",
        "citations": ["src_1"],
        "claims": [{"claim": "Company X raised $10M in Series A funding in 2024.", "evidence_ids": ["src_1"]}],
        "sources": [{"id": "src_1", "title": "TechCrunch", "url": "https://techcrunch.com/x-funding"}],
        "total": 1,
    }
    result = browser_research.to_research_result("q1", "How much funding has Company X raised?", native_result, coverage_ready=True)

    assert result["escalation_decision"] == "sufficient"
    assert len(result["evidence"]) == 1
    assert len(result["claims"]) == 1
    assert result["claims"][0]["evidence_ids"] == [result["evidence"][0]["evidence_id"]]
    assert result["claims"][0]["confidence"] == 1.0
    assert result["coverage_gaps"] == []


def test_to_research_result_recursive_pipeline_shape_uses_passed_in_sources():
    from backend.tools import browser_research

    native_result = {"answer": "X", "citations": ["https://a.com/"], "total": 1,
                      "claims": [{"claim": "Some fact about X.", "evidence_ids": ["src_1"]}]}
    pipeline_sources = [{"id": "src_1", "title": "A", "url": "https://a.com/"}]
    result = browser_research.to_research_result("q2", "What about X?", native_result,
                                                  sources=pipeline_sources, coverage_ready=False)

    assert result["escalation_decision"] == "escalate_to_deep"
    assert len(result["evidence"]) == 1
    assert result["claims"][0]["evidence_ids"] == [result["evidence"][0]["evidence_id"]]


def test_to_research_result_no_claims_or_sources_reports_coverage_gap():
    from backend.tools import browser_research

    native_result = {"total": 0, "formatted": "", "sources": []}
    result = browser_research.to_research_result("q3", "Unanswered question?", native_result)

    assert result["claims"] == []
    assert result["evidence"] == []
    assert result["coverage_gaps"] == ["Unanswered question?"]
    assert result["escalation_decision"] == "escalate_to_deep"


def test_to_research_result_unresolvable_claim_ref_is_labeled_not_dropped():
    from backend.tools import browser_research

    native_result = {
        "claims": [{"claim": "A claim citing an id with no matching source.", "evidence_ids": ["src_missing"]}],
        "sources": [],
        "total": 0,
    }
    result = browser_research.to_research_result("q4", "Question?", native_result)

    assert len(result["claims"]) == 1
    claim = result["claims"][0]
    assert claim["evidence_ids"] == []
    assert claim["confidence"] == 0.0
    assert claim["contradiction_note"] == "unsupported: no evidence available"

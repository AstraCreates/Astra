import threading

from backend.tools import browser_research, web_search


def test_search_and_fetch_stops_immediately_when_cancelled():
    fence = threading.Event()
    fence.set()

    result = browser_research.search_and_fetch("competitor pricing", cancellation_fence=fence)

    assert result["error"] == "cancelled"
    assert result["results"] == []


def test_deep_research_stops_immediately_when_cancelled():
    fence = threading.Event()
    fence.set()

    result = browser_research.deep_research(["market sizing"], cancellation_fence=fence)

    assert result["error"] == "cancelled"


def test_run_research_pipeline_stops_immediately_when_cancelled():
    fence = threading.Event()
    fence.set()

    result = browser_research.run_research_pipeline("AI note taker", cancellation_fence=fence)

    assert result["queries_run"] == 0
    assert result["results_by_query"] == {}
    assert result["combined_formatted"] == ""


def test_web_search_deep_research_stops_immediately_when_cancelled():
    fence = threading.Event()
    fence.set()

    result = web_search.deep_research("AI note taker pricing", cancellation_fence=fence)

    assert result["error"] == "cancelled"

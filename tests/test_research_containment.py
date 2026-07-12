import asyncio
import os
import sys
import types
import threading

from backend.config import settings
from backend.tools import browser_research, web_search


def test_native_partial_answer_does_not_clone_across_queries(monkeypatch):
    class Completions:
        def create(self, **kwargs):
            message = types.SimpleNamespace(content='{"answers":[{"query":"one","answer":"answer","citation_urls":["https://example.com/one"]}]}', annotations=[{"url_citation": {"url": "https://example.com/one", "title": "One"}}])
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *args, **kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions())))
    monkeypatch.setattr("backend.core.key_rotator.get_openrouter_key", lambda: "key")
    monkeypatch.setattr("backend.core.llm_cache.openrouter_extra_body", lambda *args, **kwargs: {})
    result = browser_research._native_research_pass("topic", "market", ["one", "two"])
    assert set(result["results_by_query"]) == {"one"}


def test_crw_timeout_does_not_wait_for_worker(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(browser_research, "_CRW_BATCH_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(browser_research, "_crw_search_and_fetch", lambda *args: release.wait(1) or {"total": 0, "formatted": "", "sources": []})
    import time
    started = time.monotonic()
    result = browser_research._crw_batch_search(["blocked"])
    release.set()
    assert time.monotonic() - started < 0.2
    assert result["results_by_query"]["blocked"]["error"] == "crw_search_timeout"

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int = 8) -> dict:
    """Search the web. Args: query (str), max_results (int, default 8). Returns: {query, results: [{title, url, snippet}]}."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return {
            "query": query,
            "results": [
                {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                for r in results
            ],
        }
    except Exception as e:
        logger.error("web_search failed: %s", e)
        return {"query": query, "results": [], "error": str(e)}


def news_search(query: str, max_results: int = 5) -> dict:
    """Search recent news. Args: query (str), max_results (int, default 5). Returns: {query, results: [{title, url, snippet, date}]}."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        return {
            "query": query,
            "results": [
                {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("body"), "date": r.get("date")}
                for r in results
            ],
        }
    except Exception as e:
        logger.error("news_search failed: %s", e)
        return {"query": query, "results": [], "error": str(e)}

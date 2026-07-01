"""
Clean page fetching — strips nav/footer/ads, returns readable article content.
Used by agents to read actual page content, not raw HTML.
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_page(url: str, max_chars: int = 6000) -> dict:
    """Fetch URL, return clean text (ads/nav/scripts stripped)."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            return {"url": url, "error": f"Non-HTML content: {content_type}", "text": ""}

        text, title, links = _extract(resp.text, url)
        return {
            "url": url,
            "title": title,
            "text": text[:max_chars],
            "char_count": len(text),
            "links": links[:20],
            "truncated": len(text) > max_chars,
        }
    except requests.HTTPError as e:
        return {"url": url, "error": f"HTTP {e.response.status_code}", "text": ""}
    except Exception as e:
        logger.error("fetch_page failed for %s: %s", url, e)
        return {"url": url, "error": str(e), "text": ""}


def fetch_and_summarize(url: str, focus: str = "") -> dict:
    """Fetch URL and summarize; if focus given, extracts only paragraphs relevant to that topic."""
    page = fetch_page(url, max_chars=8000)
    if page.get("error") or not page.get("text"):
        return page

    text = page["text"]
    if focus:
        # Extract paragraphs mentioning the focus topic
        focus_lower = focus.lower()
        paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 50]
        relevant = [p for p in paragraphs if any(w in p.lower() for w in focus_lower.split())]
        if relevant:
            text = "\n\n".join(relevant[:15])

    return {
        "url": url,
        "title": page.get("title", ""),
        "summary": text[:4000],
        "focus": focus,
        "links": page.get("links", []),
    }


def search_and_read(query: str, max_results: int = 3, max_chars_per_page: int = 3000) -> dict:
    """Search web and fetch full page content from top results (not just snippets)."""
    from backend.tools.web_search import web_search
    search_results = web_search(query=query, max_results=max_results + 2)
    results = search_results.get("results", [])

    enriched = []
    for r in results[:max_results]:
        url = r.get("url", "")
        if not url or any(skip in url for skip in ["youtube.com", "twitter.com", "reddit.com/r/"]):
            enriched.append({**r, "page_content": r.get("snippet", "")})
            continue
        page = fetch_page(url, max_chars=max_chars_per_page)
        enriched.append({
            "title": r.get("title", page.get("title", "")),
            "url": url,
            "snippet": r.get("snippet", ""),
            "page_content": page.get("text", ""),
            "fetch_error": page.get("error"),
        })

    return {
        "query": query,
        "results": enriched,
        "total_fetched": len(enriched),
    }


def _extract(html: str, base_url: str = "") -> tuple[str, str, list]:
    """Extract clean text and title from raw HTML via trafilatura."""
    try:
        import trafilatura
        meta = trafilatura.extract_metadata(html)
        title = (meta.title or "") if meta else ""
        text = trafilatura.extract(html, no_fallback=False, include_tables=True) or ""
        return text, title, []
    except Exception:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
        return text[:6000], "", []

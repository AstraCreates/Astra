"""
Clean page fetching — strips nav/footer/ads, returns readable article content.
Used by agents to read actual page content, not raw HTML.
"""
import logging
import re
from typing import Optional

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

_JUNK_TAGS = {
    "nav", "header", "footer", "aside", "script", "style", "noscript",
    "iframe", "svg", "form", "button", "input", "select", "textarea",
    "advertisement", "ads", "banner",
}


def fetch_page(url: str, max_chars: int = 6000) -> dict:
    """
    Fetch URL and return clean readable text content.
    Strips navigation, ads, scripts. Returns structured content.
    """
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
    """
    Fetch URL and return a focused summary. If focus is given, extracts
    only the parts of the page relevant to the focus topic.
    """
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
    """
    Search the web then fetch and read top results. Returns enriched results
    with actual page content, not just snippets.
    """
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
    """Extract clean text, title, and links from raw HTML."""
    _re_strip = lambda h: (re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip(), "", [])

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text, title, links = _re_strip(html)
        return text[:6000], title, links

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        text, title, links = _re_strip(html)
        return text[:6000], title, links

    try:
        # Title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
    except Exception:
        title = ""

    try:
        # Remove junk elements
        for tag in _JUNK_TAGS:
            for el in list(soup.find_all(tag)):
                el.decompose()

        # Remove elements by class/id hints
        junk_patterns = re.compile(
            r"(nav|menu|sidebar|footer|header|cookie|banner|popup|modal|ad-|ads-|advertisement)",
            re.I,
        )
        for el in list(soup.find_all(attrs={"class": True})):
            try:
                classes = " ".join(el.get("class") or [])
                if junk_patterns.search(classes):
                    el.decompose()
            except Exception:
                pass
        for el in list(soup.find_all(attrs={"id": True})):
            try:
                if junk_patterns.search(el.get("id") or ""):
                    el.decompose()
            except Exception:
                pass
    except Exception:
        pass

    try:
        # Extract main content — prefer <main>, <article>, <section> over body
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", attrs={"role": "main"})
            or soup.find("div", class_=re.compile(r"content|main|article|post|body", re.I))
            or soup.body
            or soup
        )

        # Get text with newlines preserved
        lines = []
        for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "blockquote"]):
            try:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 3:
                    lines.append(text)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_extract content parse failed: %s", e)
        raw, _, _ = _re_strip(html)
        return raw[:6000], title, []

    try:
        # Extract links
        links = []
        for a in soup.find_all("a", href=True):
            try:
                href = a.get("href", "")
                link_text = a.get_text(strip=True)
                if href and href.startswith("http") and link_text:
                    links.append({"text": link_text[:80], "url": href})
            except Exception:
                pass
    except Exception:
        links = []

    text = "\n\n".join(lines)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, title, links

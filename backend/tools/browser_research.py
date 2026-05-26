"""
Browser-powered research using browser-harness http_get.
Fetches real page content from any URL — websites, research papers, arXiv, news.
No hardcoded sources: agent discovers URLs via search then reads them directly.
"""
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

_BH_SRC = "/tmp/browser-harness/src"


# Domains that reliably 403 scrapers — skip fetch, use snippet only
_BLOCKED_DOMAINS = {
    "researchgate.net", "wiley.com", "springer.com", "elsevier.com",
    "jstor.org", "tandfonline.com", "sagepub.com", "nature.com",
    "sciencedirect.com", "acm.org", "ieee.org",
}


def _is_blocked(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().lstrip("www.")
    return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)


def _http_get(url: str, timeout: float = 20.0) -> str:
    """Fetch URL via browser-harness http_get (handles bot detection + gzip)."""
    import urllib.request, urllib.error, gzip
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Connection": "keep-alive",
    }
    try:
        if _BH_SRC not in sys.path:
            sys.path.insert(0, _BH_SRC)
        from browser_harness.helpers import http_get
        return http_get(url, headers=headers, timeout=timeout) or ""
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise  # re-raise so fetch_and_read can handle gracefully
    except Exception as e:
        raise


def _extract_text(html: str, max_chars: int = 3000) -> str:
    """Strip HTML tags, collapse whitespace, return readable text."""
    # Remove scripts, styles, nav, header, footer blocks
    html = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip all tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_links(html: str, base_domain: str = "") -> list[str]:
    """Extract href URLs from HTML."""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    urls = []
    for h in hrefs:
        if h.startswith("http"):
            urls.append(h)
    return urls


def fetch_and_read(url: str) -> dict:
    """
    Fetch any URL and return clean extracted text content.
    Works on websites, research papers (arXiv, PubMed, SSRN), news articles, etc.
    Paywalled/bot-blocking domains (ResearchGate, Wiley, Springer, etc.) are skipped automatically.
    """
    if _is_blocked(url):
        return {"url": url, "error": "paywalled/blocked domain — use snippet only", "content": ""}
    try:
        html = _http_get(url, timeout=25.0)
        if not html:
            return {"url": url, "error": "Empty response", "content": ""}

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        content = _extract_text(html, max_chars=4000)

        return {
            "url": url,
            "title": title,
            "content": content,
            "content_length": len(content),
        }
    except Exception as e:
        # Don't log 403s as warnings — expected for many sites
        if "403" not in str(e):
            logger.warning("fetch_and_read failed for %s: %s", url, e)
        return {"url": url, "error": str(e), "content": ""}


def search_and_fetch(query: str, max_results: int = 5) -> dict:
    """
    Search DuckDuckGo for the query, then fetch and read the actual content
    of each result page. Returns rich page content, not just snippets.
    Use for: websites, news, blogs, company pages, research papers, anything.
    """
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results * 2))
    except Exception as e:
        return {"query": query, "results": [], "error": f"Search failed: {e}"}

    urls = [r.get("href", "") for r in raw if r.get("href", "").startswith("http") and not _is_blocked(r.get("href", ""))][:max_results]
    snippets = {r.get("href", ""): r.get("body", "") for r in raw}
    titles = {r.get("href", ""): r.get("title", "") for r in raw}

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch_and_read, url): url for url in urls}
        for fut in as_completed(futures, timeout=60):
            url = futures[fut]
            try:
                page = fut.result()
                if not page.get("error"):
                    results.append({
                        "url": url,
                        "title": page.get("title") or titles.get(url, ""),
                        "snippet": snippets.get(url, ""),
                        "content": page["content"],
                    })
            except Exception as e:
                results.append({"url": url, "title": titles.get(url, ""), "snippet": snippets.get(url, ""), "content": "", "error": str(e)})

    # Sort by content length (more content = better)
    results.sort(key=lambda r: len(r.get("content", "")), reverse=True)

    formatted = [f"Query: {query}\n"]
    for r in results:
        formatted.append(f"\n### {r['title'] or r['url']}")
        formatted.append(f"URL: {r['url']}")
        if r.get("content"):
            formatted.append(r["content"][:800])
        elif r.get("snippet"):
            formatted.append(r["snippet"])

    return {
        "query": query,
        "results": results,
        "formatted": "\n".join(formatted),
        "total": len(results),
    }


def research_papers(query: str, max_results: int = 5) -> dict:
    """
    Search for academic papers and research on a topic.
    Searches arXiv, Google Scholar, PubMed, SSRN — whichever has relevant results.
    Returns full abstract and key findings extracted from each paper page.
    """
    # Search specifically for papers via DuckDuckGo
    paper_query = f"{query} research paper OR study OR analysis filetype:pdf OR site:arxiv.org OR site:scholar.google.com OR site:pubmed.ncbi.nlm.nih.gov OR site:ssrn.com"
    return search_and_fetch(paper_query, max_results=max_results)

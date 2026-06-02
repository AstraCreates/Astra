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


# Domains that reliably 403/404/auth-wall scrapers — skip fetch, use snippet only
_BLOCKED_DOMAINS = {
    # Academic paywalls
    "researchgate.net", "wiley.com", "springer.com", "elsevier.com",
    "jstor.org", "tandfonline.com", "sagepub.com", "nature.com",
    "sciencedirect.com", "acm.org", "ieee.org",
    # Auth-required / bot-blocked social/business
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "tiktok.com", "pinterest.com",
    # Login-walled news/data
    "wsj.com", "ft.com", "bloomberg.com", "nytimes.com", "washingtonpost.com",
    "hbr.org", "statista.com",
    # Community sites that 404 when scraped
    "quora.com", "glassdoor.com", "ziprecruiter.com",
    # Redirect-loops / auth-required
    "statista.com", "facebook.com", "reddit.com",
    # Consistently timeout/block scrapers
    "mckinsey.com", "enrichlabs.ai", "metro.us",
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
        import ssl, certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.reason}") from e
    except Exception as e:
        raise


def _extract_text(html: str, max_chars: int = 6000) -> str:
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
        return {"url": url, "skipped": "blocked domain", "content": ""}
    # Encode non-ASCII chars so urllib doesn't choke
    try:
        url.encode("ascii")
    except UnicodeEncodeError:
        from urllib.parse import quote
        url = quote(url, safe=":/?#[]@!$&'()*+,;=%")
    try:
        html = _http_get(url, timeout=25.0)
        if not html:
            return {"url": url, "skipped": "empty response", "content": ""}

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        content = _extract_text(html, max_chars=8000)

        return {
            "url": url,
            "title": title,
            "content": content,
            "content_length": len(content),
        }
    except Exception as e:
        es = str(e)
        # Expected HTTP errors — silent, fall back to snippet
        if any(code in es for code in ("400", "401", "403", "404", "410", "429", "302", "301", "503", "521", "444", "codec",
                                        "SSL", "CERTIFICATE", "certificate", "timed out", "Operation timed out", "TLSV1",
                                        "nodename nor servname", "Name or service not known", "Errno 8", "Errno 11001")):
            return {"url": url, "skipped": es[:40], "content": ""}
        logger.warning("fetch_and_read failed for %s: %s", url, e)
        return {"url": url, "skipped": str(e)[:80], "content": ""}


def search_and_fetch(query: str, max_results: int = 12) -> dict:
    """
    Search DuckDuckGo for the query, then fetch and read the actual content
    of each result page. Returns rich page content, not just snippets.
    Use for: websites, news, blogs, company pages, research papers, anything.
    """
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results * 3))
    except Exception as e:
        return {"query": query, "results": [], "error": f"Search failed: {e}"}

    snippets = {r.get("href", ""): r.get("body", "") for r in raw}
    titles = {r.get("href", ""): r.get("title", "") for r in raw}

    fetch_urls = []
    results = []
    for r in raw:
        url = r.get("href", "")
        if not url.startswith("http"):
            continue
        if _is_blocked(url):
            # Keep snippet — don't waste a fetch on auth-walled sites
            snippet = snippets.get(url, "")
            if snippet:
                results.append({"url": url, "title": titles.get(url, ""), "snippet": snippet, "content": ""})
        else:
            fetch_urls.append(url)
    fetch_urls = fetch_urls[:max_results + 4]

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_and_read, url): url for url in fetch_urls}
        for fut in as_completed(futures, timeout=60):
            url = futures[fut]
            try:
                page = fut.result()
                content = page.get("content", "")
                snippet = snippets.get(url, "")
                if content or snippet:
                    results.append({
                        "url": url,
                        "title": page.get("title") or titles.get(url, ""),
                        "snippet": snippet,
                        "content": content,
                    })
            except Exception:
                snippet = snippets.get(url, "")
                if snippet:
                    results.append({"url": url, "title": titles.get(url, ""), "snippet": snippet, "content": ""})

    # Sort: full content first, snippet-only last
    results.sort(key=lambda r: len(r.get("content", "")), reverse=True)

    formatted = [f"Query: {query}\n"]
    for r in results:
        formatted.append(f"\n### {r['title'] or r['url']}")
        formatted.append(f"URL: {r['url']}")
        if r.get("content"):
            formatted.append(r["content"][:8000])
        elif r.get("snippet"):
            formatted.append(f"[snippet only] {r['snippet']}")

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


def batch_search(queries: list, max_results_each: int = 8) -> dict:
    """
    Run multiple search queries IN PARALLEL and return all results combined.
    Use this to run 3-8 searches simultaneously instead of one at a time.
    queries: list of search query strings (max 8 for speed).
    Returns: {results_by_query: {query: {results, formatted}}, combined_formatted: str}
    """
    queries = queries[:8]  # cap to prevent abuse
    results_by_query: dict = {}

    with ThreadPoolExecutor(max_workers=min(len(queries), 6)) as ex:
        futures = {ex.submit(search_and_fetch, q, max_results_each): q for q in queries}
        for fut in as_completed(futures, timeout=120):
            q = futures[fut]
            try:
                results_by_query[q] = fut.result()
            except Exception as e:
                results_by_query[q] = {"query": q, "results": [], "error": str(e)}

    combined = []
    for q, r in results_by_query.items():
        combined.append(f"\n\n## QUERY: {q}\n{r.get('formatted', '')[:3000]}")

    return {
        "queries_run": len(queries),
        "results_by_query": {q: {"total": r.get("total", 0), "formatted": r.get("formatted", "")[:8000]} for q, r in results_by_query.items()},
        "combined_formatted": "\n".join(combined),
    }

"""
Browser-powered research using browser-harness http_get.
Fetches real page content from any URL — websites, research papers, arXiv, news.
No hardcoded sources: agent discovers URLs via search then reads them directly.
"""
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.tools.url_safety import validate_url

logger = logging.getLogger(__name__)

_BH_SRC = "/tmp/browser-harness/src"

# Reliable search backends in priority order. On this host duckduckgo/brave/
# mojeek/startpage frequently return "No results found", while "auto", "bing"
# and "yahoo" work fast (<2s). Rotate through the good ones with retries so a
# single rate-limited backend never yields 0 sites.
_SEARCH_BACKENDS = ("auto", "bing", "yahoo")

# Several research agents run in parallel and hammer the same search backends,
# which is exactly when they start rate-limiting. Cap CONCURRENCY (semaphore) and
# add a small inter-call gap rather than fully serializing — a single global lock
# at a 1s gap throttled all research across every session to 1 search/sec, which
# made researchers crawl. A bounded pool keeps backends happy while staying fast;
# the short-TTL result cache absorbs duplicate queries.
import threading as _threading
import time as _time

_SEARCH_GATE = _threading.BoundedSemaphore(4)  # up to 4 concurrent searches
_SEARCH_MIN_INTERVAL = 0.15  # small global spacing, not a 1/sec bottleneck
_last_search_at = 0.0
_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 min — research bursts re-ask the same queries
_SEARCH_CACHE_MAX = 256

# Per-URL fetch cache (success AND failure). Without caching failures, a dead
# URL that every search re-surfaces (e.g. a 307 redirect-loop) gets re-fetched
# on every query — the research agent appears "stuck" hammering one bad link.
_FETCH_CACHE: dict[str, tuple[float, dict]] = {}
_FETCH_CACHE_TTL = 600.0  # 10 min
_FETCH_CACHE_MAX = 512


def _robust_search(query: str, max_results: int = 12) -> list[dict]:
    """Return search results, rotating reliable ddgs backends with retries.
    Throttled process-wide so parallel agents don't rate-limit the backends,
    and cached briefly so repeated queries are free. Never hangs (each call is
    bounded) and never silently returns 0 if any backend works."""
    import random as _random
    try:
        from ddgs import DDGS
    except Exception as e:
        logger.warning("ddgs import failed: %s", e)
        return []

    global _last_search_at
    key = f"{query.strip().lower()}|{max_results}"
    now = _time.time()
    hit = _SEARCH_CACHE.get(key)
    if hit and (now - hit[0]) < _SEARCH_CACHE_TTL:
        return hit[1]

    with _SEARCH_GATE:
        # Re-check cache: another thread may have answered this query while we waited.
        hit = _SEARCH_CACHE.get(key)
        if hit and (_time.time() - hit[0]) < _SEARCH_CACHE_TTL:
            return hit[1]
        for backend in _SEARCH_BACKENDS:
            for attempt in range(3):
                gap = _SEARCH_MIN_INTERVAL - (_time.time() - _last_search_at)
                if gap > 0:
                    _time.sleep(gap)
                try:
                    _last_search_at = _time.time()
                    r = list(DDGS(timeout=12).text(query, max_results=max_results, backend=backend))
                    if r:
                        if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
                            oldest = min(_SEARCH_CACHE, key=lambda k: _SEARCH_CACHE[k][0])
                            _SEARCH_CACHE.pop(oldest, None)
                        _SEARCH_CACHE[key] = (_time.time(), r)
                        return r
                except Exception as e:
                    logger.debug("search backend=%s attempt=%d failed: %s", backend, attempt, e)
                # Jittered exponential backoff before retrying this backend.
                _time.sleep(0.4 * (2 ** attempt) + _random.uniform(0, 0.4))
    return []

_QUERY_BLUEPRINTS = {
    "market": [
        "{topic} market size TAM SAM SOM 2025 report statistics",
        "{topic} CAGR forecast 2025 2026 2030 industry report",
        "{topic} customer segments ICP buyer persona demographics firmographics",
        "{topic} pricing benchmark subscription tiers competitor pricing",
        "{topic} regulation compliance requirements risks",
        "{topic} funding rounds venture capital startups 2024 2025",
        "{topic} analyst report market map competitors",
    ],
    "competitors": [
        "{topic} top competitors alternatives companies platforms 2025",
        "{topic} site:g2.com OR site:capterra.com OR site:producthunt.com alternatives reviews",
        "{topic} Crunchbase funding valuation startup competitors",
        "{topic} pricing page subscription enterprise competitor",
        "{topic} customer complaints reddit reviews problems",
        "{topic} YC a16z Sequoia backed startup competitor",
        "{topic} market map landscape companies",
    ],
    "execution": [
        "{topic} go to market strategy startup playbook",
        "{topic} business model revenue streams monetization pricing",
        "{topic} technical architecture stack implementation guide",
        "{topic} CAC LTV unit economics benchmark",
        "{topic} founder case study how they built",
        "{topic} customer pain points complaints jobs to be done",
        "{topic} customer success story ROI case study",
    ],
}


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


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().lstrip("www.")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    tracking_prefixes = ("utm_",)
    tracking_keys = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in tracking_keys and not any(k.startswith(prefix) for prefix in tracking_prefixes)
    ]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", urlencode(query), ""))


def _source_score(result: dict, query: str) -> int:
    """Prefer source-diverse, information-dense results before fetching."""
    url = result.get("href") or result.get("url") or ""
    title = (result.get("title") or "").lower()
    body = (result.get("body") or result.get("snippet") or "").lower()
    host = _domain(url)
    text = f"{title} {body}"
    score = 0
    if any(word in text for word in ("market size", "tam", "cagr", "forecast", "funding", "pricing", "benchmark")):
        score += 4
    if any(word in text for word in ("report", "study", "survey", "data", "statistics", "analysis")):
        score += 3
    if any(d in host for d in (
        "gartner.com", "forrester.com", "mckinsey.com", "bcg.com", "deloitte.com",
        "grandviewresearch.com", "mordorintelligence.com", "ibisworld.com",
        "crunchbase.com", "pitchbook.com", "ycombinator.com", "a16z.com",
        "g2.com", "capterra.com", "producthunt.com", "sec.gov", "census.gov",
    )):
        score += 3
    if "site:" in query.lower():
        score += 1
    if any(d in host for d in ("pinterest.", "facebook.", "instagram.", "x.com", "twitter.")):
        score -= 4
    return score


def build_research_queries(topic: str, focus: str = "market", limit: int = 7) -> dict:
    """Build source-seeking search queries for a research lane.

    This gives agents a deterministic, high-coverage query plan before they
    start browsing, instead of relying on the model to invent a good search mix
    every run.
    """
    clean_topic = re.sub(r"\s+", " ", (topic or "").strip())
    if not clean_topic:
        return {"topic": topic, "focus": focus, "queries": [], "error": "topic is required"}
    normalized_focus = (focus or "market").strip().lower()
    if normalized_focus not in _QUERY_BLUEPRINTS:
        normalized_focus = "market"
    queries = [template.format(topic=clean_topic) for template in _QUERY_BLUEPRINTS[normalized_focus]]
    deduped = []
    seen = set()
    for query in queries:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(query)
    return {
        "topic": clean_topic,
        "focus": normalized_focus,
        "queries": deduped[: max(1, min(limit, 8))],
        "recommended_tool": "batch_search",
    }


class _ValidatingRedirectHandler:
    """urllib redirect handler that re-validates each hop against the SSRF
    guard before following it (a URL passing the initial check must not be
    allowed to 302 its way to an internal address)."""

    def __new__(cls):
        import urllib.request

        class _Handler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                validate_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        return _Handler()


def _http_get(url: str, timeout: float = 8.0) -> str:
    """Fetch URL via browser-harness http_get (handles bot detection + gzip)."""
    # SSRF guard: block internal/private targets before any network call.
    validate_url(url)

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
        # NOTE: residual gap — browser_harness.http_get is a third-party
        # helper we don't control, so redirects it follows internally are
        # not re-validated per hop here (only the initial URL is checked
        # above). The urllib fallback path below re-validates every hop.
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
        handlers = [_ValidatingRedirectHandler()]
        if ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(req, timeout=timeout) as r:
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


def _canonicalize_search_query(query: object) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _dedupe_search_queries(queries: list[object], limit: int = 12) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        normalized = _canonicalize_search_query(raw)
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique


def fetch_and_read(url: str = "") -> dict:
    """Fetch a URL, return clean text. Blocked/paywalled domains auto-skipped."""
    if not url:
        return {"error": "url is required — pass the full URL to fetch, e.g. https://example.com"}
    if _is_blocked(url):
        return {"url": url, "skipped": "blocked domain", "content": ""}
    # Serve a cached result (success or prior failure) so dead/looping URLs that
    # keep showing up in search results aren't re-fetched on every query.
    _now = _time.time()
    hit = _FETCH_CACHE.get(url)
    if hit and (_now - hit[0]) < _FETCH_CACHE_TTL:
        return hit[1]
    # Encode non-ASCII chars so urllib doesn't choke
    try:
        url.encode("ascii")
    except UnicodeEncodeError:
        from urllib.parse import quote
        url = quote(url, safe=":/?#[]@!$&'()*+,;=%")

    def _remember(result: dict) -> dict:
        if len(_FETCH_CACHE) >= _FETCH_CACHE_MAX:
            oldest = min(_FETCH_CACHE, key=lambda k: _FETCH_CACHE[k][0])
            _FETCH_CACHE.pop(oldest, None)
        _FETCH_CACHE[url] = (_time.time(), result)
        return result

    try:
        html = _http_get(url, timeout=8.0)
        if not html:
            return _remember({"url": url, "skipped": "empty response", "content": ""})

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        content = _extract_text(html, max_chars=8000)

        return _remember({
            "url": url,
            "title": title,
            "content": content,
            "content_length": len(content),
        })
    except Exception as e:
        es = str(e)
        # Expected HTTP errors (incl. 307 / redirect loops) — silent, cached so the
        # same dead URL is never re-fetched within the TTL.
        if any(code in es for code in ("400", "401", "403", "404", "410", "429", "302", "301", "307", "308",
                                        "redirect", "infinite loop", "503", "521", "444", "codec",
                                        "SSL", "CERTIFICATE", "certificate", "timed out", "Operation timed out", "TLSV1",
                                        "nodename nor servname", "Name or service not known", "Errno 8", "Errno 11001")):
            return _remember({"url": url, "skipped": es[:40], "content": ""})
        logger.warning("fetch_and_read failed for %s: %s", url, e)
        return _remember({"url": url, "skipped": str(e)[:80], "content": ""})


def search_and_fetch(query: str = "", max_results: int = 16) -> dict:
    """Search web then fetch full page content from each result."""
    if not query:
        return {"error": "query is required — pass a search string, e.g. \"competitor pricing SaaS\""}
    raw = _robust_search(query, max_results=max_results * 2)
    if not raw:
        return {"query": query, "results": [], "error": "Search returned no results"}

    ranked_raw = sorted(raw, key=lambda r: _source_score(r, query), reverse=True)
    snippets = {}
    titles = {}

    fetch_urls = []
    results = []
    seen_urls = set()
    seen_domains = {}
    for r in ranked_raw:
        url = _normalize_url(r.get("href", ""))
        if not url.startswith("http"):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        host = _domain(url)
        seen_domains[host] = seen_domains.get(host, 0) + 1
        # One result per domain → maximize source diversity (no more two-of-the-
        # same-site pairs). Extra hits from the same domain are dropped.
        if seen_domains[host] > 1:
            continue
        snippets[url] = r.get("body", "")
        titles[url] = r.get("title", "")
        if _is_blocked(url):
            # Keep snippet — don't waste a fetch on auth-walled sites
            snippet = snippets.get(url, "")
            if snippet:
                results.append({"url": url, "title": titles.get(url, ""), "snippet": snippet, "content": ""})
        else:
            fetch_urls.append(url)
    fetch_urls = fetch_urls[:max_results + 4]

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fetch_and_read, url): url for url in fetch_urls}
        for fut in as_completed(futures, timeout=25):
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
        "sources": [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results if r.get("url")],
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


def sonar_research(queries=None) -> dict:
    """Run queries via Perplexity sonar-pro; each returns synthesized answer with citations."""
    if not queries:
        return {"error": "queries required — pass a list of research question strings"}
    queries = list(queries)[:12]

    import httpx as _httpx
    from backend.config import settings as _settings
    from backend.core.key_rotator import get_openrouter_key as _get_key

    _key = _get_key() or _settings.agent_model_api_key

    def _call(query: str) -> dict:
        try:
            r = _httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {_key}", "Content-Type": "application/json"},
                json={
                    "model": getattr(_settings, "research_model", "") or "perplexity/sonar",
                    "messages": [{"role": "user", "content": query}],
                    "provider": {"allow_fallbacks": False},
                    "usage": {"include": True},
                },
                timeout=90,
            )
            d = r.json()
            if "error" in d:
                return {"query": query, "answer": "", "citations": [], "error": str(d["error"])[:200]}
            msg = ((d.get("choices") or [{}])[0]).get("message") or {}
            anns = msg.get("annotations") or []
            citations = [a.get("url_citation", {}).get("url", "") for a in anns if isinstance(a, dict)]
            return {"query": query, "answer": msg.get("content") or "", "citations": [c for c in citations if c]}
        except Exception as exc:
            return {"query": query, "answer": "", "citations": [], "error": str(exc)}

    results: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(queries), 6)) as ex:
        futures = {ex.submit(_call, q): q for q in queries}
        try:
            for fut in as_completed(futures, timeout=120):
                results[futures[fut]] = fut.result()
        except TimeoutError:
            for fut, q in futures.items():
                if q not in results:
                    results[q] = {"query": q, "answer": "", "citations": [], "error": "timeout"}

    combined, all_sources, seen = [], [], set()
    for q in queries:
        r = results.get(q, {})
        combined.append(f"## {q}\n{r.get('answer', '')}")
        for url in r.get("citations", []):
            if url and url not in seen:
                seen.add(url)
                all_sources.append({"url": url})

    return {
        "queries_run": len(queries),
        "results_by_query": {
            q: {"answer": results.get(q, {}).get("answer", ""), "citations": results.get(q, {}).get("citations", []), "total": len(results.get(q, {}).get("citations", []))}
            for q in queries
        },
        "combined_formatted": "\n\n".join(combined),
        "sources": all_sources,
    }


def batch_search(queries=None, max_results_each: int = 8) -> dict:
    """Run search queries in parallel and return combined results."""
    if not queries:
        return {"error": "queries is required — pass a list of search strings, e.g. [\"competitor A pricing\", \"competitor B features\"]"}
    queries = _dedupe_search_queries(list(queries), limit=12)
    if not queries:
        return {"error": "queries is required — pass a list of search strings, e.g. [\"competitor A pricing\", \"competitor B features\"]"}
    results_by_query: dict = {}

    with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as ex:
        futures = {ex.submit(search_and_fetch, q, max_results_each): q for q in queries}
        # Process-wide search gate serializes calls (~1s apart) and each query
        # retries with backoff, so a parallel batch can take well over a minute.
        # Catch the overall timeout and return whatever finished — partial
        # results beat an all-or-nothing "N futures unfinished" failure.
        try:
            for fut in as_completed(futures, timeout=110):
                q = futures[fut]
                try:
                    results_by_query[q] = fut.result()
                except Exception as e:
                    results_by_query[q] = {"query": q, "results": [], "error": str(e)}
        except TimeoutError:
            for fut, q in futures.items():
                if q in results_by_query:
                    continue
                if fut.done() and not fut.cancelled():
                    try:
                        results_by_query[q] = fut.result()
                    except Exception as e:
                        results_by_query[q] = {"query": q, "results": [], "error": str(e)}
                else:
                    fut.cancel()
                    results_by_query[q] = {"query": q, "results": [], "error": "search_timeout"}

    combined = []
    all_sources = []
    seen_sources = set()
    for q, r in results_by_query.items():
        combined.append(f"\n\n## QUERY: {q}\n{r.get('formatted', '')[:3000]}")
        for source in r.get("sources", []):
            url = _normalize_url(source.get("url", ""))
            if url and url not in seen_sources:
                seen_sources.add(url)
                all_sources.append({**source, "url": url})

    return {
        "queries_run": len(queries),
        "results_by_query": {q: {"total": r.get("total", 0), "formatted": r.get("formatted", "")[:8000]} for q, r in results_by_query.items()},
        "combined_formatted": "\n".join(combined),
        "sources": all_sources[:50],
    }


def _research_coverage(focus: str, queries: list[str], search: dict) -> dict:
    sources = search.get("sources", [])
    source_domains: dict[str, int] = {}
    for source in sources:
        host = _domain(source.get("url", ""))
        if host:
            source_domains[host] = source_domains.get(host, 0) + 1

    results_by_query = search.get("results_by_query", {})
    covered_queries = [
        query
        for query in queries
        if (results_by_query.get(query) or {}).get("total", 0) > 0
    ]

    required_sources = 8 if focus in {"market", "competitors"} else 6
    required_domains = 4 if focus in {"market", "competitors"} else 3
    required_query_coverage = min(5, len(queries))

    gaps = []
    if len(sources) < required_sources:
        gaps.append(f"source_count_below_{required_sources}")
    if len(source_domains) < required_domains:
        gaps.append(f"domain_diversity_below_{required_domains}")
    if len(covered_queries) < required_query_coverage:
        gaps.append(f"query_coverage_below_{required_query_coverage}")
    if not search.get("combined_formatted", "").strip():
        gaps.append("no_combined_evidence")

    return {
        "ready": not gaps,
        "gaps": gaps,
        "source_count": len(sources),
        "domain_count": len(source_domains),
        "source_domains": source_domains,
        "query_coverage": {
            "covered": len(covered_queries),
            "total": len(queries),
            "missing": [query for query in queries if query not in covered_queries],
        },
    }


def run_research_pipeline(topic: str, focus: str = "market", max_results_each: int = 8) -> dict:
    """Plan and run a complete source-diverse research pass.

    Agents should use this when they need reliable first-pass evidence quickly:
    it plans lane-specific queries, executes them in parallel, dedupes sources,
    and returns a compact evidence package for synthesis.
    """
    plan = build_research_queries(topic, focus=focus, limit=10)
    queries = plan.get("queries", [])
    if not queries:
        return {
            **plan,
            "results_by_query": {},
            "sources": [],
            "combined_formatted": "",
            "coverage": {"ready": False, "gaps": ["topic is required"], "source_count": 0, "domain_count": 0},
        }
    search = batch_search(queries, max_results_each=max_results_each)
    coverage = _research_coverage(plan["focus"], queries, search)
    return {
        "topic": plan["topic"],
        "focus": plan["focus"],
        "queries": queries,
        "queries_run": search.get("queries_run", 0),
        "results_by_query": search.get("results_by_query", {}),
        "sources": search.get("sources", []),
        "source_count": coverage["source_count"],
        "source_domains": coverage["source_domains"],
        "coverage": coverage,
        "combined_formatted": search.get("combined_formatted", ""),
        "next_step": (
            "Synthesize findings with concrete numbers, named companies, dates, caveats, and URLs."
            if coverage["ready"]
            else "Evidence is thin. Fill coverage gaps before making strong claims, or explicitly label uncertainty."
        ),
    }

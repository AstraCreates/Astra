"""
Browser-powered research using browser-harness http_get.
Fetches real page content from any URL — websites, research papers, arXiv, news.
No hardcoded sources: agent discovers URLs via search then reads them directly.
"""
import logging
import os
import re
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.tools.research_schema import (
    Claim,
    Evidence,
    ResearchResult,
    deduplicate_evidence,
    new_claim_id,
    new_evidence_id,
    new_query_id,
    now_iso,
    research_result_to_dict,
)
from backend.tools.research_evidence import write_evidence_artifact
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
_RESEARCH_TOOL_GATE = _threading.BoundedSemaphore(max(1, int(os.environ.get("ASTRA_RESEARCH_TOOL_CONCURRENCY", "2"))))
_RESEARCH_TOOL_LOCAL = _threading.local()
_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 min — research bursts re-ask the same queries
_SEARCH_CACHE_MAX = 256

# Per-URL fetch cache (success AND failure). Without caching failures, a dead
# URL that every search re-surfaces (e.g. a 307 redirect-loop) gets re-fetched
# on every query — the research agent appears "stuck" hammering one bad link.
_FETCH_CACHE: dict[str, tuple[float, dict]] = {}
_FETCH_CACHE_TTL = 600.0  # 10 min
_FETCH_CACHE_MAX = 512

_RECURSIVE_RESEARCH_ROUNDS = 2
_RECURSIVE_RESEARCH_MAX_FOLLOWUPS = 4
_RESEARCH_QUERY_PLAN_LIMIT = 6
_MAX_SEARCH_QUERY_WORDS = 24
_MAX_SEARCH_QUERY_CHARS = 180
_RESEARCH_EVIDENCE_CHAR_CAP = 2200
_RESEARCH_COMBINED_QUERY_CHAR_CAP = 3000
_RESEARCH_PER_QUERY_FORMATTED_CAP = 5000
_RESEARCH_MAX_SOURCES = 24
_RESEARCH_SYNTHESIS_MAX_TOKENS = 700
_RESEARCH_FOLLOWUP_MAX_TOKENS = 400
_RESEARCH_FINAL_ANSWER_MAX_TOKENS = 500
_RESEARCH_FETCH_TEXT_CHAR_CAP = 12000
_RESEARCH_RESULT_CONTENT_CHAR_CAP = 2400
_RESEARCH_MAX_URL_CANDIDATES_BUFFER = 2
_RESEARCH_SEARCH_MULTIPLIER = 1.5
_RESEARCH_BLOCK_WINDOW_SENTENCES = 1
_CRW_TIMEOUT_SECONDS = max(3.0, float(os.environ.get("ASTRA_CRW_TIMEOUT_SECONDS", "12")))
_CRW_BATCH_TIMEOUT_SECONDS = max(
    _CRW_TIMEOUT_SECONDS + 2.0,
    # 20s was tuned against a single-lane assumption. With no `chrome` renderer
    # deployed (see config.docker.toml -- a deliberate tradeoff, not a bug),
    # hard anti-bot pages fall through HTTP->lightpanda and can legitimately
    # run long; under concurrent multi-lane research (research/competitors/
    # customers/gtm firing together) the slowest straggler in a 12-query batch
    # was blowing past 20s often enough to trip the breaker on real, not
    # actually-broken, batches. 30s gives real batches breathing room without
    # going unbounded.
    float(os.environ.get("ASTRA_CRW_BATCH_TIMEOUT_SECONDS", "30")),
)
_CRW_FAILURE_THRESHOLD = max(1, int(os.environ.get("ASTRA_CRW_FAILURE_THRESHOLD", "4")))
_CRW_COOLDOWN_SECONDS = max(10.0, float(os.environ.get("ASTRA_CRW_COOLDOWN_SECONDS", "180")))
_RESEARCH_QUERY_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "about", "their", "there",
    "what", "when", "where", "which", "while", "who", "why", "how", "your", "have", "has",
    "had", "were", "been", "being", "than", "then", "them", "they", "you", "our", "its",
    "not", "but", "can", "could", "would", "should", "are", "was", "will", "may", "might",
    "research", "report", "analysis", "market", "industry", "company",
}

_crw_failures = 0
_crw_disabled_until = 0.0


def _coerce_cancel_event(cancel_event=None, cancellation_fence=None):
    return cancel_event if cancel_event is not None else cancellation_fence


def _cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())


def _call_with_optional_cancellation(func, *args, cancellation_fence=None, **kwargs):
    """Preserve legacy tool call shapes unless cancellation is active.

    Research tools are monkeypatched by tests and some integrations as simple
    two-argument callables. Passing a new ``None`` fence changes that contract
    for no behavioral gain. Thread the fence only when there is one to observe.
    """
    if cancellation_fence is None:
        return func(*args, **kwargs)
    return func(*args, cancellation_fence=cancellation_fence, **kwargs)


def _shutdown_executor(executor: ThreadPoolExecutor, futures: dict) -> None:
    for future in futures:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)


def _source_id(index: int) -> str:
    return f"src_{index}"


@contextmanager
def _research_tool_slot():
    depth = getattr(_RESEARCH_TOOL_LOCAL, "depth", 0)
    if depth > 0:
        _RESEARCH_TOOL_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _RESEARCH_TOOL_LOCAL.depth -= 1
        return
    _RESEARCH_TOOL_GATE.acquire()
    _RESEARCH_TOOL_LOCAL.depth = 1
    try:
        yield
    finally:
        _RESEARCH_TOOL_LOCAL.depth = 0
        _RESEARCH_TOOL_GATE.release()


def _crw_available() -> bool:
    return _time.time() >= _crw_disabled_until


def _record_crw_result(ok: bool) -> None:
    global _crw_failures, _crw_disabled_until
    if ok:
        _crw_failures = 0
        return
    _crw_failures += 1
    if _crw_failures >= _CRW_FAILURE_THRESHOLD:
        _crw_disabled_until = _time.time() + _CRW_COOLDOWN_SECONDS
        logger.warning(
            "crw disabled for %.0fs after %d consecutive failures",
            _CRW_COOLDOWN_SECONDS,
            _crw_failures,
        )
        _crw_failures = 0


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
    "customers": [
        "{topic} customer pain points buyer persona ICP demographics firmographics",
        "{topic} customer complaints reviews reddit forum churn reasons",
        "{topic} jobs to be done buying triggers implementation blockers",
        "{topic} willingness to pay pricing sensitivity budget owner",
        "{topic} onboarding friction adoption retention case study",
        "{topic} user interview survey findings personas",
        "{topic} customer success manager revenue operations head of operations pain points",
    ],
    "gtm": [
        "{topic} go to market strategy distribution channels launch playbook",
        "{topic} acquisition channels SEO outbound partnerships communities benchmark",
        "{topic} pricing model packaging subscription retainers project fees",
        "{topic} CAC LTV benchmark payback period sales cycle",
        "{topic} product hunt linkedin outbound founder led sales case study",
        "{topic} conversion funnel onboarding trial demo benchmark",
        "{topic} growth tactics launch examples competitors",
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

_FOCUS_ALIASES = {
    "market": "market",
    "markets": "market",
    "research": "market",
    "competitor": "competitors",
    "competitors": "competitors",
    "customer": "customers",
    "customers": "customers",
    "icp": "customers",
    "persona": "customers",
    "gtm": "gtm",
    "go-to-market": "gtm",
    "go_to_market": "gtm",
    "distribution": "gtm",
    "execution": "execution",
}

_TOPIC_NOISE_PATTERNS = (
    r"\bvalidate the market\b",
    r"\btarget customer\b",
    r"\bcompetitor intel\b",
    r"\bresearch gtm\b",
    r"\bgo to market\b",
    r"\bpricing and launch playbook\b",
    r"\bbuild(?:ing)? repeatable sales and delivery engine\b",
    r"\busing run research pipeline\b",
)

_ENTITY_PROFILE_PREFIX = re.compile(r"^(?:what|who)\s+is\s+", re.IGNORECASE)
_COMPARISON_PATTERN = re.compile(r"\bcompare\s+(.+?)\s+(?:to|with|vs\.?|versus)\s+(.+?)(?:[?.!]|$)", re.IGNORECASE)


def _is_entity_profile_request(topic: str) -> bool:
    """Recognize short founder questions about one named organization.

    Treating ``what is Acme?`` as a market-sizing request produces six nearly
    identical searches and makes a well-known company look like a coverage
    failure.  Entity profiles need authoritative company and third-party
    corroboration first.
    """
    return bool(_ENTITY_PROFILE_PREFIX.match((topic or "").strip()))


def _comparison_subjects(topic: str) -> tuple[str, str] | None:
    """Extract the two explicit subjects from a founder comparison request."""
    match = _COMPARISON_PATTERN.search((topic or "").strip())
    if not match:
        return None
    left, right = (part.strip(" ,? ") for part in match.groups())
    return (left, right) if left and right else None


def _normalize_focus(focus: str) -> str:
    key = re.sub(r"[\s_]+", "-", (focus or "market").strip().lower())
    return _FOCUS_ALIASES.get(key, "market")


def _normalize_research_topic(topic: str) -> str:
    text = re.sub(r"\s+", " ", (topic or "").strip())
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"[|]+", " ", text)
    text = re.split(r"(?:\n|;)", text, maxsplit=1)[0]
    if ":" in text:
        prefix, suffix = text.split(":", 1)
        if len(prefix.split()) <= 5 and len(suffix.split()) >= 3:
            text = suffix.strip()
    for pattern in _TOPIC_NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(please|help|need|want|make sure|figure out)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    words = text.split()
    if len(words) > 18:
        text = " ".join(words[:18])
    return text


def _resource_search_topic(topic: str, focus: str) -> str:
    """Turn a founder/product pitch into a resource-oriented search subject."""
    text = _normalize_research_topic(topic)
    lowered = text.lower()
    pitch_markers = ("frontier", "sota", "single plan", "replace multiple", "existing workflows", "$20")
    if not any(marker in lowered for marker in pitch_markers):
        return text
    if focus == "competitors":
        return "AI model aggregation platforms LLM gateways unified AI access tools"
    if focus == "customers":
        return "teams managing multiple AI coding assistants and model subscriptions"
    if focus == "gtm":
        return "AI model aggregation and LLM gateway software companies"
    return "AI model aggregation and LLM gateway software market"


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


def _coerce_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("url", "href", "link", "query", "title", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except Exception:
            return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_coerce_text(item).strip() for item in value]
        return " ".join(part for part in parts if part)
    return str(value or "")


def _normalize_url(url: object) -> str:
    url = _coerce_text(url).strip()
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


def build_research_queries(topic: str, focus: str = "market", limit: int = _RESEARCH_QUERY_PLAN_LIMIT) -> dict:
    """Build source-seeking search queries for a research lane.

    This gives agents a deterministic, high-coverage query plan before they
    start browsing, instead of relying on the model to invent a good search mix
    every run.
    """
    clean_topic = _normalize_research_topic(topic)
    if not clean_topic:
        return {"topic": topic, "focus": focus, "queries": [], "error": "topic is required"}
    normalized_focus = _normalize_focus(focus)
    resource_topic = _resource_search_topic(clean_topic, normalized_focus)
    entity_subject = _ENTITY_PROFILE_PREFIX.sub("", clean_topic).strip(" ?")
    comparison = _comparison_subjects(clean_topic)
    if comparison:
        left, right = comparison
        queries = [
            f"{left} pricing plans official",
            f"{right} pricing plans official",
            f"{left} product features target customers official",
            f"{right} product features target customers official",
            f"{left} terms privacy security official",
            f"{right} terms privacy security official",
        ]
    elif _is_entity_profile_request(clean_topic) and entity_subject:
        queries = [
            f"{entity_subject} official website company about product",
            f"{entity_subject} funding investors company profile",
            f"{entity_subject} customers reviews alternatives",
            f"{entity_subject} news launch partnerships",
            f"{entity_subject} pricing product features",
            f"{entity_subject} founder team company profile",
        ]
    else:
        queries = [template.format(topic=resource_topic) for template in _QUERY_BLUEPRINTS[normalized_focus]]
    deduped = []
    seen = set()
    for query in queries:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(query)
    return {
        "topic": clean_topic,
        "resource_topic": resource_topic,
        "focus": normalized_focus,
        "queries": deduped[: max(1, min(limit, _RESEARCH_QUERY_PLAN_LIMIT))],
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


def _extract_text(html: str, max_chars: int = _RESEARCH_FETCH_TEXT_CHAR_CAP) -> str:
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
    text = re.sub(r"\s+", " ", _coerce_text(query)).strip()
    if not text:
        return ""
    # Research agents often pass full natural-language questions or prompt
    # sentences into search. Keep the high-signal subject after a colon and
    # strip long example lists so SearXNG/CRW don't choke on paragraph-sized
    # queries.
    if ":" in text:
        lead, tail = text.split(":", 1)
        if len(tail.strip()) >= 24 and len(lead.strip()) <= 120:
            text = tail.strip()
    text = re.sub(r"\([^)]{25,}\)", "", text)
    text = re.sub(
        r"^(identify|articulate|derive|explain|find|research|map|summarize|outline|determine)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(what are|what is|who are|how do|why do)\s+", "", text, flags=re.IGNORECASE)
    text = text.replace("—", " ").replace("–", " ")
    text = re.sub(r"\s+", " ", text).strip(" -,:;")
    words = text.split()
    if len(words) > _MAX_SEARCH_QUERY_WORDS:
        text = " ".join(words[:_MAX_SEARCH_QUERY_WORDS])
    if len(text) > _MAX_SEARCH_QUERY_CHARS:
        text = text[:_MAX_SEARCH_QUERY_CHARS].rsplit(" ", 1)[0].strip()
    return text.strip(" -,:;")


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


def _research_query_terms(query: str) -> set[str]:
    return {
        token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{2,}", (query or "").lower())
        if token not in _RESEARCH_QUERY_STOPWORDS
    }


def _split_research_blocks(text: str) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not cleaned:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    if len(blocks) > 1:
        return blocks
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    windowed: list[str] = []
    for index in range(0, len(sentences), _RESEARCH_BLOCK_WINDOW_SENTENCES):
        block = " ".join(part.strip() for part in sentences[index:index + _RESEARCH_BLOCK_WINDOW_SENTENCES] if part.strip()).strip()
        if block:
            windowed.append(block)
    return windowed or [cleaned]


def _score_research_block(block: str, query_terms: set[str]) -> tuple[int, int]:
    lowered = block.lower()
    block_terms = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{2,}", lowered))
    overlap = len(query_terms & block_terms)
    numeric_hits = len(re.findall(r"\b\d+(?:\.\d+)?(?:%|x|k|m|b)?\b", block))
    currency_hits = len(re.findall(r"[$€£]\s?\d", block))
    year_hits = len(re.findall(r"\b20\d{2}\b", block))
    keyword_hits = len(re.findall(r"\b(cagr|tam|sam|som|pricing|revenue|growth|benchmark|market share|margin|funding)\b", lowered))
    score = overlap * 6 + numeric_hits * 2 + currency_hits * 2 + year_hits * 2 + keyword_hits * 3
    return score, overlap


def _compact_research_evidence(content: str, query: str, max_chars: int) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    query_terms = _research_query_terms(query)
    blocks = _split_research_blocks(text)
    ranked: list[tuple[int, int, int, str]] = []
    for index, block in enumerate(blocks):
        score, overlap = _score_research_block(block, query_terms)
        ranked.append((score, overlap, index, block))

    selected_indices: set[int] = set()
    chosen: list[tuple[int, str]] = []
    used = 0

    for score, overlap, index, block in sorted(ranked, key=lambda item: (item[0], item[1], -item[2]), reverse=True):
        if used >= max_chars and chosen:
            break
        if chosen and score <= 0 and overlap == 0:
            continue
        piece = block if len(block) <= max_chars else block[:max_chars].rsplit(" ", 1)[0].strip()
        projected = used + len(piece) + (2 if chosen else 0)
        if projected > max_chars and chosen:
            continue
        selected_indices.add(index)
        chosen.append((index, piece))
        used = projected

    if not chosen:
        head = text[: max_chars // 2].rsplit(" ", 1)[0].strip()
        tail = text[-(max_chars // 3):].split(" ", 1)[-1].strip()
        fallback = "\n...\n".join(part for part in [head, tail] if part)
        return fallback[:max_chars].strip()

    chosen.sort(key=lambda item: item[0])
    compacted = "\n\n".join(piece for _, piece in chosen).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[:max_chars].rsplit(" ", 1)[0].strip()


def fetch_and_read(url: str = "", cancellation_fence=None) -> dict:
    """Fetch a URL, return clean text. Blocked/paywalled domains auto-skipped."""
    if _cancelled(cancellation_fence):
        return {"url": url, "error": "cancelled", "content": ""}
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
        content = _extract_text(html, max_chars=_RESEARCH_FETCH_TEXT_CHAR_CAP)

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


def search_and_fetch(query: str = "", max_results: int = 16, url: str = "", cancellation_fence=None) -> dict:
    """Search web then fetch full page content from each result.

    Models sometimes call this with a `url` kwarg (confusing it with
    fetch_and_read) when they already have a specific page in mind — route
    that straight to fetch_and_read instead of silently dropping the arg and
    falling back to an unrelated auto-generated query."""
    if _cancelled(cancellation_fence):
        return {"query": query or url, "results": [], "error": "cancelled"}
    if url and not query:
        page = _call_with_optional_cancellation(fetch_and_read, url, cancellation_fence=cancellation_fence)
        return {"query": url, "results": [page] if page else [], "routed_to": "fetch_and_read"}
    if isinstance(query, (list, tuple)):
        queries = _dedupe_search_queries(list(query), limit=12)
        if not queries:
            return {"error": "query is required — pass a search string, e.g. \"competitor pricing SaaS\""}
        if len(queries) == 1:
            query = queries[0]
        else:
            return _call_with_optional_cancellation(
                batch_search, queries, max_results_each=max_results, cancellation_fence=cancellation_fence
            )
    if not query:
        return {"error": "query is required — pass a search string, e.g. \"competitor pricing SaaS\""}
    search_limit = max(max_results + _RESEARCH_MAX_URL_CANDIDATES_BUFFER, int(max_results * _RESEARCH_SEARCH_MULTIPLIER))
    raw = _robust_search(query, max_results=search_limit)
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
    fetch_urls = fetch_urls[:max_results + _RESEARCH_MAX_URL_CANDIDATES_BUFFER]

    with ThreadPoolExecutor(max_workers=min(len(fetch_urls) or 1, 8)) as ex:
        futures = {
            ex.submit(_call_with_optional_cancellation, fetch_and_read, url, cancellation_fence=cancellation_fence): url
            for url in fetch_urls
        }
        for fut in as_completed(futures, timeout=25):
            if _cancelled(cancellation_fence):
                for pending in futures:
                    pending.cancel()
                break
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
            formatted.append(_compact_research_evidence(r["content"], query, _RESEARCH_RESULT_CONTENT_CHAR_CAP))
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


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return {}
    return {}


def _research_llm_json(prompt: str, max_tokens: int = 900) -> dict:
    from backend.config import settings
    from backend.core.llm_cache import openrouter_extra_body
    from backend.core.llm_client import get_or_client

    model = getattr(settings, "or_light_model", "") or "inclusionai/ling-2.6-flash"
    client = get_or_client(settings.openrouter_base_url, timeout=120.0)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt + "\n\nRespond with ONLY a single valid JSON object. No prose, no markdown fences."}],
        max_tokens=max_tokens,
        temperature=0.2,
        extra_body=openrouter_extra_body(model),
        timeout=120.0,
    )
    content = ((resp.choices[0].message.content if getattr(resp, "choices", None) else "") or "").strip()
    return _parse_json_object(content)


def _format_batch_answer(search_result: dict, query: str) -> str:
    formatted = (search_result.get("formatted") or "").strip()
    source_lines = [f"[{source.get('id') or 'unassigned'}] {source.get('title') or source.get('url') or ''} | {source.get('url') or ''}" for source in (search_result.get("sources") or [])[:6]]
    if formatted:
        return (formatted[:_RESEARCH_EVIDENCE_CHAR_CAP] + ("\nSource IDs:\n" + "\n".join(source_lines) if source_lines else ""))[:_RESEARCH_PER_QUERY_FORMATTED_CAP]
    return f"Query: {query}\n" + "\n".join(source_lines)


def _synthesize_research_round(queries: list[str], batch_result: dict, prior_learnings: Optional[list[str]] = None) -> dict:
    evidence_blocks = []
    for query in queries:
        result = (batch_result.get("results_by_query") or {}).get(query) or {}
        evidence_blocks.append(f"## QUERY: {query}\n{_format_batch_answer(result, query)}")
    prompt = (
        "You are synthesizing web research results.\n"
        "Extract concrete learnings and identify the highest-value follow-up research directions.\n"
        "Use only what is supported by the evidence blocks.\n\n"
        f"Prior learnings:\n{chr(10).join(f'- {item}' for item in (prior_learnings or [])) or '- none'}\n\n"
        "Evidence blocks:\n"
        + "\n\n".join(evidence_blocks)
        + "\n\nReturn JSON with this shape:\n"
        '{"learnings":["fact with number/company/date"],"directions":["specific unresolved question"],"summary":"short synthesis"}'
    )
    parsed = _research_llm_json(prompt, max_tokens=_RESEARCH_SYNTHESIS_MAX_TOKENS)
    learnings = [str(item).strip() for item in (parsed.get("learnings") or []) if str(item).strip()]
    directions = [str(item).strip() for item in (parsed.get("directions") or []) if str(item).strip()]
    return {
        "learnings": learnings[:12],
        "directions": directions[:_RECURSIVE_RESEARCH_MAX_FOLLOWUPS],
        "summary": str(parsed.get("summary") or "").strip(),
    }


def _build_followup_queries(directions: list[str], original_queries: list[str]) -> list[str]:
    if not directions:
        return []
    prompt = (
        "Turn research gaps into targeted web search queries.\n"
        f"Original queries:\n{chr(10).join(f'- {q}' for q in original_queries)}\n\n"
        f"Directions:\n{chr(10).join(f'- {d}' for d in directions)}\n\n"
        "Return JSON as {\"queries\": [\"...\"]}. Make the queries specific and source-seeking."
    )
    parsed = _research_llm_json(prompt, max_tokens=_RESEARCH_FOLLOWUP_MAX_TOKENS)
    return _dedupe_search_queries(parsed.get("queries") or [], limit=_RECURSIVE_RESEARCH_MAX_FOLLOWUPS)


def _final_answers_prompt(original_queries: list[str], aggregated_results: dict, learnings: list[str]) -> str:
    evidence_blocks = []
    for query in original_queries:
        result = aggregated_results.get(query) or {"query": query, "results": [], "formatted": "", "total": 0, "sources": []}
        evidence_blocks.append(f"## QUERY: {query}\n{_format_batch_answer(result, query)}")
    return (
        "Answer each research question using only the provided evidence.\n"
        "Be concise and concrete. Return one short synthesized answer per question. Every claim must list evidence_ids copied from the source IDs in its evidence block.\n\n"
        f"Shared learnings:\n{chr(10).join(f'- {item}' for item in learnings) or '- none'}\n\n"
        "Evidence blocks:\n"
        + "\n\n".join(evidence_blocks)
        + "\n\nReturn JSON as "
        '{"answers":[{"query":"exact question","answer":"concise synthesized answer","claims":[{"claim":"supported fact","evidence_ids":["src_1"]}]}]}'
    )


def _batched_final_answers(original_queries: list[str], aggregated_results: dict, learnings: list[str]) -> dict[str, dict]:
    parsed = _research_llm_json(
        _final_answers_prompt(original_queries, aggregated_results, learnings),
        max_tokens=_RESEARCH_FINAL_ANSWER_MAX_TOKENS,
    )
    answers: dict[str, dict] = {}
    items = parsed.get("answers")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if query and answer:
                allowed = {source.get("id") for source in (aggregated_results.get(query) or {}).get("sources", []) if source.get("id")}
                claims = [{"claim": str(claim.get("claim")).strip(), "evidence_ids": [i for i in claim.get("evidence_ids") or [] if i in allowed]} for claim in item.get("claims") or [] if isinstance(claim, dict) and str(claim.get("claim") or "").strip() and any(i in allowed for i in claim.get("evidence_ids") or [])]
                answers[query] = {"answer": answer, "claims": claims}
    if answers:
        return answers

    # Backward-compatible fallback if the LLM returns the old single-answer
    # shape or a dict keyed by query.
    if isinstance(parsed.get("answer"), str) and len(original_queries) == 1:
        return {original_queries[0]: {"answer": str(parsed.get("answer") or "").strip(), "claims": []}}
    raw_answers = parsed.get("answers")
    if isinstance(raw_answers, dict):
        for query, answer in raw_answers.items():
            query_text = str(query).strip()
            answer_text = str(answer.get("answer") if isinstance(answer, dict) else answer).strip()
            if query_text and answer_text:
                answers[query_text] = {"answer": answer_text, "claims": []}
    return answers


def _finalize_recursive_research(original_queries: list[str], aggregated_results: dict, learnings: list[str]) -> dict:
    results_by_query = {}
    combined = []
    all_sources = []
    seen_sources = set()
    source_ids = {}
    for result in aggregated_results.values():
        for source in result.get("sources") or []:
            if not source.get("id"):
                source["id"] = source_ids.setdefault(_normalize_url(source.get("url", "")), _source_id(len(source_ids) + 1))
    batched_answers = _batched_final_answers(original_queries, aggregated_results, learnings)

    for query in original_queries:
        result = aggregated_results.get(query) or {"query": query, "results": [], "formatted": "", "total": 0, "sources": []}
        answer_data = batched_answers.get(query, {})
        answer = answer_data.get("answer", "")
        citations = []
        for source in result.get("sources") or []:
            url = _normalize_url(source.get("url", ""))
            if url and url not in citations:
                citations.append(url)
            if url and url not in seen_sources:
                seen_sources.add(url)
                all_sources.append({"id": source.get("id"), "title": source.get("title", ""), "url": url})
        results_by_query[query] = {
            "answer": answer,
            "citations": citations,
            "total": len(citations),
            "claims": answer_data.get("claims", []),
        }
        combined.append(f"## {query}\n{answer}")

    return {
        "queries_run": len(original_queries),
        "results_by_query": results_by_query,
        "combined_formatted": "\n\n".join(combined),
        "sources": all_sources[:_RESEARCH_MAX_SOURCES],
    }


def _ddgs_fallback_search(query: str, max_results: int) -> dict:
    fallback = search_and_fetch(query, max_results=max_results)
    if fallback.get("error"):
        return {
            "query": query,
            "results": [],
            "formatted": "",
            "total": 0,
            "sources": [],
            "error": fallback.get("error"),
        }
    return fallback


def _crw_search_and_fetch(query: str, max_results: int = 8) -> dict:
    """Search + scrape one query via the self-hosted crw instance (single call —
    scrapeOptions does search and scrape together, no separate fetch round-trip).
    Returns the same {query, results, formatted, total, sources} shape
    search_and_fetch already uses, so callers don't need to branch on backend."""
    import httpx as _httpx
    from backend.config import settings as _settings

    if not _crw_available():
        fallback = _ddgs_fallback_search(query, max_results)
        fallback.setdefault("error", "crw_cooldown_active")
        return fallback

    base_url = (getattr(_settings, "crw_base_url", "") or "http://crw:3000").rstrip("/")
    try:
        r = _httpx.post(
            f"{base_url}/v1/search",
            json={
                "query": query,
                "limit": max(1, min(max_results, 20)),
                "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
            },
            timeout=_CRW_TIMEOUT_SECONDS,
        )
        data = r.json()
    except Exception as exc:
        _record_crw_result(False)
        logger.warning("crw search failed for %r, falling back to DDGS: %s", query, exc)
        fallback = _ddgs_fallback_search(query, max_results)
        fallback.setdefault("error", str(exc))
        return fallback

    if not data.get("success"):
        _record_crw_result(False)
        logger.warning("crw returned unsuccessful response for %r, falling back to DDGS", query)
        fallback = _ddgs_fallback_search(query, max_results)
        fallback.setdefault("error", "crw_search_failed")
        return fallback

    payload = data.get("data") or []
    if isinstance(payload, dict):
        items = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    if not items:
        _record_crw_result(False)
        logger.info("crw returned no results for %r, falling back to DDGS", query)
        fallback = _ddgs_fallback_search(query, max_results)
        fallback.setdefault("error", "crw_no_results")
        return fallback
    _record_crw_result(True)

    results, sources, blocks = [], [], []
    for item in items:
        url = _normalize_url(item.get("url", ""))
        title = item.get("title") or url
        content = (item.get("markdown") or "").strip()
        snippet = item.get("snippet") or item.get("description") or ""
        results.append({"url": url, "title": title, "snippet": snippet, "content": content})
        if url:
            sources.append({"title": title, "url": url})
        block = f"### {title}\nURL: {url}\n"
        block += _compact_research_evidence(content, query, _RESEARCH_RESULT_CONTENT_CHAR_CAP) if content else f"[snippet only] {snippet}"
        blocks.append(block)

    return {
        "query": query,
        "results": results,
        "formatted": f"Query: {query}\n" + "\n\n".join(blocks),
        "total": len(results),
        "sources": sources,
    }


def _crw_batch_search(queries=None, max_results_each: int = 8, cancel_event=None) -> dict:
    """Run search+scrape for several queries against crw in parallel — the
    same output contract as batch_search (DDGS-backed), so the recursive
    sonar_research loop can call either interchangeably."""
    if not queries:
        return {"queries_run": 0, "results_by_query": {}, "combined_formatted": "", "sources": []}
    queries = _dedupe_search_queries(list(queries), limit=12)
    if cancel_event is not None and cancel_event.is_set():
        return {"queries_run": 0, "results_by_query": {}, "combined_formatted": "", "sources": [], "cancelled": True}

    results_by_query: dict = {}
    ex = ThreadPoolExecutor(max_workers=min(len(queries), 4))
    futures = {ex.submit(_crw_search_and_fetch, q, max_results_each): q for q in queries}
    timed_out = False
    try:
        try:
            for fut in as_completed(futures, timeout=_CRW_BATCH_TIMEOUT_SECONDS):
                if cancel_event is not None and cancel_event.is_set():
                    timed_out = True
                    break
                q = futures[fut]
                try:
                    results_by_query[q] = fut.result()
                except Exception as e:
                    results_by_query[q] = {"query": q, "results": [], "formatted": "", "total": 0, "sources": [], "error": str(e)}
        except TimeoutError:
            timed_out = True
            _record_crw_result(False)
            for fut, q in futures.items():
                if q not in results_by_query:
                    fut.cancel()
                    results_by_query[q] = {"query": q, "results": [], "formatted": "", "total": 0, "sources": [], "error": "crw_search_timeout"}
    finally:
        if timed_out or (cancel_event is not None and cancel_event.is_set()):
            for fut, q in futures.items():
                results_by_query.setdefault(q, {"query": q, "results": [], "formatted": "", "total": 0, "sources": [], "error": "cancelled" if cancel_event is not None and cancel_event.is_set() else "crw_search_timeout"})
            _shutdown_executor(ex, futures)
        else:
            ex.shutdown(wait=True)

    combined, all_sources, seen = [], [], set()
    for q, r in results_by_query.items():
        combined.append(f"\n\n## QUERY: {q}\n{r.get('formatted', '')[:_RESEARCH_COMBINED_QUERY_CHAR_CAP]}")
        for source in r.get("sources", []):
            url = _normalize_url(source.get("url", ""))
            if url and url not in seen:
                seen.add(url)
                all_sources.append({**source, "url": url})

    return {
        "queries_run": len(queries),
        "results_by_query": {q: {"total": r.get("total", 0), "formatted": r.get("formatted", "")[:_RESEARCH_PER_QUERY_FORMATTED_CAP], "sources": r.get("sources", []), **({"error": r["error"]} if r.get("error") else {})} for q, r in results_by_query.items()},
        "combined_formatted": "\n".join(combined),
        "sources": all_sources[:_RESEARCH_MAX_SOURCES],
    }


def _legacy_sonar_research(queries: list[str]) -> dict:
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
        "sources": all_sources[:_RESEARCH_MAX_SOURCES],
    }


def deep_research(queries=None, max_rounds: int | None = None, recursive_depth: int | None = None, cancel_event=None, cancellation_fence=None) -> dict:
    """Run recursive crw (self-hosted search+scrape) + ling web research, preserving the existing output contract."""
    cancel_event = _coerce_cancel_event(cancel_event, cancellation_fence)
    if not queries:
        return {"error": "queries required — pass a list of research question strings"}
    if isinstance(queries, str):
        queries = [queries]
    queries = _dedupe_search_queries(list(queries), limit=12)
    if not queries:
        return {"error": "queries required — pass a list of research question strings"}

    import os

    if os.environ.get("ASTRA_RESEARCH_USE_LEGACY_SONAR", "").lower() in {"1", "true", "yes"}:
        return _legacy_sonar_research(queries)

    with _research_tool_slot():
        aggregated_results: dict[str, dict] = {}
        learnings: list[str] = []
        round_queries = list(queries)
        avg_query_len = sum(len(q) for q in queries) / max(len(queries), 1)
        requested_rounds = max_rounds if max_rounds is not None else recursive_depth
        effective_max_rounds = (1 if len(queries) >= 6 or avg_query_len > 120 else _RECURSIVE_RESEARCH_ROUNDS) if requested_rounds is None else max(1, min(int(requested_rounds), _RECURSIVE_RESEARCH_ROUNDS))

        from backend.config import settings as _dr_settings

        for round_index in range(effective_max_rounds):
            if not round_queries or (cancel_event is not None and cancel_event.is_set()):
                break
            # Native provider-grounded search (OpenRouter's web plugin against
            # settings.native_research_model, e.g. Gemini's built-in Google Search
            # grounding) replaces the crw+searxng+lightpanda scrape pipeline as the
            # default path -- crw has no chrome/JS-renderer tier deployed (see
            # config.docker.toml), so anti-bot-heavy pages routinely timed out and
            # tripped the circuit breaker under concurrent multi-lane research,
            # confirmed live this session. Same results_by_query/sources/
            # combined_formatted contract either way, so nothing downstream changes.
            if _dr_settings.native_research_enabled:
                search = _native_research_pass("", "general research", round_queries, cancellation_fence=cancel_event)
            else:
                search = _crw_batch_search(round_queries, max_results_each=5) if cancel_event is None else _crw_batch_search(round_queries, max_results_each=5, cancel_event=cancel_event)
            batch_results = search.get("results_by_query") or {}
            for query, result in batch_results.items():
                existing = aggregated_results.get(query)
                if not existing:
                    aggregated_results[query] = {
                        "query": query,
                        "formatted": result.get("formatted", ""),
                        "total": result.get("total", 0),
                        "sources": [],
                    }
                merged = aggregated_results[query]
                merged["formatted"] = (
                    (merged.get("formatted") or "")
                    + ("\n\n" if merged.get("formatted") else "")
                    + (result.get("formatted") or "")
                )[:_RESEARCH_PER_QUERY_FORMATTED_CAP]
                merged["total"] = max(int(merged.get("total") or 0), int(result.get("total") or 0))
            for query, result in batch_results.items():
                bucket = aggregated_results.setdefault(query, {"query": query, "formatted": "", "total": 0, "sources": []})
                for source in result.get("sources") or []:
                    url = _normalize_url(source.get("url", ""))
                    if url and not any(_normalize_url(item.get("url", "")) == url for item in bucket["sources"]):
                        bucket["sources"].append({**source, "url": url})

            synthesis = _synthesize_research_round(round_queries, search, prior_learnings=learnings)
            for item in synthesis.get("learnings", []):
                if item not in learnings:
                    learnings.append(item)
            if round_index >= effective_max_rounds - 1 or (cancel_event is not None and cancel_event.is_set()):
                break
            round_queries = _build_followup_queries(synthesis.get("directions", []), queries)

        if cancel_event is not None and cancel_event.is_set():
            return {
                "queries_run": 0,
                "results_by_query": {},
                "combined_formatted": "",
                "sources": [],
                "error": "cancelled",
            }
        return _finalize_recursive_research(queries, aggregated_results, learnings)


def sonar_research(queries=None, cancellation_fence=None) -> dict:
    """Backward-compatible alias for deep_research."""
    return _call_with_optional_cancellation(deep_research, queries, cancellation_fence=cancellation_fence)


def batch_search(queries=None, max_results_each: int = 8, cancellation_fence=None) -> dict:
    """Run search queries in parallel and return combined results."""
    if not queries:
        return {"error": "queries is required — pass a list of search strings, e.g. [\"competitor A pricing\", \"competitor B features\"]"}
    queries = _dedupe_search_queries(list(queries), limit=12)
    if not queries:
        return {"error": "queries is required — pass a list of search strings, e.g. [\"competitor A pricing\", \"competitor B features\"]"}
    results_by_query: dict = {}

    with _research_tool_slot():
        with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as ex:
            futures = {
                ex.submit(
                    _call_with_optional_cancellation,
                    search_and_fetch,
                    q,
                    max_results_each,
                    cancellation_fence=cancellation_fence,
                ): q
                for q in queries
            }
            # Process-wide search gate serializes calls (~1s apart) and each query
            # retries with backoff, so a parallel batch can take well over a minute.
            # Catch the overall timeout and return whatever finished — partial
            # results beat an all-or-nothing "N futures unfinished" failure.
            try:
                for fut in as_completed(futures, timeout=110):
                    if _cancelled(cancellation_fence):
                        for pending in futures:
                            pending.cancel()
                        break
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
    compact_results = {}
    for q, r in results_by_query.items():
        combined.append(f"\n\n## QUERY: {q}\n{r.get('formatted', '')[:_RESEARCH_COMBINED_QUERY_CHAR_CAP]}")
        per_query_sources = []
        for source in r.get("sources", []):
            url = _normalize_url(source.get("url", ""))
            if url:
                per_query_sources.append({**source, "url": url})
            if url and url not in seen_sources:
                seen_sources.add(url)
                all_sources.append({**source, "url": url})
        compact_results[q] = {
            "total": r.get("total", 0),
            "formatted": r.get("formatted", "")[:_RESEARCH_PER_QUERY_FORMATTED_CAP],
            "sources": per_query_sources,
        }

    return {
        "queries_run": len(queries),
        "results_by_query": compact_results,
        "combined_formatted": "\n".join(combined),
        "sources": all_sources[:_RESEARCH_MAX_SOURCES],
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


def run_research_pipeline(topic: str, focus: str = "market", max_results_each: int = 8, cancellation_fence=None) -> dict:
    """Plan and run a complete source-diverse research pass.

    Agents should use this when they need reliable first-pass evidence quickly:
    it plans lane-specific queries, executes them in parallel, dedupes sources,
    and returns a compact evidence package for synthesis.
    """
    plan = build_research_queries(topic, focus=focus, limit=_RESEARCH_QUERY_PLAN_LIMIT)
    queries = plan.get("queries", [])
    if not queries:
        return {
            **plan,
            "results_by_query": {},
            "sources": [],
            "combined_formatted": "",
            "coverage": {"ready": False, "gaps": ["topic is required"], "source_count": 0, "domain_count": 0},
        }
    from backend.config import settings
    with _research_tool_slot():
        if _cancelled(cancellation_fence):
            search = {"queries_run": 0, "results_by_query": {}, "sources": [], "combined_formatted": "", "error": "cancelled"}
        else:
            search = (
                _call_with_optional_cancellation(
                    _native_research_pass,
                    plan["resource_topic"],
                    plan["focus"],
                    queries,
                    cancellation_fence=cancellation_fence,
                )
                if settings.native_research_enabled
                else _call_with_optional_cancellation(
                    batch_search,
                    queries,
                    max_results_each=max_results_each,
                    cancellation_fence=cancellation_fence,
                )
            )
    coverage = _research_coverage(plan["focus"], queries, search)
    # Wave 5.3: one canonical ResearchResult per query, built from the exact
    # same results_by_query/sources/coverage this function already returns --
    # to_research_result() is a pure mapping, so this can never change the
    # legacy fields above, only add "structured" alongside them.
    results_by_query = search.get("results_by_query", {})
    pipeline_sources = search.get("sources", [])
    structured = {
        query: research_result_to_dict(
            to_research_result(
                new_query_id(query),
                query,
                results_by_query.get(query, {}),
                sources=pipeline_sources,
                coverage_ready=coverage["ready"],
                run_id=None,
                step_id=None,
            )
        )
        for query in queries
    }
    return {
        "topic": plan["topic"],
        "focus": plan["focus"],
        "queries": queries,
        "queries_run": search.get("queries_run", 0),
        "results_by_query": results_by_query,
        "sources": pipeline_sources,
        "source_count": coverage["source_count"],
        "source_domains": coverage["source_domains"],
        "coverage": coverage,
        "combined_formatted": search.get("combined_formatted", ""),
        "structured": structured,
        "next_step": (
            "Synthesize findings with concrete numbers, named companies, dates, caveats, and URLs."
            if coverage["ready"]
            else "Evidence is thin. Fill coverage gaps before making strong claims, or explicitly label uncertainty."
        ),
    }


def _native_research_pass(topic: str, focus: str, queries: list[str], cancellation_fence=None) -> dict:
    """Run one provider-native grounded pass instead of recursive local search."""
    if _cancelled(cancellation_fence):
        return {"queries_run": 0, "results_by_query": {}, "sources": [], "combined_formatted": "", "error": "cancelled"}
    if len(queries) > 1:
        aggregate = {"queries_run": 0, "results_by_query": {}, "sources": [], "combined_formatted": ""}
        seen_urls = set()
        for query in queries:
            if _cancelled(cancellation_fence):
                aggregate["error"] = "cancelled"
                break
            one = _native_research_pass(topic, focus, [query], cancellation_fence=cancellation_fence)
            aggregate["queries_run"] += int(one.get("queries_run", 0))
            aggregate["results_by_query"].update(one.get("results_by_query") or {})
            aggregate["combined_formatted"] += ("\n\n" if aggregate["combined_formatted"] else "") + (one.get("combined_formatted") or "")
            for source in one.get("sources") or []:
                url = source.get("url") if isinstance(source, dict) else None
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    aggregate["sources"].append(source)
        return aggregate
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    from backend.core.llm_cache import openrouter_extra_body
    from backend.core.llm_client import get_or_client

    model = settings.native_research_model
    prompt = (
        "Research resources, not the named product. Do not search for the company name unless it is an established public company.\n"
        f"Research subject: {topic}\nFocus: {focus}\n\n"
        "Answer the following source-seeking questions with concrete facts, dates, pricing, named resources, and URLs. Return ONLY JSON: {\"answers\":[{\"query\":\"exact input question\",\"answer\":\"grounded answer\",\"citation_urls\":[\"https://...\"]}]}. Include an answers item only when you have evidence for that exact question. Keep each answer under 120 words and return at most one answer per input question.\n"
        + "\n".join(f"{i + 1}. {query}" for i, query in enumerate(queries))
        + "\nPrefer primary sources, analyst reports, pricing pages, public datasets, and credible reviews."
    )
    client = get_or_client(settings.openrouter_base_url, get_openrouter_key() or settings.agent_model_api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
        temperature=0.2,
        extra_body=(None if "search-preview" in model else openrouter_extra_body(model, {"plugins": [{"id": "web", "engine": "native"}]})),
        timeout=180.0,
    )
    message = resp.choices[0].message if getattr(resp, "choices", None) else None
    answer = ((getattr(message, "content", None) if message else None) or "").strip()
    sources = []
    for annotation in (getattr(message, "annotations", None) or []) if message else []:
        citation = annotation.get("url_citation", {}) if isinstance(annotation, dict) else getattr(annotation, "url_citation", {})
        url = citation.get("url", "") if isinstance(citation, dict) else getattr(citation, "url", "")
        title = citation.get("title", "") if isinstance(citation, dict) else getattr(citation, "title", "")
        if url:
            sources.append({"url": _normalize_url(url), "title": title})
    unique_sources = []
    seen_urls = set()
    for source in sources:
        if source["url"] in seen_urls:
            continue
        seen_urls.add(source["url"])
        unique_sources.append(source)
    sources = [dict(source, id=_source_id(index)) for index, source in enumerate(unique_sources[:_RESEARCH_MAX_SOURCES], start=1)]
    parsed_answers = _parse_json_object(answer).get("answers")
    # Some native-search providers return source URLs in the requested JSON but
    # omit SDK annotations.  Preserve those URLs as citations so a grounded
    # result does not become an empty-source failure solely due to transport
    # shape. They remain visible in the artifact for review.
    if isinstance(parsed_answers, list):
        for item in parsed_answers:
            if not isinstance(item, dict):
                continue
            for raw_url in item.get("citation_urls") or []:
                normalized = _normalize_url(raw_url)
                parsed_url = urlparse(normalized)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    continue
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                sources.append({
                    "url": normalized,
                    "title": "Native research citation",
                    "id": _source_id(len(sources) + 1),
                })
    results_by_query = {}
    combined = []
    if isinstance(parsed_answers, list):
        by_url = {source["url"]: source for source in sources}
        for item in parsed_answers:
            query, response = str(item.get("query") or "").strip(), str(item.get("answer") or "").strip()
            if not response:
                continue
            if query not in queries:
                if len(queries) == 1:
                    query = queries[0]
                else:
                    def _tokens(value):
                        return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}
                    query_tokens = _tokens(query)
                    best_query = max(queries, key=lambda candidate: len(query_tokens & _tokens(candidate)))
                    overlap = len(query_tokens & _tokens(best_query)) / max(1, len(query_tokens))
                    if overlap < 0.2:
                        continue
                    query = best_query
            cited = [by_url[url] for url in (_normalize_url(url) for url in item.get("citation_urls") or [] if isinstance(url, str)) if url in by_url]
            if not cited and len(parsed_answers) == 1:
                cited = sources
            ids = [source["id"] for source in cited]
            results_by_query[query] = {"answer": response, "citations": ids, "claims": [{"claim": response, "evidence_ids": ids}] if ids else [], "formatted": response[:_RESEARCH_EVIDENCE_CHAR_CAP], "sources": cited, "total": len(ids)}
            combined.append(f"## {query}\n{response}")
    elif len(queries) == 1 and answer:
        ids = [source["id"] for source in sources]
        results_by_query[queries[0]] = {"answer": answer, "citations": ids, "claims": [{"claim": answer, "evidence_ids": ids}] if ids else [], "formatted": answer[:_RESEARCH_EVIDENCE_CHAR_CAP], "sources": sources, "total": len(ids)}
        combined.append(f"## {queries[0]}\n{answer}")
    return {
        "queries_run": len(results_by_query),
        "results_by_query": results_by_query,
        "sources": sources,
        "combined_formatted": "\n\n".join(combined)[:_RESEARCH_COMBINED_QUERY_CHAR_CAP],
    }


def to_research_result(
    query_id: str,
    question: str,
    native_result: dict,
    sources: Optional[list] = None,
    coverage_ready: Optional[bool] = None,
    run_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> ResearchResult:
    """Adapter (Wave 5.3 — Research Engine V2): map this module's EXISTING
    native-search per-query result shapes into the canonical ResearchResult
    schema (research_schema.py). Pure mapping — does not touch native
    search/synthesis logic at all.

    native_result is whatever `results_by_query[question]` already looks
    like, from any of this module's three pipelines:
      - _native_research_pass (run_research_pipeline w/ native_research_enabled):
        {"answer","citations","claims","sources","total","formatted"} — carries
        its own per-query "sources" list.
      - _finalize_recursive_research (this module's own deep_research()):
        {"answer","citations","total","claims"} — evidence_ids in "claims"
        reference ids ("src_1", ...) from the PIPELINE-level source list, not
        a per-query one. Pass that list via `sources` (deep_research()'s
        top-level "sources") so those ids resolve to real url/title.
      - batch_search / run_research_pipeline's non-native path:
        {"total","formatted","sources"} — no LLM-synthesized "claims"/"answer".

    sources: optional pipeline-level source list (falls back to
    native_result.get("sources") when omitted, which is enough for the
    native-pass shape above but not the recursive-pipeline shape).

    coverage_ready: pass run_research_pipeline's `coverage["ready"]` (the
    existing readiness signal from _research_coverage) to translate directly
    into escalation_decision. `_research_coverage` is pipeline-wide (source
    count, domain diversity, query coverage across ALL queries), so it can't
    be recomputed from a single query's native_result; when the caller
    doesn't have it, this falls back to a per-query heuristic (did this
    query return any citations at all) with the exact same
    sufficient/escalate_to_deep vocabulary.
    """
    native_result = native_result or {}
    source_pool = list(sources) if sources is not None else list(native_result.get("sources") or [])

    retrieved_at = now_iso()
    raw_evidence: list[Evidence] = []
    url_to_id_hints: dict[str, list[str]] = {}
    for src in source_pool:
        if not isinstance(src, dict):
            continue
        url = _normalize_url(src.get("url", ""))
        if not url or not url.startswith("http"):
            continue
        title = str(src.get("title") or "")
        raw_evidence.append({
            "evidence_id": new_evidence_id(url, ""),
            "source_url": url,
            "title": title,
            "domain": _domain(url),
            "published_at": None,  # native search doesn't surface publish dates today
            "retrieved_at": retrieved_at,
            # search_and_fetch's per-query "sources" list only ever carries
            # title/url (see its construction) -- no snippet/content survives
            # to this point, so excerpt is honestly empty rather than
            # fabricated. TODO: thread snippet/content through if a future
            # refactor keeps it attached to the source dict.
            "excerpt": "",
        })
        if src.get("id"):
            url_to_id_hints.setdefault(url, []).append(str(src["id"]))

    evidence = deduplicate_evidence(raw_evidence)
    for ev in evidence:
        try:
            write_evidence_artifact(run_id, step_id, ev)
        except Exception:
            logger.debug("write_evidence_artifact raised unexpectedly", exc_info=True)

    # Map every ref a claim's evidence_ids might use (a source "id" like
    # "src_1", or a raw citation URL) to the evidence_id actually kept after
    # dedup. Note: if two distinct literal URLs normalize to the same dedupe
    # key (e.g. tracking-param variants), only the survivor's hints resolve
    # -- the same "keep first occurrence" rule deduplicate_evidence applies.
    evidence_id_by_ref: dict[str, str] = {}
    for ev in evidence:
        url = ev["source_url"]
        evidence_id_by_ref[url] = ev["evidence_id"]
        for source_id in url_to_id_hints.get(url, []):
            evidence_id_by_ref[source_id] = ev["evidence_id"]

    claims: list[Claim] = []
    for raw_claim in native_result.get("claims") or []:
        if not isinstance(raw_claim, dict):
            continue
        text = str(raw_claim.get("claim") or "").strip()
        if not text:
            continue
        mapped_ids: list[str] = []
        for ref in raw_claim.get("evidence_ids") or []:
            eid = evidence_id_by_ref.get(str(ref))
            if eid and eid not in mapped_ids:
                mapped_ids.append(eid)
        claim_id = new_claim_id(query_id, text)
        if mapped_ids:
            claims.append({
                "claim_id": claim_id,
                "text": text,
                "evidence_ids": mapped_ids,
                "confidence": 1.0,
                "contradicted": False,
                "contradiction_note": "",
            })
        else:
            # Guard against silently dropping a claim with zero matched
            # evidence -- label it rather than drop it.
            claims.append({
                "claim_id": claim_id,
                "text": text,
                "evidence_ids": [],
                "confidence": 0.0,
                "contradicted": False,
                "contradiction_note": "unsupported: no evidence available",
            })

    if not claims:
        # batch_search / non-native pipeline: no LLM-synthesized claims at
        # all, just raw search results. Fall back to the synthesized
        # "answer" (if any) as a single claim rather than reporting zero
        # claims when evidence clearly exists.
        answer = str(native_result.get("answer") or "").strip()
        if answer:
            all_ids = [e["evidence_id"] for e in evidence]
            claims.append({
                "claim_id": new_claim_id(query_id, answer),
                "text": answer,
                "evidence_ids": all_ids,
                "confidence": 0.5 if all_ids else 0.0,
                "contradicted": False,
                "contradiction_note": "" if all_ids else "unsupported: no evidence available",
            })

    total = int(native_result.get("total") or 0)
    coverage_gaps: list[str] = [] if (total > 0 or evidence) else [question]

    if coverage_ready is not None:
        escalation_decision = "sufficient" if coverage_ready else "escalate_to_deep"
    else:
        # Per-query fallback mirroring _research_coverage's cheapest signal
        # (did this query return anything at all) when the caller doesn't
        # have the pipeline-wide coverage object.
        escalation_decision = "sufficient" if total > 0 else "escalate_to_deep"

    return {
        "query_id": query_id,
        "question": question,
        "claims": claims,
        "evidence": evidence,
        "coverage_gaps": coverage_gaps,
        "escalation_decision": escalation_decision,
    }

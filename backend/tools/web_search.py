import logging
import re
from typing import Optional
from urllib.parse import urlparse

from backend.config import settings
from backend.tools.research_evidence import write_evidence_artifact
from backend.tools.research_schema import (
    Evidence,
    ResearchResult,
    deduplicate_evidence,
    new_claim_id,
    new_evidence_id,
    new_query_id,
    now_iso,
    research_result_to_dict,
)

logger = logging.getLogger(__name__)


def deep_research(
    query: str,
    focus: str = "",
    cancellation_fence=None,
    run_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> dict:
    """Multi-agent deep research. Returns synthesized report with citations.

    run_id/step_id are optional and purely additive (no existing caller
    passes them today) — when present, per-evidence Artifact rows are
    written best-effort via research_evidence.write_evidence_artifact.
    """
    import asyncio
    full_query = f"{query}. Focus specifically on: {focus}" if focus else query
    if cancellation_fence is not None and getattr(cancellation_fence, "is_set", lambda: False)():
        return {"query": full_query, "report": "", "sources": [], "error": "cancelled"}
    try:
        result = asyncio.run(_run_open_deep_research(full_query, cancellation_fence=cancellation_fence, run_id=run_id, step_id=step_id))
        return result
    except RuntimeError:
        # Already inside an event loop (FastAPI context) — use thread
        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(asyncio.run, _run_open_deep_research(full_query, cancellation_fence=cancellation_fence, run_id=run_id, step_id=step_id))
        try:
            return future.result(timeout=300)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {"query": full_query, "report": "", "sources": [], "error": "deep_research_timeout"}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


# Synthesis runs against planner_model_base_url (OpenRouter); use an OpenRouter model.
_OPENROUTER_MODELS = [settings.or_highoutput_model]
_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash-8b"]


async def _try_odr_model(
    deep_researcher, SearchAPI, HumanMessage, AIMessage, model_spec: str, config_extra: dict, query: str,
    run_id: Optional[str] = None, step_id: Optional[str] = None,
) -> dict | None:
    """Run open_deep_research with a single model. Returns result dict or None on failure."""
    config = {
        "configurable": {
            "search_api": SearchAPI.NONE,
            "research_model": model_spec,
            "summarization_model": model_spec,
            "compression_model": model_spec,
            "final_report_model": model_spec,
            "allow_clarification": False,
            "max_concurrent_research_units": 3,
            **config_extra,
        }
    }
    result = await deep_researcher.ainvoke({"messages": [HumanMessage(content=query)]}, config=config)
    messages = result.get("messages", [])
    report_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            report_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
    import re as _re
    sources, seen_urls = [], set()
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else ""
        for url in _re.findall(r'https?://[^\s\)\"\']+', content):
            if url not in seen_urls:
                seen_urls.add(url)
                sources.append({"title": "", "url": url})
    return _build_odr_result(query, f"open_deep_research:{model_spec}", report_text, sources, run_id=run_id, step_id=step_id)


def _build_odr_result(
    query: str, model_label: str, report_text: str, sources: list,
    run_id: Optional[str] = None, step_id: Optional[str] = None,
) -> dict:
    """Shared tail for every open_deep_research / custom-fallback code path:
    attaches the legacy blob fields existing callers already read (report,
    sources, source_count, model, formatted) AND the new canonical
    ResearchResult under "structured" (see research_schema.py)."""
    query_id = new_query_id(query)
    structured = _extract_claims_from_report(query_id, query, report_text, sources, run_id=run_id, step_id=step_id)
    return {
        "query": query,
        "report": report_text,
        "sources": sources[:30],
        "source_count": len(sources),
        "model": model_label,
        "formatted": _format_deep_report(query, report_text, sources),
        "structured": research_result_to_dict(structured),
    }


def _is_cancelled(cancellation_fence) -> bool:
    return cancellation_fence is not None and getattr(cancellation_fence, "is_set", lambda: False)()


async def _run_open_deep_research(
    query: str, cancellation_fence=None, run_id: Optional[str] = None, step_id: Optional[str] = None,
) -> dict:
    """Try gpt-oss-120b first, then Gemini models, then custom synthesis."""
    from backend.config import settings

    if _is_cancelled(cancellation_fence):
        return {"query": query, "report": "", "sources": [], "error": "cancelled"}

    try:
        from open_deep_research.deep_researcher import deep_researcher
        from open_deep_research.configuration import SearchAPI
        from langchain_core.messages import HumanMessage, AIMessage
    except ImportError as e:
        logger.error("open_deep_research not installed: %s", e)
        return await _custom_deep_research(query, cancellation_fence=cancellation_fence, run_id=run_id, step_id=step_id)

    last_err = None

    # --- Pass 1: OpenRouter high-output model ---
    provider_config = {key: value for key, value in {"openai_api_key": settings.planner_model_api_key, "openai_base_url": settings.planner_model_base_url}.items() if value}
    for model_name in _OPENROUTER_MODELS:
        if _is_cancelled(cancellation_fence):
            return {"query": query, "report": "", "sources": [], "error": "cancelled"}
        try:
            res = await _try_odr_model(deep_researcher, SearchAPI, HumanMessage, AIMessage,
                                       f"openai:{model_name}", provider_config, query,
                                       run_id=run_id, step_id=step_id)
            if res:
                logger.info("deep_research succeeded with OpenRouter %s", model_name)
                return res
        except Exception as e:
            last_err = e
            logger.warning("OpenRouter %s failed: %s", model_name, e)

    # --- Pass 2: Gemini models ---
    for model_name in _GEMINI_MODELS:
        if _is_cancelled(cancellation_fence):
            return {"query": query, "report": "", "sources": [], "error": "cancelled"}
        research_model = f"google_genai:{model_name}"
        config_extra = {"google_api_key": settings.gemini_api_key} if settings.gemini_api_key else {}
        try:
            res = await _try_odr_model(deep_researcher, SearchAPI, HumanMessage, AIMessage,
                                       research_model, config_extra, query,
                                       run_id=run_id, step_id=step_id)
            if res:
                logger.info("open_deep_research succeeded with Gemini %s", model_name)
                return res
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "quota" in err_str or "rate" in err_str or "429" in err_str or "exhausted" in err_str:
                logger.warning("Gemini %s quota/rate error, trying next: %s", model_name, e)
                continue
            logger.error("open_deep_research (%s) failed: %s", model_name, e)
            break

    if _is_cancelled(cancellation_fence):
        return {"query": query, "report": "", "sources": [], "error": "cancelled"}

    logger.warning("All models failed (%s), falling back to custom synthesis", last_err)
    result = await _custom_deep_research(query, cancellation_fence=cancellation_fence, run_id=run_id, step_id=step_id)
    if last_err:
        result["model_error"] = str(last_err)
    return result


async def _custom_deep_research(
    query: str, cancellation_fence=None, run_id: Optional[str] = None, step_id: Optional[str] = None,
) -> dict:
    """
    Parallel multi-query search + LLM synthesis. Used when open_deep_research unavailable.
    Generates sub-queries, searches in parallel, reads pages, synthesizes with OpenRouter.
    """
    import asyncio
    from backend.config import settings

    if _is_cancelled(cancellation_fence):
        return {"query": query, "report": "", "sources": [], "error": "cancelled"}

    # Generate sub-queries covering different angles
    angles = [
        query,
        f"{query} market size statistics",
        f"{query} competitors alternatives",
        f"{query} trends 2024 2025",
        f"{query} use cases examples",
    ]

    # Parallel searches + page reads
    async def _search_angle(q: str) -> str:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: web_search(q, max_results=4))
        results = raw.get("results", [])
        snippets = [f"[{r['title']}] {r['snippet']}" for r in results if r.get("snippet")]
        return f"### {q}\n" + "\n".join(snippets[:4])

    # Launch angle searches one at a time (not asyncio.gather up front) so a
    # cancellation mid-loop stops us from kicking off further angles and lets
    # us return whatever partial evidence we already gathered instead of
    # crashing or blocking on the full batch.
    tasks = []
    for angle in angles:
        if _is_cancelled(cancellation_fence):
            break
        tasks.append(asyncio.create_task(_search_angle(angle)))
    sections = await asyncio.gather(*tasks) if tasks else []

    if _is_cancelled(cancellation_fence):
        partial = "\n\n".join(s for s in sections if s.strip())
        return {
            "query": query, "report": partial[:2000], "sources": [],
            "model": "custom:cancelled_partial", "error": "cancelled",
        }

    combined = "\n\n".join(s for s in sections if s.strip())

    if not combined.strip():
        return {"query": query, "report": "No research data found.", "sources": [], "model": "custom:no_data"}

    # Synthesize with OpenRouter planner model
    try:
        from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
        from backend.core.llm_client import get_or_client
        client = get_or_client(settings.planner_model_base_url, settings.planner_model_api_key)
        resp = client.chat.completions.create(
            model=settings.planner_model_name,
            messages=cacheable_messages([
                {"role": "system", "content": (
                    "You are a research analyst. Write a comprehensive research report covering: "
                    "market size/TAM, key players/competitors, trends, use cases, opportunities, risks. "
                    "Write in professional prose with clear sections. Be specific and cite data where visible."
                )},
                {"role": "user", "content": f"Query: {query}\n\nSEARCH DATA:\n{combined[:8000]}"},
            ], breakpoints=(0,)),  # cache stable system prompt
            temperature=0.2,
            max_tokens=2000,
            extra_body=openrouter_extra_body(settings.planner_model_name),
        )
        report = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""
    except Exception as e:
        logger.error("Custom synthesis LLM call failed: %s", e)
        report = combined[:4000]

    import re as _re
    sources = []
    seen: set = set()
    for section in sections:
        for url in _re.findall(r'https?://[^\s\)\"\']+', section):
            if url not in seen:
                seen.add(url)
                sources.append({"title": "", "url": url})

    return _build_odr_result(
        query, f"custom:multi_search+{settings.planner_model_name}", report, sources,
        run_id=run_id, step_id=step_id,
    )


def _fallback_research(query: str) -> dict:
    """Fall back to search_and_read when Gemini unavailable."""
    try:
        from backend.tools.page_fetcher import search_and_read as _sar
        result = _sar(query=query, max_results=5)
        result["model"] = "fallback:search_and_read"
        result["report"] = result.get("content", result.get("formatted", ""))
        result["sources"] = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in result.get("results", [])]
        return result
    except Exception as e:
        return {"query": query, "report": "", "sources": [], "error": f"Fallback also failed: {e}"}


_CLAIM_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')
_MIN_CLAIM_CHARS = 40


def _split_report_into_claims(report_text: str) -> list[str]:
    """Cheap heuristic splitter — NOT true claim extraction. Splits the
    report into paragraphs, strips markdown heading/bullet markers, then
    splits each paragraph into sentence-ish chunks and keeps only
    substantive-looking ones (>_MIN_CLAIM_CHARS). Real atomic-claim
    extraction would need an LLM pass; see the TODO in
    _extract_claims_from_report for why we don't fake that precision here.
    """
    if not report_text or not report_text.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', report_text) if p.strip()]
    claims: list[str] = []
    for para in paragraphs:
        para = re.sub(r'^#{1,6}\s*', '', para)
        para = re.sub(r'^[-*]\s+', '', para)
        for sentence in _CLAIM_SENTENCE_SPLIT_RE.split(para):
            sentence = sentence.strip()
            if len(sentence) > _MIN_CLAIM_CHARS:
                claims.append(sentence)
    return claims


def _extract_claims_from_report(
    query_id: str, question: str, report_text: str, sources: list,
    run_id: Optional[str] = None, step_id: Optional[str] = None,
) -> ResearchResult:
    """Convert an open_deep_research (or custom-fallback) report + flat
    source list into the canonical ResearchResult shape.

    HONEST LIMITATIONS (do not read past this as more precise than it is):
      - Evidence excerpts are empty strings. open_deep_research's report is a
        synthesized narrative; it does not give us a per-source quote/snippet
        to attach as `excerpt`. TODO: if ODR starts exposing per-source
        excerpts/published dates, wire them in here instead of "" / None.
      - Claim -> evidence attribution is report-level, not sentence-level.
        The report text isn't attributed per-sentence to a specific source,
        so we cannot say *which* source backs *which* claim — only that the
        report as a whole drew on all of `sources`. Every claim therefore
        inherits every evidence id. "100% of material claims have evidence
        ids" is true here by construction (inherit-all), not because each
        claim was individually verified against its specific source. Real
        claim-level attribution needs either ODR itself to expose it, or a
        separate LLM extraction pass that reads each claim against each
        source — that's future work, not faked here.
      - coverage_gaps is always [] — ODR doesn't expose unanswered
        sub-questions either. TODO: derive this once ODR (or an extraction
        pass) reports gaps.
    """
    retrieved_at = now_iso()
    evidence: list[Evidence] = []
    for src in sources or []:
        url = str((src or {}).get("url") or "").strip()
        if not url:
            continue
        title = str((src or {}).get("title") or "")
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            domain = ""
        evidence.append({
            "evidence_id": new_evidence_id(url, ""),
            "source_url": url,
            "title": title,
            "domain": domain,
            "published_at": None,  # ODR gives no per-source date today
            "retrieved_at": retrieved_at,
            "excerpt": "",  # ODR gives no per-claim/per-source excerpt today — see docstring
        })
    evidence = deduplicate_evidence(evidence)

    for ev in evidence:
        try:
            write_evidence_artifact(run_id, step_id, ev)
        except Exception:
            # write_evidence_artifact already swallows its own errors; this
            # is an extra belt-and-suspenders guard so a bug there can never
            # take down research itself.
            logger.debug("write_evidence_artifact raised unexpectedly", exc_info=True)

    all_evidence_ids = [e["evidence_id"] for e in evidence]

    claims: list = []
    for sentence in _split_report_into_claims(report_text):
        claim_id = new_claim_id(query_id, sentence)
        if all_evidence_ids:
            claims.append({
                "claim_id": claim_id,
                "text": sentence,
                "evidence_ids": list(all_evidence_ids),
                "confidence": 0.5,  # heuristic sentence split + inherited (not per-claim) attribution
                "contradicted": False,
                "contradiction_note": "",
            })
        else:
            # Guard against silently dropping claims that have zero matched
            # evidence — label them rather than drop them.
            claims.append({
                "claim_id": claim_id,
                "text": sentence,
                "evidence_ids": [],
                "confidence": 0.0,
                "contradicted": False,
                "contradiction_note": "unsupported: no evidence available",
            })

    return {
        "query_id": query_id,
        "question": question,
        "claims": claims,
        "evidence": evidence,
        "coverage_gaps": [],
        "escalation_decision": "escalated",
    }


def _format_deep_report(query: str, report: str, sources: list) -> str:
    lines = [f"# Deep Research: {query}\n", report, ""]
    if sources:
        lines.append(f"\n## Sources ({len(sources)})")
        for i, s in enumerate(sources[:15], 1):
            lines.append(f"{i}. [{s['title']}]({s['url']})" if s.get("title") else f"{i}. {s.get('url', '')}")
    return "\n".join(lines)


def _robust_text_search(query: str, max_results: int) -> list:
    """ddgs text search rotating reliable backends (auto/bing) with retries —
    the default/duckduckgo/google/brave backends often return 0 on this host."""
    import time as _t
    try:
        from ddgs import DDGS
    except Exception as exc:
        logger.warning("ddgs import failed for web search: %s", exc)
        return []
    for backend in ("auto", "bing"):
        for attempt in range(2):
            try:
                r = list(DDGS(timeout=12).text(query, max_results=max_results, backend=backend))
                if r:
                    return r
            except Exception as exc:
                logger.warning(
                    "ddgs text search failed for query=%r backend=%s attempt=%s: %s",
                    query, backend, attempt + 1, exc,
                )
            _t.sleep(0.3 * (attempt + 1))
    return []


def web_search(query: str, max_results: int = 8) -> dict:
    """Search the web. Returns {query, results: [{title, url, snippet}], formatted: str}."""
    try:
        raw = _robust_text_search(query, max_results)
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
        return {
            "query": query,
            "results": results,
            "formatted": _format_results(query, results),
        }
    except Exception as e:
        logger.error("web_search failed: %s", e)
        return {"query": query, "results": [], "error": str(e), "formatted": f"Search failed: {e}"}


def news_search(query: str, max_results: int = 5) -> dict:
    """Search recent news. Returns results with title, url, snippet, date."""
    try:
        import time as _t
        raw = []
        try:
            from ddgs import DDGS
            for backend in ("auto", "bing"):
                try:
                    raw = list(DDGS(timeout=12).news(query, max_results=max_results, backend=backend))
                    if raw:
                        break
                except Exception:
                    _t.sleep(0.3)
        except Exception:
            raw = []
        # Fall back to web text search if news returns nothing.
        if not raw:
            return web_search(query, max_results=max_results)
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("body", ""),
                "date": r.get("date", ""),
            }
            for r in raw
        ]
        return {
            "query": query,
            "results": results,
            "formatted": _format_results(query, results, show_date=True),
        }
    except Exception as e:
        logger.error("news_search failed: %s", e)
        return {"query": query, "results": [], "error": str(e), "formatted": f"Search failed: {e}"}


def search_and_read(query: str, max_results: int = 3) -> dict:
    """Search web + fetch full page content from top results. More thorough than web_search."""
    from backend.tools.page_fetcher import search_and_read as _sar
    return _sar(query=query, max_results=max_results)


def fetch_page(url: str) -> dict:
    """Fetch a URL, return clean text stripped of ads/nav/footer."""
    from backend.tools.page_fetcher import fetch_page as _fp
    return _fp(url=url)


def _format_results(query: str, results: list, show_date: bool = False) -> str:
    if not results:
        return f"No results for: {query}"
    lines = [f"Search: {query}\n"]
    for i, r in enumerate(results, 1):
        date = f" [{r['date']}]" if show_date and r.get("date") else ""
        lines.append(f"{i}. {r['title']}{date}")
        lines.append(f"   {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:200]}")
        lines.append("")
    return "\n".join(lines)

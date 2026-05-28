import logging
from typing import Optional

logger = logging.getLogger(__name__)


def deep_research(query: str, focus: str = "") -> dict:
    """
    Deep research using open_deep_research (LangChain/LangGraph multi-agent).
    Spawns parallel researcher agents with DuckDuckGo search, synthesizes a
    comprehensive report with citations.

    Args:
        query: Research question or topic
        focus: Optional focus area (e.g. "market sizing", "competitors")
    Returns:
        {query, report: str, sources: [{title, url}], model: str, error?}
    """
    import asyncio
    full_query = f"{query}. Focus specifically on: {focus}" if focus else query
    try:
        result = asyncio.run(_run_open_deep_research(full_query))
        return result
    except RuntimeError:
        # Already inside an event loop (FastAPI context) — use thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run_open_deep_research(full_query))
            return future.result(timeout=300)


_DEEPINFRA_MODELS = ["deepseek-ai/DeepSeek-V4-Flash"]
_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash-8b"]


async def _try_odr_model(deep_researcher, SearchAPI, HumanMessage, AIMessage, model_spec: str, config_extra: dict, query: str) -> dict | None:
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
    return {
        "query": query, "report": report_text,
        "sources": sources[:30], "source_count": len(sources),
        "model": f"open_deep_research:{model_spec}",
        "formatted": _format_deep_report(query, report_text, sources),
    }


async def _run_open_deep_research(query: str) -> dict:
    """Try gpt-oss-120b first, then Gemini models, then custom synthesis."""
    from backend.config import settings
    import os

    try:
        from open_deep_research.deep_researcher import deep_researcher
        from open_deep_research.configuration import SearchAPI
        from langchain_core.messages import HumanMessage, AIMessage
    except ImportError as e:
        logger.error("open_deep_research not installed: %s", e)
        return await _custom_deep_research(query)

    last_err = None

    # --- Pass 1: DeepInfra gpt-oss-120b ---
    _saved_oai = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL")}
    try:
        if settings.planner_model_api_key:
            os.environ["OPENAI_API_KEY"] = settings.planner_model_api_key
        if settings.planner_model_base_url:
            os.environ["OPENAI_BASE_URL"] = settings.planner_model_base_url
        for model_name in _DEEPINFRA_MODELS:
            try:
                res = await _try_odr_model(deep_researcher, SearchAPI, HumanMessage, AIMessage,
                                           f"openai:{model_name}", {}, query)
                if res:
                    logger.info("deep_research succeeded with DeepInfra %s", model_name)
                    return res
            except Exception as e:
                last_err = e
                logger.warning("DeepInfra %s failed: %s", model_name, e)
    finally:
        for k, v in _saved_oai.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    # --- Pass 2: Gemini models ---
    _saved_goog = os.environ.get("GOOGLE_API_KEY")
    if settings.gemini_api_key:
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
    try:
        for model_name in _GEMINI_MODELS:
            research_model = f"google_genai:{model_name}"
            config = {
                "configurable": {
                    "search_api": SearchAPI.NONE,
                    "research_model": research_model,
                    "summarization_model": research_model,
                    "compression_model": research_model,
                    "final_report_model": research_model,
                    "allow_clarification": False,
                    "max_concurrent_research_units": 3,
                }
            }
            try:
                result = await deep_researcher.ainvoke(
                    {"messages": [HumanMessage(content=query)]},
                    config=config,
                )
                # Success — extract report
                messages = result.get("messages", [])
                report_text = ""
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        report_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                        break
                sources = []
                seen_urls: set = set()
                import re as _re
                for msg in messages:
                    content = msg.content if isinstance(msg.content, str) else ""
                    for url in _re.findall(r'https?://[^\s\)\"\']+', content):
                        if url not in seen_urls:
                            seen_urls.add(url)
                            sources.append({"title": "", "url": url})
                logger.info("open_deep_research (%s): %d chars, %d sources", model_name, len(report_text), len(sources))
                return {
                    "query": query,
                    "report": report_text,
                    "sources": sources[:30],
                    "source_count": len(sources),
                    "model": f"open_deep_research:{model_name}",
                    "formatted": _format_deep_report(query, report_text, sources),
                }
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if "quota" in err_str or "rate" in err_str or "429" in err_str or "exhausted" in err_str:
                    logger.warning("Gemini %s quota/rate error, trying next: %s", model_name, e)
                    continue
                logger.error("open_deep_research (%s) failed: %s", model_name, e)
                break
    finally:
        if _saved_goog is None:
            os.environ.pop("GOOGLE_API_KEY", None)
        else:
            os.environ["GOOGLE_API_KEY"] = _saved_goog

    logger.warning("All models failed (%s), falling back to custom synthesis", last_err)
    result = await _custom_deep_research(query)
    if last_err:
        result["model_error"] = str(last_err)
    return result


async def _custom_deep_research(query: str) -> dict:
    """
    Parallel multi-query search + LLM synthesis. Used when open_deep_research unavailable.
    Generates sub-queries, searches in parallel, reads pages, synthesizes with DeepInfra.
    """
    import asyncio
    from backend.config import settings

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

    sections = await asyncio.gather(*[_search_angle(a) for a in angles])
    combined = "\n\n".join(s for s in sections if s.strip())

    if not combined.strip():
        return {"query": query, "report": "No research data found.", "sources": [], "model": "custom:no_data"}

    # Synthesize with DeepInfra planner model
    try:
        import openai as _openai
        client = _openai.OpenAI(
            base_url=settings.planner_model_base_url,
            api_key=settings.planner_model_api_key,
        )
        prompt = (
            f"You are a research analyst. Based on the search data below, write a comprehensive research report "
            f"on: {query}\n\n"
            f"Cover: market size/TAM, key players/competitors, trends, use cases, opportunities, risks.\n"
            f"Write in professional prose with clear sections. Be specific and cite data where visible.\n\n"
            f"SEARCH DATA:\n{combined[:8000]}"
        )
        resp = client.chat.completions.create(
            model=settings.planner_model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
        )
        report = resp.choices[0].message.content or ""
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

    return {
        "query": query,
        "report": report,
        "sources": sources[:20],
        "source_count": len(sources),
        "model": f"custom:multi_search+{settings.planner_model_name}",
        "formatted": _format_deep_report(query, report, sources),
    }


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


def _format_deep_report(query: str, report: str, sources: list) -> str:
    lines = [f"# Deep Research: {query}\n", report, ""]
    if sources:
        lines.append(f"\n## Sources ({len(sources)})")
        for i, s in enumerate(sources[:15], 1):
            lines.append(f"{i}. [{s['title']}]({s['url']})" if s.get("title") else f"{i}. {s.get('url', '')}")
    return "\n".join(lines)


def web_search(query: str, max_results: int = 8) -> dict:
    """Search the web. Returns {query, results: [{title, url, snippet}], formatted: str}."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
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
    """Search recent news. Returns {query, results: [{title, url, snippet, date}], formatted: str}."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.news(query, max_results=max_results))
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
    """Search the web AND fetch + read actual page content from top results. Deeper than web_search."""
    from backend.tools.page_fetcher import search_and_read as _sar
    return _sar(query=query, max_results=max_results)


def fetch_page(url: str) -> dict:
    """Fetch and read a specific URL. Returns clean readable text content, stripped of ads/nav/footer."""
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

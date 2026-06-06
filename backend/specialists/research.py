"""Research specialist — autonomous browser-powered research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import (
    search_and_fetch,
    fetch_and_read,
    research_papers,
    batch_search,
    build_research_queries,
    run_research_pipeline,
)
from backend.tools.patent_search import patent_search
from backend.tools.web_search import news_search
from backend.tools.video_research import youtube_research, tiktok_research


def _make_auto_logging_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "research"):
    """Wrap a research tool so every result is auto-logged to Obsidian."""
    @functools.wraps(tool_fn)
    def wrapper(*args, **kwargs):
        result = tool_fn(*args, **kwargs)
        ctx: AgentContext | None = ctx_holder[0] if ctx_holder else None
        if ctx is None:
            return result

        # Build heading from args
        heading = args[0] if args else kwargs.get("query") or kwargs.get("url") or tool_name

        # Build content summary
        if isinstance(result, list):
            lines = []
            for item in result:
                if isinstance(item, dict):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    text = item.get("content") or item.get("text") or item.get("snippet") or ""
                    lines.append(f"**[{title}]({url})**\n{text[:1500]}")
            content = "\n\n".join(lines) if lines else str(result)[:2000]
        elif isinstance(result, dict):
            # search_and_fetch returns {query, results, formatted}
            if "formatted" in result:
                content = result["formatted"][:3000]
            elif "results" in result:
                lines = []
                for r in result["results"]:
                    url = r.get("url", "")
                    title = r.get("title", "")
                    text = r.get("content") or r.get("snippet") or ""
                    lines.append(f"**[{title}]({url})**\n{text[:1500]}")
                content = "\n\n".join(lines) if lines else str(result)[:3000]
            else:
                content = str(result)[:3000]
        else:
            content = str(result)[:2000]

        try:
            obsidian_append(
                agent=agent_name,
                session_id=ctx.session_id,
                heading=str(heading)[:120],
                content=content,
                founder_id=ctx.founder_id,
            )
        except Exception:
            pass

        return result

    return wrapper


_FOCUS_ROLES = {
    "research": (
        "MARKET INTELLIGENCE:\n"
        "1. Call run_research_pipeline(topic='{topic}', focus='market') for the core evidence package.\n"
        "   Then call build_research_queries(topic='{topic}', focus='market') and run 2-4 batch_search rounds using those queries.\n"
        "   The query plan covers: market size/TAM, CAGR/growth forecasts, "
        "customer segments/ICP, pricing benchmarks, regulation, funding/news, and analyst reports.\n"
        "2. Run news_search for latest 2025/2026 developments.\n"
        "3. Run research_papers when academic/user-behavior evidence is relevant.\n"
        "4. fetch_and_read the 8-15 highest-value URLs from the searches, prioritizing primary/analyst/competitor sources.\n\n"
        "obsidian_log with: MARKET SIZE, GROWTH RATE, TAM/SAM/SOM, KEY SEGMENTS, REGULATORY, VC FUNDING DATA, and SOURCES."
    ),
    "research_competitors": (
        "COMPETITOR INTELLIGENCE (named companies, pricing, features, weaknesses — NOT market size or financial benchmarks):\n"
        "1. Call run_research_pipeline(topic='{topic}', focus='competitors') for the core evidence package.\n"
        "   Then call build_research_queries(topic='{topic}', focus='competitors') and run 2-4 batch_search rounds using those queries.\n"
        "   The query plan covers: named competitors, G2/Capterra/ProductHunt alternatives, "
        "Crunchbase/funding, pricing pages, reviews/complaints, YC/a16z/VC-backed startups, and market maps.\n"
        "2. Extract at least 8 named competitors. Run additional targeted batch_search rounds with narrower terms until you have 8+.\n"
        "3. fetch_and_read homepage/pricing pages for 8-12 competitors.\n"
        "4. Run patent_search and youtube_research when product demos/reviews matter.\n\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses, market position), WHITESPACE OPPORTUNITIES, and SOURCES."
    ),
}


def build_research_agent(agent_name: str = "research", **kwargs) -> Agent:
    # ctx_holder: mutable so wrappers can see the live AgentContext
    ctx_holder: list = [None]

    # _2/_3/_4 variants log to same Obsidian note as base so notes merge
    import re as _re
    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_batch = _make_auto_logging_tool(batch_search, "batch_search", ctx_holder, log_name)
    auto_query_plan = _make_auto_logging_tool(build_research_queries, "build_research_queries", ctx_holder, log_name)
    auto_pipeline = _make_auto_logging_tool(run_research_pipeline, "run_research_pipeline", ctx_holder, log_name)
    auto_papers = _make_auto_logging_tool(research_papers, "research_papers", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder, log_name)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder, log_name)
    auto_youtube = _make_auto_logging_tool(youtube_research, "youtube_research", ctx_holder, log_name)
    auto_tiktok = _make_auto_logging_tool(tiktok_research, "tiktok_research", ctx_holder, log_name)


    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    focus_searches = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])
    model = kwargs.pop("model", settings.or_light_model)
    model_base_url = kwargs.pop("model_base_url", settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", get_openrouter_key() or settings.agent_model_api_key)
    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=40,
        role=(
            "You are an elite deep research specialist. Your ONLY domain is MARKET OPPORTUNITY — "
            "TAM/SAM/SOM, market growth trends, timing thesis, and investment narrative. "
            "NOT competitor profiling (research_competitors), NOT financial benchmarks (research_financial), "
            "NOT regulatory risk (research_regulatory), NOT customer personas (customer_discovery).\n\n"
            "Be THOROUGH: visit many sources across the web. Run multiple search rounds and read "
            "8-15 high-value pages before synthesizing. Breadth and primary-source depth matter more than speed.\n\n"
            "TOOLS:\n"
            "- run_research_pipeline(topic, focus) — complete first-pass research: query plan + parallel searches + deduped sources. Use this first.\n"
            "- build_research_queries(topic, focus) — creates a high-coverage query plan. Use this before batch_search.\n"
            "- batch_search(queries, max_results_each=6) — runs multiple searches in parallel. PRIMARY tool; use this first.\n"
            "- search_and_fetch(query) — single targeted search + page fetch. Use only for follow-up gaps.\n"
            "- fetch_and_read(url) — read a specific URL in full depth.\n"
            "- research_papers(query) — academic papers.\n"
            "- news_search(query) — recent news.\n"
            "- patent_search(query) — IP landscape.\n"
            "- youtube_research(query) — YouTube video metadata + transcripts for competitor/creator analysis.\n"
            "- tiktok_research(query) — TikTok video metadata + captions for viral trend analysis.\n"
            "- obsidian_log — FINAL step only after ALL searches complete.\n\n"
            "RESEARCH QUALITY RULES:\n"
            "- Generate specific, source-seeking queries. Avoid vague searches like just the product category.\n"
            "- Prefer primary sources, analyst reports, competitor pages, government/public datasets, and reputable review sites.\n"
            "- Check run_research_pipeline.coverage. If coverage.ready is false, fill gaps with one targeted batch_search or clearly mark uncertainty.\n"
            "- Always name concrete companies, numbers, dates, and URLs. If evidence is weak, say so.\n"
            "- Search broadly: run run_research_pipeline, THEN 2-4 additional batch_search rounds to fill gaps and "
            "go deeper on specifics. fetch_and_read 8-15 of the best URLs. Aim for 15+ distinct sources before you finish.\n\n"
            "YOUR SEARCH PLAN (replace {topic} with the actual subject):\n\n"
            + focus_searches
        ),
        tools={
            "run_research_pipeline": auto_pipeline,
            "build_research_queries": auto_query_plan,
            "search_and_fetch": auto_search,
            "batch_search": auto_batch,
            "fetch_and_read": auto_fetch,
            "research_papers": auto_papers,
            "news_search": auto_news,
            "patent_search": auto_patent,
            "youtube_research": auto_youtube,
            "tiktok_research": auto_tiktok,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )

    # Patch run to inject ctx into ctx_holder before each run
    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

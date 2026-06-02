"""Research specialist — autonomous browser-powered research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read, research_papers
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
        "MARKET INTELLIGENCE (run ALL 8):\n"
        "1. search_and_fetch('{topic} market size TAM SAR revenue 2024 2025 statistics')\n"
        "2. search_and_fetch('{topic} industry growth rate forecast CAGR report')\n"
        "3. search_and_fetch('{topic} venture capital funding rounds 2024 2025')\n"
        "4. search_and_fetch('{topic} market trends emerging technology adoption')\n"
        "5. search_and_fetch('{topic} customer demographics segments target audience')\n"
        "6. search_and_fetch('{topic} regulatory environment compliance requirements')\n"
        "7. news_search('{topic} 2025 2026 latest')\n"
        "8. research_papers('{topic} academic study user behavior market')\n\n"
        "Then 8+ fetch_and_read calls on the most valuable URLs found.\n"
        "obsidian_log with: MARKET SIZE, GROWTH RATE, TAM/SAM/SOM, KEY SEGMENTS, REGULATORY, VC FUNDING DATA."
    ),
    "research_competitors": (
        "COMPETITOR INTELLIGENCE (run ALL 15):\n"
        "1. search_and_fetch('{topic} top companies platforms list 2024 2025')\n"
        "2. search_and_fetch('{topic} startups to watch named companies founded 2020 2021 2022 2023 2024')\n"
        "3. search_and_fetch('{topic} crunchbase funding raised valuation startup')\n"
        "4. search_and_fetch('{topic} Y Combinator a16z sequoia backed startup company')\n"
        "5. search_and_fetch('{topic} alternatives competitors site:g2.com OR site:capterra.com OR site:producthunt.com')\n"
        "6. search_and_fetch('{topic} best platform tool ranked review techcrunch venturebeat')\n"
        "7. search_and_fetch('{topic} pricing model subscription freemium enterprise')\n"
        "8. search_and_fetch('{topic} customer reviews complaints reddit forum')\n"
        "9. search_and_fetch('{topic} product features comparison strengths weaknesses')\n"
        "10. search_and_fetch('{topic} market map landscape 2024 2025')\n"
        "11. news_search('{topic} company startup launch 2024 2025')\n"
        "12. patent_search('{topic}')\n"
        "13. youtube_research('{topic} platform demo review walkthrough')\n"
        "14. tiktok_research('{topic} review product')\n\n"
        "CRITICAL: After step 1-6, you MUST have a list of specific named companies/platforms. "
        "If you haven't found at least 5 named competitors, run additional searches with more specific terms. "
        "Then for EACH named competitor found: fetch_and_read(competitor_homepage_url) and fetch_and_read(competitor_pricing_url).\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses, market position), WHITESPACE OPPORTUNITIES, VIDEO INSIGHTS."
    ),
    "research_execution": (
        "EXECUTION STRATEGY RESEARCH (run ALL 10):\n"
        "1. search_and_fetch('how to build {topic} startup go-to-market strategy')\n"
        "2. search_and_fetch('{topic} business model revenue streams monetization')\n"
        "3. search_and_fetch('{topic} tech stack architecture how it works implementation')\n"
        "4. search_and_fetch('{topic} sales strategy B2B B2C customer acquisition cost')\n"
        "5. search_and_fetch('{topic} unit economics LTV CAC payback period')\n"
        "6. search_and_fetch('{topic} founder story how they built it lessons learned')\n"
        "7. search_and_fetch('{topic} user pain points problems complaints needs')\n"
        "8. search_and_fetch('{topic} customer success stories case studies ROI')\n"
        "9. youtube_research('{topic} startup founder how to build tutorial')\n"
        "10. tiktok_research('{topic} startup tips growth hacks')\n\n"
        "Then 8+ fetch_and_read calls on the most actionable URLs found.\n"
        "obsidian_log with: RECOMMENDED TECH STACK, GTM STRATEGY, PRICING MODEL, FIRST 90 DAYS PLAN, USER PERSONAS, KEY RISKS, VIDEO CREATOR INSIGHTS."
    ),
}


def build_research_agent(agent_name: str = "research", **kwargs) -> Agent:
    # Strip model overrides — research always uses planner model
    for k in ("model", "model_base_url", "model_api_key"):
        kwargs.pop(k, None)

    # ctx_holder: mutable so wrappers can see the live AgentContext
    ctx_holder: list = [None]

    # _2/_3/_4 variants log to same Obsidian note as base so notes merge
    import re as _re
    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_papers = _make_auto_logging_tool(research_papers, "research_papers", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder, log_name)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder, log_name)
    auto_youtube = _make_auto_logging_tool(youtube_research, "youtube_research", ctx_holder, log_name)
    auto_tiktok = _make_auto_logging_tool(tiktok_research, "tiktok_research", ctx_holder, log_name)


    from backend.config import settings
    focus_searches = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])
    agent = Agent(
        name=agent_name,
        model=settings.planner_model_name,
        model_base_url=settings.planner_model_base_url,
        model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        max_iterations=40,
        role=(
            "You are an elite deep research specialist. You produce investment-grade research. "
            "Prioritize speed + quality: complete core coverage fast, then stop once evidence is sufficient.\n\n"
            "TOOLS:\n"
            "- search_and_fetch(query) — searches + fetches full content from multiple sites. PRIMARY tool.\n"
            "- fetch_and_read(url) — read a specific URL in full depth.\n"
            "- research_papers(query) — academic papers.\n"
            "- news_search(query) — recent news.\n"
            "- patent_search(query) — IP landscape.\n"
            "- youtube_research(query) — YouTube video metadata + transcripts for competitor/creator analysis.\n"
            "- tiktok_research(query) — TikTok video metadata + captions for viral trend analysis.\n"
            "- obsidian_log — FINAL step only after ALL searches complete.\n\n"
            "YOUR MANDATORY SEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + focus_searches
        ),
        tools={
            "search_and_fetch": auto_search,
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

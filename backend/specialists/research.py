"""Research specialist — autonomous browser-powered research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read, research_papers, batch_search
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
        "STEP 1 — Run ONE batch_search with ALL these queries simultaneously:\n"
        "batch_search(queries=[\n"
        "  '{topic} market size TAM revenue 2024 2025 statistics',\n"
        "  '{topic} industry growth rate forecast CAGR report',\n"
        "  '{topic} venture capital funding rounds 2024 2025',\n"
        "  '{topic} customer demographics segments target audience',\n"
        "  '{topic} regulatory environment compliance requirements',\n"
        "  '{topic} market trends emerging technology adoption'\n"
        "])\n"
        "STEP 2 — news_search('{topic} 2025 2026 latest')\n"
        "STEP 3 — research_papers('{topic} academic study user behavior market')\n"
        "STEP 4 — 6+ fetch_and_read calls on the most valuable URLs found.\n\n"
        "SELF-EVALUATION (run before obsidian_log):\n"
        "Check if you have ALL of these. For each missing item, run 2 more targeted searches before logging:\n"
        "[ ] TAM number with source (e.g. '$4.2B market, Source: Grand View Research 2024')\n"
        "[ ] CAGR / growth rate with source\n"
        "[ ] At least 3 named VC-backed companies or funded startups in this space\n"
        "[ ] Target customer segment with specific pain point\n"
        "[ ] Regulatory or compliance note\n"
        "If any box is unchecked, search for it specifically before logging.\n\n"
        "obsidian_log with: MARKET SIZE, GROWTH RATE, TAM/SAM/SOM, KEY SEGMENTS, REGULATORY, VC FUNDING DATA."
    ),
    "research_competitors": (
        "COMPETITOR INTELLIGENCE — find REAL named companies in this specific market.\n\n"
        "STEP 0 — TOPIC EXTRACTION (do this first, before any search):\n"
        "Read your task instruction. Extract a SPECIFIC topic like 'AI stock trading signals retail investors' or "
        "'transparent equity prediction platform'. NEVER use generic terms like 'AI', 'fintech', 'platform' alone.\n\n"
        "STEP 1 — Run ONE batch_search with ALL these queries simultaneously:\n"
        "batch_search(queries=[\n"
        "  '{topic} top companies platforms named list 2024 2025',\n"
        "  '{topic} startups named companies crunchbase funding 2022 2023 2024',\n"
        "  '{topic} alternatives site:g2.com OR site:capterra.com OR site:producthunt.com',\n"
        "  '{topic} best ranked review techcrunch venturebeat',\n"
        "  '{topic} Y Combinator a16z sequoia backed named startup',\n"
        "  '{topic} pricing model subscription plans cost per month',\n"
        "  '{topic} market map landscape named players 2024 2025'\n"
        "])\n"
        "STEP 2 — news_search('{topic} company startup funding launch 2024 2025')\n"
        "STEP 3 — patent_search('{topic}')\n"
        "STEP 4 — youtube_research('{topic} platform demo review walkthrough')\n\n"
        "STEP 2 — DEEP DIVE ON NAMED COMPETITORS:\n"
        "After steps 1-10 you MUST have at least 5 specific named companies (e.g. Trade Ideas, TrendSpider, Tickeron). "
        "If you have fewer than 5, run MORE searches with different terms before continuing. "
        "For EACH named competitor: fetch_and_read(their homepage URL) then fetch_and_read(their /pricing URL).\n\n"
        "SELF-EVALUATION (run before obsidian_log):\n"
        "Check if you have ALL of these. For each missing item, run 2 more targeted searches:\n"
        "[ ] At least 5 named competitors with homepage URLs\n"
        "[ ] Pricing for at least 3 of them (specific dollar amounts)\n"
        "[ ] Funding amount for at least 2 of them\n"
        "[ ] At least 1 clear gap or weakness in the competitive landscape\n"
        "[ ] At least 1 YouTube or TikTok creator covering this space\n"
        "If any box is unchecked, search specifically for what's missing before logging.\n\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses, market position), "
        "WHITESPACE OPPORTUNITIES, VIDEO INSIGHTS, PRICING COMPARISON."
    ),
    "research_execution": (
        "EXECUTION STRATEGY RESEARCH — how to actually build and launch this specific product.\n\n"
        "STEP 0 — TOPIC EXTRACTION (do this first):\n"
        "Read your task instruction. Extract a SPECIFIC product/domain like 'AI trading signal SaaS retail investors'. "
        "NEVER use generic terms like 'AI', 'startup', 'platform' alone in queries.\n\n"
        "STEP 1 — Run ONE batch_search with ALL these queries simultaneously:\n"
        "batch_search(queries=[\n"
        "  'how to build {topic} startup go-to-market strategy',\n"
        "  '{topic} business model revenue streams monetization subscription',\n"
        "  '{topic} tech stack architecture engineering how it works',\n"
        "  '{topic} customer acquisition cost CAC LTV unit economics',\n"
        "  '{topic} user pain points reddit complaints what users want',\n"
        "  '{topic} regulatory legal compliance requirements'\n"
        "])\n"
        "STEP 2 — youtube_research('{topic} how to build launch tutorial founder')\n"
        "STEP 3 — 6+ fetch_and_read calls on the most actionable URLs found.\n\n"
        "SELF-EVALUATION (run before obsidian_log):\n"
        "Check if you have ALL of these. For each missing item, run 2 more targeted searches:\n"
        "[ ] Specific tech stack recommendation (not generic — name actual frameworks, DBs, APIs)\n"
        "[ ] CAC and LTV estimates with source\n"
        "[ ] At least 2 specific GTM channels with evidence they work for this space\n"
        "[ ] Named user persona with specific pain point and willingness to pay\n"
        "[ ] At least 1 regulatory or legal risk specific to this domain\n"
        "If any box is unchecked, search specifically for what's missing before logging.\n\n"
        "obsidian_log with: RECOMMENDED TECH STACK, GTM STRATEGY, PRICING MODEL, FIRST 90 DAYS PLAN, USER PERSONAS, KEY RISKS, REGULATORY NOTES, VIDEO CREATOR INSIGHTS."
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
    auto_batch = _make_auto_logging_tool(batch_search, "batch_search", ctx_holder, log_name)
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
            "CRITICAL — TOPIC EXTRACTION:\n"
            "Before any search, read your TASK INSTRUCTION carefully and extract a SPECIFIC SEARCH TOPIC.\n"
            "The topic must be specific: product category + target user + key differentiator.\n"
            "GOOD: 'AI stock trading signal platform retail investors' or 'transparent AI prediction engine equity markets'\n"
            "BAD: 'AI', 'technology', 'platform', 'startup', 'software' — these are too generic and FORBIDDEN as standalone queries.\n"
            "NEVER search Wikipedia. NEVER search for generic technology terms alone.\n"
            "Every query must include the specific domain from your task instruction.\n\n"
            "TOOLS:\n"
            "- batch_search(queries=[...]) — run 3-8 searches IN PARALLEL. USE THIS FIRST for speed.\n"
            "- search_and_fetch(query) — single search + fetch. Use for follow-up searches.\n"
            "- fetch_and_read(url) — read a specific URL in full depth.\n"
            "- research_papers(query) — academic papers.\n"
            "- news_search(query) — recent news.\n"
            "- patent_search(query) — IP landscape.\n"
            "- youtube_research(query) — YouTube video metadata + transcripts.\n"
            "- tiktok_research(query) — TikTok video metadata + captions.\n"
            "- obsidian_log — FINAL step only after ALL searches complete.\n\n"
            "SPEED REQUIREMENT: Start with ONE batch_search call containing 4-6 queries to run them all in parallel.\n"
            "Then use individual search_and_fetch for follow-ups. This cuts research time by 4x.\n\n"
            "YOUR MANDATORY SEARCH SEQUENCE (replace {topic} with your extracted SPECIFIC topic — never a generic word):\n\n"
            + focus_searches
        ),
        tools={
            "batch_search": auto_batch,
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

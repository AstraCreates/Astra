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
        "  'TOPIC market size TAM revenue 2024 2025 statistics',\n"
        "  'TOPIC industry growth rate forecast CAGR report',\n"
        "  'TOPIC venture capital funding rounds 2024 2025',\n"
        "  'TOPIC customer demographics segments target audience',\n"
        "  'TOPIC regulatory environment compliance requirements',\n"
        "  'TOPIC market trends emerging technology adoption'\n"
        "])\n"
        "STEP 2 — news_search('TOPIC 2025 2026 latest')\n"
        "STEP 3 — research_papers('TOPIC academic study user behavior market')\n"
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
        "STEP 1 — Run ONE batch_search replacing TOPIC with the FULL product phrase from your task (no abbreviations):\n"
        "batch_search(queries=[\n"
        "  'TOPIC top companies platforms named list 2024 2025',\n"
        "  'TOPIC startups named companies crunchbase funding 2022 2023 2024',\n"
        "  'TOPIC alternatives site:g2.com OR site:capterra.com OR site:producthunt.com',\n"
        "  'TOPIC best ranked review techcrunch venturebeat',\n"
        "  'TOPIC Y Combinator a16z sequoia backed named startup',\n"
        "  'TOPIC pricing model subscription plans cost per month',\n"
        "  'TOPIC market map landscape named players 2024 2025'\n"
        "])\n"
        "STEP 2 — news_search('TOPIC company startup funding launch 2024 2025')\n"
        "STEP 3 — patent_search('TOPIC')\n"
        "STEP 4 — youtube_research('TOPIC platform demo review walkthrough')\n\n"
        "STEP 5 — DEEP DIVE ON NAMED COMPETITORS:\n"
        "You MUST have at least 5 specific named companies. "
        "If you have fewer than 5, run MORE searches with different terms before continuing. "
        "For EACH named competitor: fetch_and_read(their homepage URL) then fetch_and_read(their /pricing URL).\n\n"
        "SELF-EVALUATION (run before obsidian_log):\n"
        "[ ] At least 5 named competitors with homepage URLs\n"
        "[ ] Pricing for at least 3 of them (specific dollar amounts)\n"
        "[ ] Funding amount for at least 2 of them\n"
        "[ ] At least 1 clear gap or weakness in the competitive landscape\n"
        "[ ] At least 1 YouTube or TikTok creator covering this space\n"
        "For each unchecked box, run 2 more targeted searches before logging.\n\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses, market position), "
        "WHITESPACE OPPORTUNITIES, VIDEO INSIGHTS, PRICING COMPARISON."
    ),
    "research_execution": (
        "EXECUTION STRATEGY RESEARCH — how to actually build and launch this specific product.\n\n"
        "STEP 1 — Run ONE batch_search replacing TOPIC with the FULL product phrase from your task (no abbreviations):\n"
        "batch_search(queries=[\n"
        "  'how to build TOPIC startup go-to-market strategy',\n"
        "  'TOPIC business model revenue streams monetization subscription',\n"
        "  'TOPIC tech stack architecture engineering how it works',\n"
        "  'TOPIC customer acquisition cost CAC LTV unit economics',\n"
        "  'TOPIC user pain points reddit complaints what users want',\n"
        "  'TOPIC regulatory legal compliance requirements'\n"
        "])\n"
        "STEP 2 — youtube_research('TOPIC how to build launch tutorial founder')\n"
        "STEP 3 — 6+ fetch_and_read calls on the most actionable URLs found.\n\n"
        "SELF-EVALUATION (run before obsidian_log):\n"
        "[ ] Specific tech stack recommendation (name actual frameworks, DBs, APIs)\n"
        "[ ] CAC and LTV estimates with source\n"
        "[ ] At least 2 specific GTM channels with evidence they work for this space\n"
        "[ ] Named user persona with specific pain point and willingness to pay\n"
        "[ ] At least 1 regulatory or legal risk specific to this domain\n"
        "For each unchecked box, run 2 more targeted searches before logging.\n\n"
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
        model="meta-llama/llama-3.3-70b-instruct",
        model_base_url=settings.openrouter_base_url,
        model_api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        max_iterations=40,
        role=(
            "You are an elite deep research specialist. You produce investment-grade research. "
            "Prioritize speed + quality: complete core coverage fast, then stop once evidence is sufficient.\n\n"
            "CRITICAL — SEARCH QUERY RULES:\n"
            "1. Copy the EXACT product/domain phrase from your TASK INSTRUCTION into every search query.\n"
            "   Use the full descriptive phrase — NEVER shorten, abbreviate, or use acronyms.\n"
            "   Example: task says 'co-founder matching platform' → search 'co-founder matching platform market size'\n"
            "   NEVER: 'CO matching' or 'co matching' or just 'matching platform'\n"
            "2. Your search queries MUST contain 4+ words describing the specific product/service.\n"
            "3. FORBIDDEN in queries: single words, abbreviations, acronyms, Wikipedia searches.\n"
            "4. If the task mentions a company name, include it in searches.\n\n"
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
            "YOUR MANDATORY SEARCH SEQUENCE — replace TOPIC with the FULL product/domain phrase from your task (4+ words, no abbreviations):\n\n"
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

    # Patch run to:
    # 1. Inject ctx into ctx_holder
    # 2. Replace TOPIC in the role prompt with the actual goal phrase so the
    #    LLM never has to guess — prevents "co-founder" → "CO" hallucinations
    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        # Extract a clean topic phrase from the goal (first 120 chars, strip newlines)
        raw_goal = (ctx.goal or "").replace("\n", " ").strip()
        topic_phrase = raw_goal[:120]
        # Replace TOPIC placeholder in the agent's role with the actual goal phrase
        if "TOPIC" in agent.role:
            agent.role = agent.role.replace("TOPIC", topic_phrase)
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

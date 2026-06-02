"""Research specialist — autonomous browser-powered research."""
import asyncio
import functools
import logging
import re as _re

logger = logging.getLogger(__name__)
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
                    lines.append(f"**[{title}]({url})**\n{text[:8000]}")
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
                    lines.append(f"**[{title}]({url})**\n{text[:8000]}")
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
    "research": {
        "goal": "MARKET INTELLIGENCE",
        "query_brief": (
            "Generate 30 search queries to research the market for: TOPIC\n"
            "Cover: market size/TAM, growth rate/CAGR, VC funding, customer segments, "
            "regulatory landscape, market trends, academic research, news, use cases, "
            "industry reports, demographics, pain points, geographic markets, adjacent markets."
        ),
        "instructions": (
            "STEP 1 — Run batch_search with the first 8 queries from your SEARCH_QUERIES list.\n"
            "STEP 2 — Run batch_search with queries 9-16.\n"
            "STEP 3 — Run batch_search with queries 17-24.\n"
            "STEP 4 — Run batch_search with queries 25-30 + news_search + research_papers.\n"
            "STEP 5 — fetch_and_read the 8 most valuable URLs found across all results.\n\n"
            "SELF-EVALUATION before obsidian_log:\n"
            "[ ] TAM number with source\n[ ] CAGR with source\n"
            "[ ] 3+ named VC-backed companies in this space\n"
            "[ ] Target customer segment with specific pain point\n"
            "[ ] Regulatory or compliance note\n"
            "For each unchecked box, run 2 more searches.\n\n"
            "obsidian_log: MARKET SIZE, GROWTH RATE, TAM/SAM/SOM, KEY SEGMENTS, REGULATORY, VC FUNDING."
        ),
    },
    "research_competitors": {
        "goal": "COMPETITOR INTELLIGENCE — find REAL named companies",
        "query_brief": (
            "Generate 30 search queries to find competitors for: TOPIC\n"
            "Cover: named companies list, crunchbase/funding, G2/Capterra/ProductHunt alternatives, "
            "YC/a16z/sequoia backed startups, pricing pages, market maps, reddit recommendations, "
            "techcrunch/venturebeat reviews, vs comparisons, feature comparisons, customer reviews, "
            "LinkedIn company searches, investor portfolios, patent holders, acquisition targets."
        ),
        "instructions": (
            "STEP 1 — Run batch_search with queries 1-8.\n"
            "STEP 2 — Run batch_search with queries 9-16.\n"
            "STEP 3 — Run batch_search with queries 17-24.\n"
            "STEP 4 — Run batch_search with queries 25-30 + patent_search + youtube_research.\n"
            "STEP 5 — For EACH named competitor found: fetch_and_read their homepage + /pricing page.\n"
            "         You MUST find at least 5 named companies. Run more searches if needed.\n\n"
            "SELF-EVALUATION before obsidian_log:\n"
            "[ ] 5+ named competitors with URLs\n[ ] Pricing for 3+ of them\n"
            "[ ] Funding for 2+ of them\n[ ] 1+ clear market gap\n[ ] 1+ video creator in this space\n"
            "For each unchecked box, run 2 more searches.\n\n"
            "obsidian_log: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses), "
            "WHITESPACE OPPORTUNITIES, VIDEO INSIGHTS, PRICING COMPARISON."
        ),
    },
    "research_execution": {
        "goal": "EXECUTION STRATEGY — how to build and launch this product",
        "query_brief": (
            "Generate 30 search queries for execution strategy for: TOPIC\n"
            "Cover: go-to-market strategy, tech stack choices, business model, revenue streams, "
            "CAC/LTV/unit economics, sales channels, user pain points (reddit/forums), "
            "founder interviews, YC advice, regulatory requirements, hiring plan, "
            "pricing strategy, growth hacks, customer success stories, build vs buy decisions."
        ),
        "instructions": (
            "STEP 1 — Run batch_search with queries 1-8.\n"
            "STEP 2 — Run batch_search with queries 9-16.\n"
            "STEP 3 — Run batch_search with queries 17-24.\n"
            "STEP 4 — Run batch_search with queries 25-30 + youtube_research.\n"
            "STEP 5 — fetch_and_read the 8 most actionable URLs.\n\n"
            "SELF-EVALUATION before obsidian_log:\n"
            "[ ] Specific tech stack (actual frameworks, DBs, APIs)\n"
            "[ ] CAC and LTV estimates with source\n"
            "[ ] 2+ GTM channels with evidence\n"
            "[ ] Named user persona with pain point and WTP\n"
            "[ ] 1+ regulatory risk specific to this domain\n"
            "For each unchecked box, run 2 more searches.\n\n"
            "obsidian_log: TECH STACK, GTM STRATEGY, PRICING MODEL, FIRST 90 DAYS, USER PERSONAS, KEY RISKS, REGULATORY."
        ),
    },
}


def build_research_agent(agent_name: str = "research", **kwargs) -> Agent:
    # Strip model overrides — research always uses planner model
    for k in ("model", "model_base_url", "model_api_key"):
        kwargs.pop(k, None)

    # ctx_holder: mutable so wrappers can see the live AgentContext
    ctx_holder: list = [None]

    # _2/_3/_4 variants log to same Obsidian note as base so notes merge
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
    focus_config = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])

    # Role prompt is built at run-time (after queries are generated), so use a placeholder
    agent = Agent(
        name=agent_name,
        model=settings.light_model_name,
        model_base_url=settings.light_model_base_url,
        model_api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        max_iterations=40,
        role="ROLE_PLACEHOLDER",  # replaced at runtime after query generation
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

    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx

        # Step 1: extract topic deterministically, build 30 queries from templates
        topic = await _extract_topic(ctx.goal or "")
        queries = _build_queries(topic, agent_name)

        # Step 2: pipeline search — generate 3 queries, start searching, generate next 3 simultaneously
        # Split into batches of 3 and run them as a pipeline with asyncio
        import json as _json
        search_results = await _pipeline_search(queries, batch_size=3)

        # Combine all search results into a pre-fetched context block
        combined = []
        for r in search_results:
            if isinstance(r, dict) and r.get("combined_formatted"):
                combined.append(r["combined_formatted"][:12000])
            elif isinstance(r, dict) and r.get("formatted"):
                combined.append(r["formatted"][:8000])
        pre_fetched = "\n\n---\n\n".join(combined)[:120000]

        agent.role = (
            f"You are an elite deep research specialist focused on: {focus_config['goal']}.\n"
            f"Topic: {topic}\n\n"
            f"SEARCH RESULTS (already fetched — do NOT re-run these searches):\n"
            f"{pre_fetched}\n\n"
            "YOUR JOB NOW:\n"
            "1. Read the search results above carefully.\n"
            "2. Call fetch_and_read on the 6-8 most valuable URLs found in the results above.\n"
            "3. Run news_search and research_papers for any gaps.\n"
            "4. Self-evaluate and run targeted follow-up searches for anything missing.\n"
            "5. Call obsidian_log with your complete findings.\n\n"
            "TOOLS: fetch_and_read, search_and_fetch, news_search, research_papers, "
            "patent_search, youtube_research, batch_search, obsidian_log.\n\n"
            f"{focus_config['instructions']}"
        )
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent


async def _pipeline_search(queries: list, batch_size: int = 3) -> list:
    """
    Pipeline: kick off searching each batch of `batch_size` queries as soon as
    the previous batch is in-flight — no waiting for results before starting next.
    Returns list of batch_search result dicts.
    """
    import asyncio
    batches = [queries[i:i+batch_size] for i in range(0, len(queries), batch_size)]
    tasks = [asyncio.create_task(_run_batch(b)) for b in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


async def _run_batch(queries: list) -> dict:
    import asyncio
    return await asyncio.to_thread(batch_search, queries, 6)


_MARKET_SUFFIXES = [
    "market size TAM revenue 2024 2025",
    "industry growth rate CAGR forecast",
    "venture capital funding rounds 2024",
    "customer demographics target audience",
    "regulatory compliance requirements",
    "market trends emerging 2025",
    "top investors backed startups",
    "total addressable market analysis",
    "user behavior survey research",
    "geographic market regions breakdown",
    "adjacent markets opportunities",
    "industry report grand view research",
    "market share leading companies",
    "demand drivers growth factors",
    "barriers to entry challenges",
    "B2B B2C customer segments",
    "pricing benchmarks industry average",
    "revenue model subscription freemium",
    "pain points user problems",
    "news funding launch 2025 2026",
    "academic study analysis",
    "competitive landscape overview",
    "technology adoption curve",
    "enterprise SMB customer split",
    "sales cycle length deal size",
    "unit economics LTV CAC payback",
    "churn retention benchmarks",
    "seasonal trends patterns",
    "international expansion markets",
    "regulation policy government impact",
]

_COMPETITOR_SUFFIXES = [
    "top companies named list 2024 2025",
    "startups crunchbase funding raised",
    "alternatives site:g2.com OR site:capterra.com",
    "best tools ranked site:producthunt.com",
    "Y Combinator backed startup named",
    "a16z sequoia funded company",
    "pricing plans subscription cost per month",
    "market map landscape named players",
    "vs comparison named competitors",
    "reviews reddit users recommend",
    "site:techcrunch.com funding announcement",
    "site:venturebeat.com startup",
    "customer complaints weaknesses",
    "feature comparison strengths",
    "free trial demo overview",
    "founder CEO interview story",
    "team size employees revenue",
    "latest news launch product update",
    "API integration partners",
    "acquisition merger exit",
    "patent holder IP owner",
    "enterprise SMB focus market",
    "NPS customer satisfaction score",
    "growth rate MRR ARR metrics",
    "channel distribution partnership",
    "white label reseller program",
    "open source alternative",
    "international global expansion",
    "Series A B C funding 2023 2024",
    "valuation unicorn decacorn",
]

_EXECUTION_SUFFIXES = [
    "go-to-market strategy how to launch",
    "business model revenue streams",
    "tech stack architecture engineering",
    "customer acquisition cost CAC LTV",
    "user pain points reddit forum complaints",
    "regulatory legal compliance requirements",
    "sales strategy B2C B2B channels",
    "founder interview lessons learned YC",
    "first 100 customers acquisition",
    "product market fit signals",
    "pricing strategy freemium tiered",
    "viral growth loop referral",
    "content marketing SEO strategy",
    "paid acquisition channels ROI",
    "hiring team roles first employees",
    "unit economics payback period",
    "churn reduction retention tactics",
    "onboarding activation best practices",
    "API integrations technical requirements",
    "database schema architecture choices",
    "frontend backend framework choice",
    "infrastructure scaling cloud provider",
    "security compliance GDPR SOC2",
    "partnership channel sales strategy",
    "investor pitch deck metrics",
    "fundraising timeline milestones",
    "competitive differentiation moat",
    "community building early adopters",
    "case study success story ROI",
    "youtube tutorial founder how to build",
]

_ROLE_SUFFIXES = {
    "research": _MARKET_SUFFIXES,
    "research_market": _MARKET_SUFFIXES,
    "research_financial": _MARKET_SUFFIXES,
    "research_regulatory": _MARKET_SUFFIXES,
    "research_competitors": _COMPETITOR_SUFFIXES,
    "research_execution": _EXECUTION_SUFFIXES,
}


def _build_queries(topic: str, agent_name: str) -> list:
    """Build 30 search queries deterministically — no LLM, no hallucination."""
    import re
    base = _re.sub(r"_\d+$", "", agent_name)
    suffixes = _ROLE_SUFFIXES.get(base, _MARKET_SUFFIXES)
    return [f"{topic} {s}" for s in suffixes]


async def _extract_topic(goal: str) -> str:
    """Extract the core product phrase using LLM — handles complex multi-sentence goals."""
    from backend.config import settings
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=settings.light_model_base_url,
            api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        )
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.light_model_name,
            messages=[{
                "role": "user",
                "content": (
                    "Extract the core product/domain phrase from this goal. "
                    "Output ONLY 3-7 words that describe what the product IS. "
                    "Rules: no verbs (build/create/make), write all words in full (never abbreviate), "
                    "no acronyms, describe the product not the action.\n"
                    "Examples:\n"
                    "Goal: 'Build a co-founder matching platform' → 'co-founder matching platform'\n"
                    "Goal: 'AI-predicted stock market signals for retail traders' → 'AI stock trading signal platform'\n"
                    "Goal: 'Restaurant inventory management with AI' → 'restaurant inventory management software'\n"
                    "Goal: 'B2B sales outreach automation tool' → 'B2B sales outreach automation'\n\n"
                    f"Goal: {goal[:500]}\n\nProduct phrase:"
                ),
            }],
            max_tokens=20,
            temperature=0.0,
        )
        phrase = resp.choices[0].message.content.strip().strip('"\'').strip()
        if phrase and 2 <= len(phrase.split()) <= 8:
            return phrase
    except Exception as e:
        logger.warning("_extract_topic LLM failed: %s", e)
    # Regex fallback for when LLM is unavailable
    import re
    goal = goal.replace("\n", " ").strip()
    cleaned = re.sub(r"^(build|create|make|develop|launch|start|design|implement|i want to|we want to|help me|i need)[:\s]+", "", goal, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+(with|that|for|using|which|where|featuring)\s+.*$", "", cleaned, flags=re.IGNORECASE).strip()
    return (cleaned[:60].rsplit(" ", 1)[0] if len(cleaned) > 60 else cleaned) or goal[:60]
    # Fallback: first 60 chars of goal, cleaned
    return goal.replace("\n", " ").strip()[:60]

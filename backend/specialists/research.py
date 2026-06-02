"""Research specialist — autonomous browser-powered research."""
import asyncio
import functools
import logging

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
    focus_config = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])

    # Role prompt is built at run-time (after queries are generated), so use a placeholder
    agent = Agent(
        name=agent_name,
        model=settings.planner_model_name,
        model_base_url=settings.planner_model_base_url,
        model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
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

        # Step 1: extract topic, then generate 30 queries for it
        topic = await _extract_topic(ctx.goal or "")
        queries = await _generate_queries(topic, focus_config["query_brief"])

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


def _sanitize_queries(queries: list, topic: str) -> list:
    """Remove abbreviations and ensure every query contains the topic phrase."""
    import re
    # Words from the topic that should never be abbreviated
    topic_words = set(topic.lower().split())
    clean = []
    for q in queries:
        q = str(q).strip()
        # Drop queries shorter than 4 words — too generic
        if len(q.split()) < 4:
            q = f"{topic} {q}"
        # Drop queries that don't contain ANY word from the topic (completely off-topic)
        q_lower = q.lower()
        if not any(w in q_lower for w in topic_words if len(w) > 3):
            q = f"{topic} {q}"
        # Replace isolated uppercase abbreviations (1-3 capital letters alone) that
        # aren't part of a longer word — e.g. "CO market size" → "{topic} market size"
        q = re.sub(r'\b[A-Z]{1,3}\b(?!\w)', topic, q)
        clean.append(q[:100])  # cap length
    return clean


async def _generate_queries(topic: str, query_brief: str) -> list:
    """Ask the LLM to generate 30 targeted search queries for the given topic and research angle."""
    import json
    from backend.config import settings
    brief = query_brief.replace("TOPIC", topic)
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=settings.planner_model_base_url,
            api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.planner_model_name,
            messages=[{
                "role": "user",
                "content": (
                    f"{brief}\n\n"
                    f"The topic phrase is: \"{topic}\"\n\n"
                    "STRICT RULES — violating any rule makes the query invalid:\n"
                    f"1. Every query MUST contain the words from \"{topic}\" written out IN FULL — never shorten, never abbreviate\n"
                    "2. NEVER use acronyms or initialisms (no CO, AI alone, SaaS alone, etc.) — write the full words\n"
                    "3. Each query must be 5-10 words\n"
                    "4. Each query targets a different angle (no repeats)\n"
                    "5. Include site: operators and year filters (2024, 2025) where useful\n\n"
                    "Output ONLY a JSON array of 30 query strings. No explanation, no markdown."
                ),
            }],
            max_tokens=1000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        queries = json.loads(raw)
        if isinstance(queries, list) and len(queries) >= 10:
            return _sanitize_queries([str(q) for q in queries[:30]], topic)
    except Exception as e:
        logger.warning("_generate_queries failed: %s", e)
    # Fallback: basic queries using topic
    return [
        f"{topic} market size 2024 2025",
        f"{topic} industry growth forecast",
        f"{topic} top companies list",
        f"{topic} funding rounds crunchbase",
        f"{topic} customer reviews reddit",
        f"{topic} pricing subscription cost",
        f"{topic} go-to-market strategy",
        f"{topic} tech stack architecture",
    ]


async def _extract_topic(goal: str) -> str:
    """Extract a 3-6 word search-friendly product phrase from the goal."""
    import asyncio
    from backend.config import settings
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=settings.planner_model_base_url,
            api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.planner_model_name,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the core product/domain phrase from this goal. "
                    f"Output ONLY 3-6 words that describe what the product IS — "
                    f"no verbs like 'build' or 'create', no adjectives like 'real-time'. "
                    f"Examples: 'co-founder matching platform', 'AI stock trading signals', "
                    f"'restaurant inventory management software', 'B2B sales automation tool'.\n\n"
                    f"Goal: {goal[:400]}\n\nProduct phrase:"
                ),
            }],
            max_tokens=20,
            temperature=0.0,
        )
        phrase = resp.choices[0].message.content.strip().strip('"\'').strip()
        if phrase and 3 <= len(phrase.split()) <= 8:
            return phrase
    except Exception:
        pass
    # Fallback: first 60 chars of goal, cleaned
    return goal.replace("\n", " ").strip()[:60]

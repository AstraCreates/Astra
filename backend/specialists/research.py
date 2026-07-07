"""Research specialist — autonomous browser-powered research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import (
    search_and_fetch,
    fetch_and_read,
    research_papers,
    batch_search,
    sonar_research,
    build_research_queries,
    run_research_pipeline,
)
from backend.tools.patent_search import patent_search
from backend.tools.web_search import news_search
from backend.tools.video_research import youtube_research, tiktok_research, youtube_get_transcript


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


_DONE_INSTRUCTIONS = (
    "\n\nDONE OUTPUT — plain text values only, no markdown stars, no bullet symbols, no emojis.\n"
    "After obsidian_log, call done with this exact JSON structure (fill every field from research + injected company context):\n"
    '{"action":"done","output":{'
    '"summary":"one paragraph synthesis of all findings",'
    '"market_size":"TAM/SAM/SOM with concrete numbers e.g. $12B TAM growing 18% CAGR",'
    '"icp":"who the ideal customer is, 1-2 sentences",'
    '"problem":"core pain point the company solves, 1-2 sentences",'
    '"solution":"what the product does, 1-2 sentences",'
    '"differentiator":"key competitive advantage over alternatives, 1 sentence",'
    '"moat":"defensibility or barriers to entry, 1 sentence",'
    '"revenue_model":"how the company makes money, 1 sentence",'
    '"go_to_market":"primary acquisition strategy and key channels, 1-2 sentences",'
    '"risks":"top 2-3 risks in 1-2 sentences",'
    '"tagline":"one-line value proposition",'
    '"mission":"company mission statement",'
    '"competitors":["CompanyA","CompanyB","CompanyC"],'
    '"sources":["url1","url2"]}}\n'
    "For identity fields (problem, solution, tagline, mission, revenue_model, differentiator, moat, icp): "
    "use injected company brain context as the source of truth, supplement with research.\n"
    "For market/competitor fields: use your research findings.\n"
    "Before done, pressure-test the idea hard: what is weak, crowded, unconvincing, or likely to fail? "
    "If the evidence points to a materially better wedge, ICP, pricing model, or product direction, call ask_user "
    "with a decision-grade question before done."
)

_DONE_COMPETITORS = (
    "\n\nDONE OUTPUT — plain text, no markdown.\n"
    '{"action":"done","output":{'
    '"competitors":["Company A","Company B","Company C","Company D","Company E","Company F","Company G","Company H"],'
    '"differentiator":"how this company differentiates from the listed competitors, 1 sentence",'
    '"summary":"competitive landscape synthesis",'
    '"sources":["url1","url2"]}}\n'
    "List at least 6 real named competitor companies."
)

_DONE_CUSTOMERS = (
    "\n\nDONE OUTPUT — plain text, no markdown.\n"
    '{"action":"done","output":{'
    '"icp":"ideal customer profile with demographics, job title, company size",'
    '"problem":"core pain point the customer experiences, 1-2 sentences",'
    '"summary":"customer intelligence synthesis",'
    '"sources":["url1","url2"]}}\n'
)

_DONE_GTM = (
    "\n\nDONE OUTPUT — plain text, no markdown.\n"
    '{"action":"done","output":{'
    '"go_to_market":"primary GTM strategy and key acquisition channels, 1-2 sentences",'
    '"revenue_model":"pricing model and monetization approach, 1 sentence",'
    '"summary":"GTM intelligence synthesis",'
    '"sources":["url1","url2"]}}\n'
)

_FOCUS_ROLES = {
    "research": (
        "COMPREHENSIVE RESEARCH — cover all 4 areas in sequence:\n\n"
        "1. MARKET (TAM/SAM/SOM, growth, regulation, funding): run_research_pipeline(focus='market') — sonar_research handles fetching internally, no separate URL fetching needed.\n"
        "2. COMPETITORS (named companies, pricing, features, weaknesses): run_research_pipeline(focus='competitors') then sonar_research(['<topic> top competitors pricing', '<topic> alternatives G2 reviews', ...]).\n"
        "3. CUSTOMERS (ICP, buyer pain, Reddit/reviews, WTP): build_research_queries(focus='customers') then sonar_research(queries). Add tiktok_research + youtube_research for sentiment.\n"
        "4. GTM (acquisition channels, CAC benchmarks, launch tactics): build_research_queries(focus='gtm') then sonar_research(queries) + news_search.\n\n"
        "Use fetch_and_read only for specific competitor pricing pages or paywalled reports sonar cannot reach.\n"
        "Do NOT run batch_search — sonar_research replaces it. Move through all 4 areas before logging.\n\n"
        "obsidian_log with ALL sections: MARKET SIZE, COMPETITOR TABLE, ICP PROFILE, PAIN POINTS, GTM CHANNELS, SOURCES."
        + _DONE_INSTRUCTIONS
    ),
    "research_competitors": (
        "COMPETITOR INTELLIGENCE (named companies, pricing, features, weaknesses):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. run_research_pipeline(topic='{topic}', focus='competitors') — sonar handles content fetching internally.\n"
        "2. sonar_research(['<topic> competitor pricing 2025', '<topic> alternatives Capterra G2 ProductHunt', "
        "'<topic> YC-backed startups funding', '<topic> competitor weaknesses reviews']) for deeper coverage.\n"
        "3. Extract at least 8 named competitors. Use fetch_and_read only for specific pricing pages sonar missed.\n"
        "4. patent_search and youtube_research when product demos/reviews matter.\n\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses), WHITESPACE OPPORTUNITIES, SOURCES."
        + _DONE_COMPETITORS
    ),
    "research_customers": (
        "CUSTOMER & ICP INTELLIGENCE (who buys, why, how, pain severity):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. build_research_queries(topic='{topic}', focus='customers') then sonar_research(queries).\n"
        "   Covers: Reddit/forum complaints, App Store/G2 reviews, pain signals, "
        "buyer demographics, job-to-be-done, willingness to pay, churn reasons, buying triggers.\n"
        "2. tiktok_research and youtube_research for consumer sentiment and creator commentary.\n"
        "3. Use fetch_and_read only for specific high-signal community pages sonar did not cover.\n\n"
        "obsidian_log with: ICP PROFILE (demographics, job title, company size), TOP PAIN POINTS (quoted), "
        "BUYING TRIGGERS, WILLINGNESS TO PAY, CHURN REASONS, SOURCES."
        + _DONE_CUSTOMERS
    ),
    "research_gtm": (
        "GO-TO-MARKET & DISTRIBUTION INTELLIGENCE (channels, growth tactics, pricing models):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. build_research_queries(topic='{topic}', focus='gtm') then sonar_research(queries).\n"
        "   Covers: how competitors acquire customers, CAC benchmarks, successful launch channels (PH, HN, Reddit, "
        "cold email, SEO, paid), pricing page patterns, freemium vs trial vs direct-sales split.\n"
        "2. news_search for recent launches and growth stories in this space.\n"
        "3. Use fetch_and_read only for specific competitor growth pages sonar did not cover.\n\n"
        "obsidian_log with: CHANNEL MAP (channel, fit, cost, speed), PRICING MODEL PATTERNS, "
        "LAUNCH PLAYBOOK (what worked for others), CAC BENCHMARKS, SOURCES."
        + _DONE_GTM
    ),
}


_MAX_RESEARCH_PLANS = {"scale", "beta"}
_RESEARCH_DEPTHS = {"quick", "normal", "max"}


def _normalize_research_depth(value: object) -> str:
    depth = str(value or "").strip().lower()
    aliases = {
        "fast": "quick",
        "standard": "normal",
        "default": "normal",
        "deep": "max",
        "super": "max",
        "super_deep": "max",
    }
    depth = aliases.get(depth, depth)
    return depth if depth in _RESEARCH_DEPTHS else ""


def _research_plan_for_founder(founder_id: str) -> str:
    try:
        from backend.accounts import get_or_create_org

        org = get_or_create_org(founder_id)
        entitlements = org.get("entitlements") or {}
        subscription = org.get("subscription") or {}
        return str(entitlements.get("plan_id") or subscription.get("plan") or "starter").lower()
    except Exception:
        return "starter"


def _is_max_research_plan(plan: str) -> bool:
    return (plan or "").lower() in _MAX_RESEARCH_PLANS


def _effective_research_depth(plan: str, requested_depth: object = "") -> str:
    requested = _normalize_research_depth(requested_depth)
    if requested:
        return requested
    return "max" if _is_max_research_plan(plan) else "normal"


def _research_depth_guidance(plan: str, requested_depth: object = "") -> str:
    depth = _effective_research_depth(plan, requested_depth)
    if depth == "max":
        return (
            "SUPER DEEP RESEARCH MODE (Max workspace):\n"
            "- Be THOROUGH: visit many sources across the web. Run multiple search rounds and read "
            "8-15 high-value pages before synthesizing.\n"
            "- Search broadly: run run_research_pipeline, THEN 2-4 sonar_research calls to fill gaps and "
            "go deeper on specifics. Aim for 15+ distinct cited sources before you finish.\n"
        )
    if depth == "quick":
        return (
            "QUICK RESEARCH MODE:\n"
            "- Optimize for speed. Run one narrow run_research_pipeline pass and synthesize immediately.\n"
            "- Aim for 3-5 distinct cited sources. Mark uncertainty instead of chasing every gap.\n"
            "- Do not run video, patent, academic, news, or extra fetches unless the founder explicitly asks.\n"
        )
    return (
        "NORMAL RESEARCH MODE:\n"
        "- Optimize for speed and decision quality. Do one focused run_research_pipeline pass, then at most "
        "one targeted sonar_research call only if a critical gap remains.\n"
        "- Read only the highest-signal pages sonar missed. Aim for 5-8 distinct cited sources, then synthesize.\n"
        "- Do not run video, patent, academic, or news research unless the founder explicitly asks or the topic requires it.\n"
    )


def _research_max_iterations(plan: str, requested: int | None = None, requested_depth: object = "") -> int:
    if requested is not None:
        return requested
    depth = _effective_research_depth(plan, requested_depth)
    if depth == "quick":
        return 14
    if depth == "max":
        return 40
    return 22


def _build_research_role(agent_name: str, focus_searches: str, plan: str, requested_depth: object = "") -> str:
    return (
        "You are an elite research specialist. Your ONLY domain is MARKET OPPORTUNITY — "
        "TAM/SAM/SOM, market growth trends, timing thesis, and investment narrative. "
        "NOT competitor profiling (research_competitors), NOT financial benchmarks (research_financial), "
        "NOT regulatory risk (research_regulatory), NOT customer personas (customer_discovery).\n\n"
        + _research_depth_guidance(plan, requested_depth)
        + "\nTOOLS:\n"
        "- run_research_pipeline(topic, focus) — first-pass: builds query plan + runs sonar_research in parallel. Use this first.\n"
        "- sonar_research(queries) — PRIMARY tool. Pass a list of research questions; each returns a synthesized cited answer. Replaces batch_search + fetch_and_read loops.\n"
        "- build_research_queries(topic, focus) — generates a high-coverage query plan. Pass result queries to sonar_research.\n"
        "- fetch_and_read(url) — read a specific URL in full depth. Use only for paywalled reports or specific pages sonar missed.\n"
        "- research_papers(query) — academic papers.\n"
        "- news_search(query) — recent news.\n"
        "- patent_search(query) — IP landscape.\n"
        "- youtube_research(query) — searches YouTube, returns metadata + transcript excerpts for the top results.\n"
        "- youtube_get_transcript(url_or_video_id) — full transcript + metadata for ONE specific video you already have a URL/ID for (e.g. the founder pasted a link). Use this instead of youtube_research when you're not searching.\n"
        "- tiktok_research(query) — TikTok video metadata + captions for viral trend analysis.\n"
        "- obsidian_log — FINAL step only after ALL searches complete.\n\n"
        "RESEARCH QUALITY RULES:\n"
        "- Generate specific, source-seeking queries. Avoid vague searches like just the product category.\n"
        "- Prefer primary sources, analyst reports, competitor pages, government/public datasets, and reputable review sites.\n"
        "- Check run_research_pipeline.coverage. If coverage.ready is false, fill gaps with one targeted search or clearly mark uncertainty.\n"
        "- Always name concrete companies, numbers, dates, and URLs. If evidence is weak, say so.\n"
        "- Be critical, not promotional. Try to DISPROVE the current idea, wedge, pricing, and ICP before you endorse them.\n"
        "- Surface the strongest bear case, the most fragile assumption, and the most promising pivot or narrowing option.\n"
        "- If research reveals a serious viability risk or a better direction, ask the founder for a decision using ask_user before finishing.\n\n"
        "YOUR SEARCH PLAN (replace {topic} with the actual subject):\n\n"
        + focus_searches
    )


def build_research_agent(agent_name: str = "research", **kwargs) -> Agent:
    # ctx_holder: mutable so wrappers can see the live AgentContext
    ctx_holder: list = [None]

    # _2/_3/_4 variants log to same Obsidian note as base so notes merge
    import re as _re
    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_batch = _make_auto_logging_tool(batch_search, "batch_search", ctx_holder, log_name)
    auto_sonar = _make_auto_logging_tool(sonar_research, "sonar_research", ctx_holder, log_name)
    auto_query_plan = _make_auto_logging_tool(build_research_queries, "build_research_queries", ctx_holder, log_name)
    auto_pipeline = _make_auto_logging_tool(run_research_pipeline, "run_research_pipeline", ctx_holder, log_name)
    auto_papers = _make_auto_logging_tool(research_papers, "research_papers", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder, log_name)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder, log_name)
    auto_youtube = _make_auto_logging_tool(youtube_research, "youtube_research", ctx_holder, log_name)
    auto_tiktok = _make_auto_logging_tool(tiktok_research, "tiktok_research", ctx_holder, log_name)
    auto_youtube_transcript = _make_auto_logging_tool(youtube_get_transcript, "youtube_get_transcript", ctx_holder, log_name)


    from backend.config import research_default_is_local, settings
    from backend.core.key_rotator import get_openrouter_key
    # Default research routing stays on OpenRouter unless local is explicitly
    # selected as the default provider.
    _use_local = research_default_is_local()
    model = kwargs.pop("model", settings.local_research_model if _use_local else settings.or_light_model)
    model_base_url = kwargs.pop("model_base_url", settings.local_research_base_url if _use_local else settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", settings.local_research_api_key if _use_local else (get_openrouter_key() or settings.agent_model_api_key))
    requested_max_iterations = kwargs.pop("max_iterations", None)
    _max_iter = _research_max_iterations("starter", requested_max_iterations)
    focus_searches = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])
    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=_max_iter,
        role=_build_research_role(agent_name, focus_searches, "starter"),
        tools={
            "run_research_pipeline": auto_pipeline,
            "sonar_research": auto_sonar,
            "build_research_queries": auto_query_plan,
            "search_and_fetch": auto_search,
            "batch_search": auto_batch,
            "fetch_and_read": auto_fetch,
            "research_papers": auto_papers,
            "news_search": auto_news,
            "patent_search": auto_patent,
            "youtube_research": auto_youtube,
            "youtube_get_transcript": auto_youtube_transcript,
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
        plan = _research_plan_for_founder(ctx.founder_id)
        constraints = (ctx.shared or {}).get("constraints") or {}
        requested_depth = constraints.get("research_depth") or (ctx.shared or {}).get("research_depth")
        agent.role = _build_research_role(agent_name, focus_searches, plan, requested_depth)
        agent.max_iterations = _research_max_iterations(plan, requested_max_iterations, requested_depth)
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

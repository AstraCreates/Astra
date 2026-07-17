"""Research specialist — autonomous browser-powered research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import (
    search_and_fetch,
    fetch_and_read,
    research_papers,
    batch_search,
    deep_research,
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


def _research_focus_for_agent(agent_name: str) -> str:
    if agent_name == "research_competitors":
        return "competitors"
    if agent_name == "research_customers":
        return "customers"
    if agent_name == "research_gtm":
        return "gtm"
    if agent_name == "research_execution":
        return "execution"
    return "market"


def _goal_topic(ctx: AgentContext | None) -> str:
    raw = (getattr(ctx, "goal", "") or "").strip()
    if not raw:
        return ""
    normalized = " ".join(raw.split())
    founder_section = raw.split("Founder goal:", 1)[1].strip() if "Founder goal:" in raw else raw
    founder_section = founder_section.split("\n\nStack:", 1)[0].strip()

    company_name = ""
    import re as _re
    name_match = _re.search(r"Company/project name:\s*(.+)", founder_section)
    if name_match:
        company_name = " ".join(name_match.group(1).split())

    profile = ""
    if "Business profile:" in founder_section:
        profile = founder_section.split("Business profile:", 1)[1]
        profile = profile.split("\n---", 1)[0].strip()

    post_name = ""
    if company_name and name_match:
        post_name = founder_section[name_match.end():].strip()
    elif "---" in founder_section:
        post_name = founder_section.split("---", 1)[1].strip()

    candidate_parts = [company_name, post_name or profile]
    candidate = " ".join(part.strip() for part in candidate_parts if part and part.strip())
    candidate = " ".join(candidate.split())
    if candidate:
        return candidate[:320]
    return normalized[:1200]


def _make_resilient_research_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "research"):
    """Fill common missing arguments from the active goal so research agents
    don't burn iterations on empty tool calls."""
    focus = _research_focus_for_agent(agent_name)
    force_lane_focus = agent_name in {"research_competitors", "research_customers", "research_gtm"}

    @functools.wraps(tool_fn)
    def wrapper(*args, **kwargs):
        ctx: AgentContext | None = ctx_holder[0] if ctx_holder else None
        topic = _goal_topic(ctx)
        patched_kwargs = dict(kwargs)

        if tool_name in {"run_research_pipeline", "build_research_queries"}:
            if not args and not patched_kwargs.get("topic") and not patched_kwargs.get("query") and topic:
                patched_kwargs["topic"] = topic
            if force_lane_focus:
                patched_kwargs["focus"] = focus
            else:
                patched_kwargs.setdefault("focus", focus)
        elif tool_name == "research_papers":
            if not args and not patched_kwargs.get("query") and topic:
                patched_kwargs["query"] = topic
        elif tool_name in {"deep_research", "sonar_research"}:
            # Real production bug: the role prompt tells agents to call
            # deep_research(queries) directly (sonar_research is its
            # documented alias), but the model sometimes omits queries
            # entirely, passes an empty list, or passes a singular `query`
            # string (matching the singular naming every other research tool
            # uses) instead of the plural `queries` list deep_research
            # actually takes — deep_research has no built-in tolerance for
            # any of these and just returns a hard "queries required" error,
            # repeatedly, burning turns with zero research done.
            if not args and not patched_kwargs.get("queries"):
                single = patched_kwargs.pop("query", None)
                if single:
                    patched_kwargs["queries"] = [single] if isinstance(single, str) else list(single)
                elif topic:
                    plan = build_research_queries(topic, focus=focus, limit=6)
                    patched_kwargs["queries"] = plan.get("queries") or [topic]
            if "max_rounds" not in patched_kwargs and "depth" in patched_kwargs:
                patched_kwargs["max_rounds"] = patched_kwargs.pop("depth")
        elif tool_name == "search_and_fetch":
            # Only backfill when the model gave us nothing usable at all — a
            # `url` kwarg (model confusing this with fetch_and_read) is real
            # intent and must not be overwritten with an unrelated auto-query.
            if not args and not patched_kwargs.get("query") and not patched_kwargs.get("url") and topic:
                plan = build_research_queries(topic, focus=focus, limit=1)
                queries = plan.get("queries") or [topic]
                patched_kwargs["query"] = queries[0]
        elif tool_name == "news_search":
            if not args and not patched_kwargs.get("query") and topic:
                patched_kwargs["query"] = topic

        return tool_fn(*args, **patched_kwargs)

    return wrapper


_DONE_INSTRUCTIONS = (
    "\n\nDONE OUTPUT — plain text values only, no markdown stars, no bullet symbols, no emojis.\n"
    "After obsidian_log, call done with this exact JSON structure (fill only the market fields from research; do not invent competitor/customer/GTM details for this lane):\n"
    '{"action":"done","output":{'
    '"summary":"one paragraph synthesis of all findings",'
    '"market_size":"TAM/SAM/SOM with concrete numbers e.g. $12B TAM growing 18% CAGR",'
    '"risks":"top 2-3 risks in 1-2 sentences",'
    '"sources":["url1","url2"]}}\n'
    "Use injected company brain context only if it already contains a market thesis; otherwise keep the output strictly market-focused and do not backfill missing company-positioning fields.\n"
    "Before done, pressure-test the market thesis hard: what is weak, crowded, unconvincing, or likely to fail? "
    "If the evidence points to a materially different market thesis, call ask_user with a decision-grade question before done."
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

_DONE_EXECUTION = (
    "\n\nDONE OUTPUT — plain text, no markdown.\n"
    '{"action":"done","output":{'
    '"execution_strategy":"first-90-days plan grounded in comparable founder case studies, 2-3 sentences",'
    '"go_to_market":"GTM channels, sequencing, and early-traction playbook, 1-2 sentences",'
    '"recommended_tech_stack":"tech stack recommendation with rationale, 1-2 sentences",'
    '"summary":"execution intelligence synthesis",'
    '"sources":["url1","url2"]}}\n'
)

_FOCUS_ROLES = {
    "research": (
        "MARKET OPPORTUNITY RESEARCH — cover market sizing, timing, and investment narrative only:\n\n"
        "1. MARKET (TAM/SAM/SOM, growth, regulation, funding, timing thesis): run_research_pipeline(focus='market') "
        "for grounded source discovery. Call it again with refined queries if coverage gaps remain.\n\n"
        "Finish the market pass before logging.\n\n"
        "obsidian_log with MARKET sections only: MARKET SIZE, GROWTH DRIVERS, TIMING THESIS, SOURCES."
        + _DONE_INSTRUCTIONS
    ),
    "research_competitors": (
        "COMPETITOR INTELLIGENCE (named companies, pricing, features, weaknesses):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. run_research_pipeline(topic='{topic}', focus='competitors') for grounded source discovery. Call it "
        "again with more specific queries (pricing, alternatives, funding, weaknesses/reviews) if coverage gaps remain "
        "or deeper competitive evidence is required.\n"
        "2. Extract at least 8 named competitors.\n\n"
        "obsidian_log with: COMPETITOR TABLE (name, URL, pricing, funding, strengths, weaknesses), WHITESPACE OPPORTUNITIES, SOURCES."
        + _DONE_COMPETITORS
    ),
    "research_customers": (
        "CUSTOMER & ICP INTELLIGENCE (who buys, why, how, pain severity):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. build_research_queries(topic='{topic}', focus='customers') to plan targeted queries.\n"
        "2. run_research_pipeline(topic='{topic}', focus='customers') for grounded evidence: Reddit/forum complaints, "
        "App Store/G2 reviews, pain signals, buyer demographics, job-to-be-done, willingness to pay, churn reasons, "
        "buying triggers. Call it again with refined queries if coverage gaps remain.\n"
        "If run_research_pipeline returns coverage.ready=true or next_step says to synthesize, finish without another pass.\n"
        "If evidence is still thin after that, log the uncertainty rather than guessing.\n\n"
        "obsidian_log with: ICP PROFILE (demographics, job title, company size), TOP PAIN POINTS (quoted), "
        "BUYING TRIGGERS, WILLINGNESS TO PAY, CHURN REASONS, SOURCES."
        + _DONE_CUSTOMERS
    ),
    "research_gtm": (
        "GO-TO-MARKET & DISTRIBUTION INTELLIGENCE (channels, growth tactics, pricing models):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. build_research_queries(topic='{topic}', focus='gtm') to plan targeted queries.\n"
        "2. run_research_pipeline(topic='{topic}', focus='gtm') for grounded evidence: how competitors acquire "
        "customers, CAC benchmarks, successful launch channels (PH, HN, Reddit, cold email, SEO, paid), pricing "
        "page patterns, freemium vs trial vs direct-sales split, recent launches in this space. Call it again with "
        "refined queries if coverage gaps remain.\n"
        "If run_research_pipeline returns coverage.ready=true or next_step says to synthesize, finish without another pass.\n"
        "If evidence remains thin, log the gap explicitly rather than guessing.\n\n"
        "obsidian_log with: CHANNEL MAP (channel, fit, cost, speed), PRICING MODEL PATTERNS, "
        "LAUNCH PLAYBOOK (what worked for others), CAC BENCHMARKS, SOURCES."
        + _DONE_GTM
    ),
    "research_execution": (
        "EXECUTION & GO-TO-MARKET INTELLIGENCE (first-90-days plan, GTM sequencing, tech stack):\n"
        "FIRST: call obsidian_read to see what prior research passes already found. Skip any sources already cited.\n"
        "1. run_research_pipeline(topic='{topic}', focus='execution') for grounded evidence: comparable founder "
        "case studies, launch sequencing, common early-execution mistakes, GTM channel sequencing, recommended tech "
        "stack rationale. Call it again with refined queries if coverage gaps remain.\n\n"
        "obsidian_log with: FIRST-90-DAYS PLAN, GTM SEQUENCING, TECH STACK RECOMMENDATION, SOURCES."
        + _DONE_EXECUTION
    ),
}


_MAX_RESEARCH_PLANS = {"scale"}


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


def _effective_is_deep(plan: str, depth_override: str | None = None) -> bool:
    """Founder-chosen research_depth constraint (fast/deep) takes precedence
    over the billing-tier default; unset falls back to plan tier."""
    if depth_override == "deep":
        return True
    if depth_override == "fast":
        return False
    return _is_max_research_plan(plan)


def _research_depth_guidance(plan: str, depth_override: str | None = None) -> str:
    if _effective_is_deep(plan, depth_override):
        return (
            "SUPER DEEP RESEARCH MODE (Max workspace):\n"
            "- Be THOROUGH: visit many sources across the web. Run multiple search rounds and read "
            "8-15 high-value pages before synthesizing.\n"
            "- Search broadly: run run_research_pipeline, then use 2-4 deep_research calls as escalation to fill remaining gaps "
            "and go deeper on specifics. Aim for 15+ distinct cited sources before you finish.\n"
        )
    return (
        "FAST RESEARCH MODE:\n"
        "- Optimize for speed and decision quality. Do one focused run_research_pipeline pass, then at most "
        "one targeted deep_research call only if a critical gap remains.\n"
        "- Read only the highest-signal pages sonar missed. Aim for 5-8 distinct cited sources, then synthesize.\n"
        "- If the first pass already has enough named sources and concrete signals, stop there and write the brief.\n"
        "- Do not run video, patent, academic, or news research unless the founder explicitly asks or the topic requires it.\n"
    )


def _research_max_iterations(plan: str, requested: int | None = None, depth_override: str | None = None) -> int:
    if requested is not None:
        return requested
    return 60 if _effective_is_deep(plan, depth_override) else 24


def _research_tool_call_caps(agent_name: str, is_deep: bool) -> dict[str, int]:
    """Keep tool limits aligned with the fast/deep instructions in the role.

    Every lane's own prompt tells it to re-call run_research_pipeline with
    refined queries when coverage.ready comes back false ("fill gaps with
    one targeted search") -- capping this at 1 for narrow lanes (research_gtm,
    research_customers, research_market, etc.) directly contradicted that
    instruction. The model would try the retry its own prompt told it to
    make, get BLOCKED by the cap, and burn the rest of its iteration budget
    stuck instead of finishing -- confirmed production failure
    (research_gtm hit max_iterations_reached after run_research_pipeline
    returned incomplete coverage on its one and only allowed call). Give
    every lane room for the one legitimate refinement call its prompt
    promises; "research" (the comprehensive lane covering 4 areas) gets one
    more on top of that in deep mode.
    """
    deep_calls = 4 if agent_name == "research" else 2
    pipeline_calls = 3 if is_deep and agent_name == "research" else 2
    return {"run_research_pipeline": pipeline_calls, "deep_research": deep_calls if is_deep else 1, "search_and_fetch": 1, "fetch_and_read": 2 if agent_name in {"research", "research_competitors"} else 1, "obsidian_read": 1, "obsidian_log": 1}


def _build_research_role(agent_name: str, focus_searches: str, plan: str, depth_override: str | None = None) -> str:
    return (
        "You are an elite research specialist. Your ONLY domain is MARKET OPPORTUNITY — "
        "TAM/SAM/SOM, market growth trends, timing thesis, and investment narrative. "
        "NOT competitor profiling (research_competitors), NOT financial benchmarks (research_financial), "
        "NOT regulatory risk (research_regulatory), NOT customer personas (customer_discovery).\n\n"
        + _research_depth_guidance(plan, depth_override)
        + "\nTOOLS:\n"
        "- run_research_pipeline(topic, focus) — your PRIMARY and only real research tool. Plans queries and runs "
        "them through provider-native grounded search (real live web evidence, not a shallow snippet pass) in one "
        "call. You get exactly ONE refinement call beyond the first if coverage gaps remain — there is no "
        "separate 'deep_research' escalation tool anymore, this same call handles both first-pass and deep passes.\n"
        "  STOP RULE: check the returned coverage.ready and next_step fields. If coverage.ready is true or "
        "next_step says 'Synthesize findings', DO NOT call run_research_pipeline again — you already have enough. "
        "Move straight to writing your findings and calling obsidian_log.\n"
        "  IF BLOCKED: if a tool result ever starts with 'BLOCKED', you have used your calls to that tool — do not "
        "retry it, do not call build_research_queries again hoping for a different result. Immediately write your "
        "findings with whatever evidence you already have (clearly marking any gaps as unconfirmed) and call "
        "obsidian_log to finish. A brief with an honestly marked gap is far better than never finishing.\n"
        "- build_research_queries(topic, focus) — generates a high-coverage query plan when you need more targeted "
        "queries than the topic alone gives run_research_pipeline.\n"
        "- obsidian_log — FINAL step only after ALL research is complete. Put your FULL findings here, in as "
        "much detail as the evidence supports.\n\n"
        "YOUR done OUTPUT MUST BE SHORT — a 2-3 sentence summary plus key facts (named companies, numbers, "
        "dates), NOT a repeat of the full findings you already wrote to obsidian_log. A done call that tries "
        "to inline the entire writeup risks getting cut off mid-JSON by the output length limit, which fails "
        "outright and wastes the iterations you have left. Confirmed production failure: an oversized done "
        "call got truncated, produced invalid JSON, and burned the rest of the run's budget retrying instead "
        "of finishing. Short done output, full findings in obsidian_log — every time.\n\n"
        "RESEARCH QUALITY RULES:\n"
        "- Generate specific, source-seeking queries. Avoid vague searches like just the product category.\n"
        "- Prefer primary sources, analyst reports, competitor pages, government/public datasets, and reputable review sites.\n"
        "- Check run_research_pipeline.coverage. If coverage.ready is false, use your one refinement call with a "
        "sharper query, then write up with what you have and clearly mark uncertainty — never spin past that.\n"
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
    resilient_search = _make_resilient_research_tool(search_and_fetch, "search_and_fetch", ctx_holder, agent_name)
    resilient_fetch = _make_resilient_research_tool(fetch_and_read, "fetch_and_read", ctx_holder, agent_name)
    resilient_batch = _make_resilient_research_tool(batch_search, "batch_search", ctx_holder, agent_name)
    resilient_deep = _make_resilient_research_tool(deep_research, "deep_research", ctx_holder, agent_name)
    resilient_sonar = _make_resilient_research_tool(sonar_research, "sonar_research", ctx_holder, agent_name)
    resilient_query_plan = _make_resilient_research_tool(build_research_queries, "build_research_queries", ctx_holder, agent_name)
    resilient_pipeline = _make_resilient_research_tool(run_research_pipeline, "run_research_pipeline", ctx_holder, agent_name)
    resilient_papers = _make_resilient_research_tool(research_papers, "research_papers", ctx_holder, agent_name)
    resilient_news = _make_resilient_research_tool(news_search, "news_search", ctx_holder, agent_name)

    auto_search = _make_auto_logging_tool(resilient_search, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(resilient_fetch, "fetch_and_read", ctx_holder, log_name)
    auto_batch = _make_auto_logging_tool(resilient_batch, "batch_search", ctx_holder, log_name)
    auto_deep = _make_auto_logging_tool(resilient_deep, "deep_research", ctx_holder, log_name)
    auto_sonar = _make_auto_logging_tool(resilient_sonar, "sonar_research", ctx_holder, log_name)
    auto_query_plan = _make_auto_logging_tool(resilient_query_plan, "build_research_queries", ctx_holder, log_name)
    auto_pipeline = _make_auto_logging_tool(resilient_pipeline, "run_research_pipeline", ctx_holder, log_name)
    auto_papers = _make_auto_logging_tool(resilient_papers, "research_papers", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(resilient_news, "news_search", ctx_holder, log_name)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder, log_name)
    auto_youtube = _make_auto_logging_tool(youtube_research, "youtube_research", ctx_holder, log_name)
    auto_tiktok = _make_auto_logging_tool(tiktok_research, "tiktok_research", ctx_holder, log_name)
    auto_youtube_transcript = _make_auto_logging_tool(youtube_get_transcript, "youtube_get_transcript", ctx_holder, log_name)


    from backend.config import research_default_is_local, settings
    from backend.core.key_rotator import get_openrouter_key
    # Default research routing stays on OpenRouter unless local is explicitly
    # selected as the default provider.
    _use_local = research_default_is_local()
    model = kwargs.pop("model", settings.local_research_model if _use_local else settings.research_agent_model)
    model_base_url = kwargs.pop("model_base_url", settings.local_research_base_url if _use_local else settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", settings.local_research_api_key if _use_local else (get_openrouter_key() or settings.agent_model_api_key))
    requested_max_iterations = kwargs.pop("max_iterations", None)
    _max_iter = _research_max_iterations("starter", requested_max_iterations)
    focus_searches = _FOCUS_ROLES.get(agent_name, _FOCUS_ROLES["research"])
    # Real production bug: run_research_pipeline returns coverage.ready=True with
    # next_step="Synthesize findings..." but the fast research model (ling-2.6-flash)
    # sometimes ignores that signal and keeps re-calling the same first-pass tool with
    # rephrased queries — observed running 8+ times before hitting max_iterations,
    # burning ~1M tokens on one lane. The prompt already tells it to stop; this is the
    # code-level backstop, reusing the same max_tool_calls mechanism marketing agents
    # already use (factory.py) to hard-cap repeat calls to the same tool.
    #
    # Caps are per-role, not flat, because each role's own prompt asks for a
    # different amount of legitimate tool use:
    # - "research" (comprehensive, covers all 4 areas): run_research_pipeline for
    #   market + competitors (2 legit calls) plus retries, and deep_research for
    #   customers + gtm (2 legit calls) plus escalation retries in deep mode.
    # - "research_competitors": one area, run_research_pipeline first then
    #   deep_research escalation — needs the least of either.
    # - "research_customers" / "research_gtm": one area each, deep_research is
    #   their PRIMARY tool (their prompts don't call run_research_pipeline at
    #   all), so deep_research gets more room than run_research_pipeline.
    # search_and_fetch/fetch_and_read were NOT capped here originally — a real
    # production incident showed research_competitors calling search_and_fetch
    # 20+ times in a row (each one a real full-page fetch, not a cheap snippet
    # call) before hitting max_iterations, burning real tokens the whole way.
    # Every role's own prompt already says to use these "only for specific
    # pages deep_research/run_research_pipeline missed" — a handful of calls,
    # not dozens — so cap them at the same order of magnitude as deep_research.
    _requested_tool_caps = kwargs.pop("max_tool_calls", None) or {}
    _tool_call_caps = _research_tool_call_caps(agent_name, is_deep=False)
    _tool_call_caps.update(_requested_tool_caps)
    lane_tools = {
        "run_research_pipeline": auto_pipeline,
        "deep_research": auto_deep,
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
    }
    if agent_name in {"research", "research_market", "research_financial", "research_regulatory", "research_execution", "research_competitors", "research_customers", "research_gtm"}:
        lane_tools.pop("deep_research", None)
        lane_tools.pop("sonar_research", None)

    if agent_name in {"research", "research_market", "research_financial", "research_regulatory", "research_execution", "research_competitors", "research_customers", "research_gtm"}:
        for _research_tool in ("batch_search", "search_and_fetch", "fetch_and_read", "deep_research", "sonar_research", "research_papers", "news_search", "patent_search", "youtube_research", "youtube_get_transcript", "tiktok_research"):
            lane_tools.pop(_research_tool, None)

    # Research wrappers already persist evidence and the final report. Do not
    # expose the generic append path, which invites one-write-per-thought loops.
    lane_tools.pop("obsidian_append", None)
    # Keep narrow lanes on their intended path. In production these agents were
    # repeatedly drifting into random search_and_fetch/fetch_and_read URL loops
    # (often junk or ambiguous pages) instead of taking the required
    # deep_research pass that their own prompts demand.
    if agent_name == "research":
        lane_tools.pop("search_and_fetch", None)
        lane_tools.pop("fetch_and_read", None)
        lane_tools.pop("batch_search", None)
        lane_tools.pop("research_papers", None)
        lane_tools.pop("patent_search", None)
    elif agent_name == "research_customers":
        lane_tools.pop("search_and_fetch", None)
        lane_tools.pop("fetch_and_read", None)
        lane_tools.pop("batch_search", None)
        lane_tools.pop("research_papers", None)
        lane_tools.pop("patent_search", None)
        lane_tools.pop("news_search", None)
    elif agent_name == "research_gtm":
        lane_tools.pop("search_and_fetch", None)
        lane_tools.pop("fetch_and_read", None)
        lane_tools.pop("batch_search", None)
        lane_tools.pop("research_papers", None)
        lane_tools.pop("patent_search", None)

    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=_max_iter,
        max_tool_calls=_tool_call_caps,
        role=_build_research_role(agent_name, focus_searches, "starter"),
        tools=lane_tools,
        **kwargs,
    )

    # Patch run to inject ctx into ctx_holder before each run
    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        plan = _research_plan_for_founder(ctx.founder_id)
        depth_override = ((ctx.shared or {}).get("constraints") or {}).get("research_depth")
        agent.role = _build_research_role(agent_name, focus_searches, plan, depth_override)
        agent.max_iterations = _research_max_iterations(plan, requested_max_iterations, depth_override)
        agent.max_tool_calls = _research_tool_call_caps(agent_name, _effective_is_deep(plan, depth_override))
        agent.max_tool_calls.update(_requested_tool_caps)
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

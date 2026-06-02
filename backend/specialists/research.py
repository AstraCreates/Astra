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
        model="meta-llama/llama-3.3-70b-instruct",
        model_base_url=settings.openrouter_base_url,
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

        # Extract topic then build the 30 topic-specific queries
        topic = await _extract_topic(ctx.goal or "")
        queries = _build_queries(topic, agent_name)

        # Format queries into 4 sequential batches of 8 for the agent to call
        batches = [queries[i:i+8] for i in range(0, min(len(queries), 32), 8)]
        batch_lines = []
        for i, batch in enumerate(batches, 1):
            quoted = [f'"{q}"' for q in batch]
            batch_lines.append(f"Batch {i}: batch_search(queries=[{', '.join(quoted)}])")
        query_block = "\n".join(batch_lines)

        agent.role = (
            f"You are an elite research specialist. Task: {focus_config['goal']}.\n"
            f"Topic: \"{topic}\"\n\n"
            "RULES (non-negotiable):\n"
            f"1. Execute the queries below EXACTLY as written — every query contains \"{topic}\".\n"
            "2. After batch_search returns results, ONLY call fetch_and_read on URLs where the page title "
            f"or snippet explicitly mentions \"{topic}\" or a direct synonym. "
            "Skip Wikipedia, generic news, social media, unrelated company pages.\n"
            "3. NEVER search for anything outside the provided query list.\n"
            "4. If a batch_search returns no useful results, move to the next batch — do not improvise.\n\n"
            f"QUERIES (run all 4 batches in order):\n{query_block}\n\n"
            "STEPS:\n"
            "1. batch_search(Batch 1) → review titles/snippets → fetch_and_read ONLY relevant URLs.\n"
            "2. batch_search(Batch 2) → same filter.\n"
            "3. batch_search(Batch 3) → same filter.\n"
            "4. batch_search(Batch 4) → same filter.\n"
            "5. news_search for recent news if gaps remain.\n"
            "6. Self-evaluate checklist below → targeted follow-up batch_search if needed.\n"
            "7. obsidian_log with complete findings.\n\n"
            f"{focus_config['instructions']}"
        )
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent


def _build_queries(topic: str, agent_name: str) -> list:
    """
    Build targeted search queries. Each query quotes the topic to force relevance —
    search engines only return pages that actually mention the topic.
    """
    base = _re.sub(r"_\d+$", "", agent_name)
    t = topic  # shorthand

    if base in ("research", "research_market"):
        return [
            f'"{t}" market size revenue 2024 2025',
            f'"{t}" industry growth rate CAGR forecast report',
            f'"{t}" total addressable market TAM analysis',
            f'"{t}" venture capital funding startups 2024',
            f'"{t}" customer segments target audience demographics',
            f'"{t}" regulatory compliance legal requirements',
            f'"{t}" market trends 2025 emerging technology',
            f'"{t}" pricing model subscription cost benchmark',
            f'"{t}" user pain points problems challenges site:medium.com OR site:dev.to',
            f'"{t}" market size revenue TAM site:statista.com OR site:grandviewresearch.com',
            f'"{t}" funding investment venture capital site:crunchbase.com',
            f'"{t}" industry news 2024 2025 site:forbes.com OR site:businesswire.com',
            f'"{t}" industry report analyst 2024 site:gartner.com OR site:forrester.com',
            f'"{t}" market share leading companies revenue site:pitchbook.com',
            f'"{t}" barriers entry challenges startup site:investopedia.com',
            f'"{t}" B2B enterprise customer segments site:linkedin.com',
            f'"{t}" unit economics SaaS metrics site:saastr.com OR site:stripe.com',
            f'"{t}" geographic expansion international site:mckinsey.com OR site:bcg.com',
            f'"{t}" regulatory environment policy site:reuters.com OR site:bloomberg.com',
            f'"{t}" adoption rate growth statistics site:pew.org OR site:statista.com',
            f'"{t}" investor report outlook 2025 site:ivey.ca OR site:kpmg.com',
            f'"{t}" competitive landscape map companies site:mapbox.com OR site:notion.so',
            f'"{t}" use cases customer success stories site:case-studies.com',
            f'"{t}" market opportunity gap whitespace site:harvard.edu OR site:stanford.edu',
            f'"{t}" patent filings IP landscape site:patents.google.com',
            f'"{t}" community discussion trends site:quora.com OR site:producthunt.com',
            f'"{t}" academic research findings study site:scholar.google.com',
            f'"{t}" funding announcement news 2025 site:vcnewsdaily.com',
            f'"{t}" analyst report gartner OR forrester OR cbinsights site:gartner.com',
            f'"{t}" growth trend forecast outlook site:McKinsey.com OR site:PwC.com',
        ]

    if base == "research_financial":
        return [
            f'"{t}" funding rounds investors raised capital site:crunchbase.com',
            f'"{t}" venture capital Series A B C site:pitchbook.com',
            f'"{t}" valuation latest funding round 2024 2025',
            f'"{t}" investor portfolio companies site:a16z.com OR site:sequoia.com',
            f'"{t}" revenue ARR SaaS business model metrics',
            f'"{t}" IPO exit acquisition valuation comparable',
            f'"{t}" venture return analysis investor ROI outcomes',
            f'"{t}" fundraising timeline milestones burn rate runway',
            f'"{t}" cap table dilution equity financing rounds',
            f'"{t}" angel investors seed funding network startup',
            f'"{t}" venture debt financing SaaS growth funding',
            f'"{t}" revenue benchmarks cohort retention metrics site:saastr.com',
            f'"{t}" unit economics growth multiple CAC LTV ratio',
            f'"{t}" exit strategies acquisition targets bidders site:pitchbook.com',
            f'"{t}" venture market size funding available capital pool',
            f'"{t}" investor check size typical round size stage',
            f'"{t}" due diligence financials investor questions site:forentrepreneurs.com',
            f'"{t}" salary equity compensation early employees site:levels.fyi',
            f'"{t}" dilution antidilution rights preferences financing',
            f'"{t}" venture thesis investor focus criteria checklist',
            f'"{t}" fundraising deck pitch what investors want site:docsend.com',
            f'"{t}" portfolio company performance tracking metrics benchmarks',
            f'"{t}" term sheet valuation economics preferred stock',
            f'"{t}" venture capital concentration risk market evolution',
            f'"{t}" financing gap bridge round convertible note',
            f'"{t}" venture return outlook fund performance 2024 2025',
            f'"{t}" investor confidence market sentiment funding available',
            f'"{t}" comparable acquisitions valuation multiples EBITDA',
            f'"{t}" minority stake preference structure liquidation',
            f'"{t}" venture opportunity size addressable market capital flow',
        ]

    if base == "research_regulatory":
        return [
            f'"{t}" regulatory compliance requirements legal framework',
            f'"{t}" government policy regulations industry specific laws',
            f'"{t}" licensing requirements permits startup compliance',
            f'"{t}" data privacy GDPR CCPA compliance requirements site:iubenda.com',
            f'"{t}" SOC2 compliance certification security standards',
            f'"{t}" industry regulations standards compliance bodies',
            f'"{t}" tax implications business structure LLC C-Corp',
            f'"{t}" employment law hiring contractors legal requirements',
            f'"{t}" intellectual property patent trademark copyright',
            f'"{t}" product liability insurance requirements risk',
            f'"{t}" contract law terms conditions privacy policy',
            f'"{t}" international expansion regulatory requirements countries',
            f'"{t}" import export compliance tariffs trade regulations',
            f'"{t}" financial services regulations FINRA SEC compliance',
            f'"{t}" healthcare HIPAA compliance medical device regulations',
            f'"{t}" environmental compliance sustainability regulations',
            f'"{t}" labor law compliance wage hour overtime rules',
            f'"{t}" anti-corruption FCPA bribery compliance international',
            f'"{t}" accessibility compliance ADA WCAG requirements',
            f'"{t}" antitrust competition law restrictions practices',
            f'"{t}" consumer protection law FTC regulations practices',
            f'"{t}" legal entity formation Delaware C-Corp advantages',
            f'"{t}" escrow agreement dispute resolution arbitration',
            f'"{t}" regulatory filing requirements SEC Edgar filings',
            f'"{t}" compliance timeline deadline critical milestones',
            f'"{t}" audit requirements external auditors SOX compliance',
            f'"{t}" regulatory risk matrix assessment industry specific',
            f'"{t}" legal counsel recommendation startup law firms site:startuplegal.com',
            f'"{t}" compliance automation tools frameworks requirements',
            f'"{t}" regulatory intelligence monitoring changes requirements',
        ]

    if base == "research_competitors":
        return [
            f'"{t}" companies platforms list 2024 2025 -site:reddit.com',
            f'"{t}" startups site:crunchbase.com funding raised',
            f'"{t}" alternatives competitors site:g2.com OR site:capterra.com',
            f'"{t}" best tools site:producthunt.com OR site:alternativeto.net',
            f'"{t}" Y Combinator YC startup companies site:ycombinator.com',
            f'"{t}" top companies site:linkedin.com/company OR site:glassdoor.com',
            f'"{t}" pricing plans cost per month comparison -site:techcrunch.com',
            f'"{t}" market map named players landscape site:cbinsights.com OR site:preqin.com',
            f'"{t}" vs comparison feature comparison site:trustradius.com',
            f'"{t}" reviews sentiment site:trustpilot.com OR site:sitejabber.com',
            f'"{t}" funding Series A B site:crunchbase.com 2023 2024',
            f'"{t}" startup pitch deck investor presentation',
            f'"{t}" customer reviews complaints site:g2.com OR site:trustpilot.com',
            f'"{t}" feature comparison table strengths weaknesses',
            f'"{t}" CEO founder interview company overview',
            f'"{t}" revenue ARR MRR growth metrics',
            f'"{t}" acquisition partnership integration',
            f'"{t}" open source alternative github',
            f'"{t}" enterprise pricing annual contract',
            f'"{t}" free trial freemium model overview',
            f'"{t}" API documentation developer platform',
            f'"{t}" customers case study named clients',
            f'"{t}" product launch new features 2025',
            f'"{t}" team size employees headcount linkedin',
            f'"{t}" white label reseller OEM',
            f'"{t}" international expansion countries',
            f'"{t}" valuation latest funding round 2024',
            f'"{t}" NPS score customer satisfaction',
            f'"{t}" site:linkedin.com company overview employees',
            f'"{t}" named companies founded 2020 2021 2022 2023',
        ]

    # research_execution
    return [
        f'"{t}" go-to-market strategy launch site:builtwith.com OR site:semrush.com',
        f'"{t}" business model revenue streams site:stripe.com/resources',
        f'"{t}" tech stack architecture choices site:github.com OR site:stackoverflow.com',
        f'"{t}" customer acquisition cost CAC site:napkincalculator.com OR site:saastr.com',
        f'"{t}" user pain points discussion site:reddit.com/r/entrepreneur',
        f'"{t}" regulatory compliance requirements startup site:startuplegal.com',
        f'"{t}" sales strategy channels B2B B2C site:hubspot.com/resources',
        f'"{t}" founder interview how we built site:ycombinator.com/launches',
        f'"{t}" first 100 customers strategy site:growthhackers.com',
        f'"{t}" pricing strategy models site:pricewell.io OR site:stripe.com/pricing',
        f'"{t}" product market fit signals site:lenny.substack.com OR site:andrewchen.com',
        f'"{t}" SaaS metrics LTV CAC unit economics site:forentrepreneurs.com',
        f'"{t}" content marketing SEO strategy site:ahrefs.com/blog OR site:moz.com/blog',
        f'"{t}" paid acquisition performance ROI site:clv.com OR site:databox.com',
        f'"{t}" hiring early team roles site:levels.fyi OR site:blindley.com',
        f'"{t}" retention churn reduction onboarding site:neilpatel.com',
        f'"{t}" infrastructure scaling architecture site:aws.amazon.com/builders',
        f'"{t}" security compliance GDPR SOC2 site:security.stackexchange.com',
        f'"{t}" partnership integration channel site:partners.slack.com',
        f'"{t}" investor pitch deck metrics site:docsend.com OR site:pitchdeck.com',
        f'"{t}" competitive moat defensibility site:strategyzer.com',
        f'"{t}" community building early adopters site:community.webflow.com',
        f'"{t}" startup lessons case study site:firstround.com/review',
        f'"{t}" case study ROI success metrics site:casebase.com',
        f'"{t}" youtube tutorial build launch site:youtube.com OR site:vimeo.com',
        f'"{t}" API integration third party tools site:rapidapi.com',
        f'"{t}" database architecture backend site:github.com/trending',
        f'"{t}" frontend framework design system site:storybook.js.org',
        f'"{t}" viral loop referral product site:growth.design',
        f'"{t}" startup failure lessons site:postmortem.tech OR site:indiehackers.com',
    ]


def _regex_extract_topic(goal: str) -> str:
    """Deterministic topic extraction — no LLM, no hallucination."""
    goal = goal.replace("\n", " ").strip()
    # Remove leading instruction verbs
    cleaned = _re.sub(
        r"^(build|create|make|develop|launch|start|design|implement|i want to|we want to|"
        r"help me build|i need|we need|build me|create me)[:\s]+(?:a\s+|an\s+|the\s+)?",
        "", goal, flags=_re.IGNORECASE
    ).strip()
    # Trim at implementation details
    cleaned = _re.sub(
        r"\s+(with|that|for|using|which|where|featuring|including|and a|also)\s+.*$",
        "", cleaned, flags=_re.IGNORECASE
    ).strip()
    # Cap length
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rsplit(" ", 1)[0]
    return cleaned.strip() or goal[:60].strip()


def _is_bad_topic(phrase: str) -> bool:
    """Return True if the phrase looks like a hallucination/abbreviation."""
    words = phrase.strip().split()
    # Too short
    if len(words) < 2:
        return True
    # All-caps single token (CO, AI, B2B alone, etc.)
    if any(_re.fullmatch(r'[A-Z]{1,4}', w) for w in words):
        return True
    # Contains math/code
    if any(c in phrase for c in ['=', '+', '->', '()', '<', '>']):
        return True
    return False


async def _extract_topic(goal: str) -> str:
    """Extract the core product phrase. Regex first (reliable), LLM to enhance if needed."""
    # Always start with deterministic regex — never hallucinates
    regex_result = _regex_extract_topic(goal)

    # Only use LLM for complex multi-sentence goals where regex truncates badly
    if len(goal.split()) <= 12:
        return regex_result  # short goal, regex is perfect

    from backend.config import settings
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        )
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model="meta-llama/llama-3.3-70b-instruct",
            messages=[{
                "role": "user",
                "content": (
                    "Extract the core product/domain phrase from this goal. "
                    "Output ONLY 3-6 words. Write ALL words in FULL — never abbreviate, never use acronyms alone.\n"
                    "CRITICAL: 'co-founder' must stay as 'co-founder' not 'CO'. "
                    "'artificial intelligence' not 'AI' alone. Write the full hyphenated word.\n"
                    "Examples:\n"
                    "→ 'co-founder matching platform'\n"
                    "→ 'AI stock trading signal platform'\n"
                    "→ 'restaurant inventory management software'\n\n"
                    f"Goal: {goal[:400]}\n\nProduct phrase (3-6 words, no abbreviations):"
                ),
            }],
            max_tokens=15,
            temperature=0.0,
        )
        phrase = resp.choices[0].message.content.strip().strip('"\'').strip()
        if phrase and 2 <= len(phrase.split()) <= 8 and not _is_bad_topic(phrase):
            return phrase
    except Exception as e:
        logger.warning("_extract_topic LLM failed: %s", e)

    return regex_result

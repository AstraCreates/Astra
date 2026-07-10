"""Finance fundraise specialist — investor deck financials, SAFE/priced round terms, target investor list, pitch narrative, outreach one-pager."""
import functools
import re as _re

from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read
from backend.tools.web_search import web_search
from backend.tools.pdf_generator import generate_pdf
from backend.tools.doc_generator import format_legal_document


def _make_auto_logging_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "finance_fundraise"):
    """Wrap a research tool so every result is auto-logged to Obsidian."""
    @functools.wraps(tool_fn)
    def wrapper(*args, **kwargs):
        result = tool_fn(*args, **kwargs)
        ctx: AgentContext | None = ctx_holder[0] if ctx_holder else None
        if ctx is None:
            return result

        heading = args[0] if args else kwargs.get("query") or kwargs.get("url") or tool_name

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


_FUNDRAISE_SEARCH_SEQUENCE = (
    "FUNDRAISING RESEARCH — run these 5 searches in order (replace {topic} with the actual subject):\n"
    "1. search_and_fetch('{topic} startup seed funding round 2024 2025 raise amount SAFE valuation cap')\n"
    "2. search_and_fetch('{topic} venture capital investors VCs active seed Series A 2024 2025')\n"
    "3. search_and_fetch('{topic} VC fund portfolio investments recent 2024 2025 crunchbase angellist')\n"
    "4. search_and_fetch('{topic} competitor funding raised investors lead 2024 2025')\n"
    "5. search_and_fetch('YC SAFE post-money valuation cap standard terms discount rate 2024 2025')\n\n"
    "Then fetch_and_read on 1-2 of the most relevant VC firm pages found above "
    "(skip if search results already contain enough investor data).\n\n"
    "IMPORTANT: After completing research, immediately move to deliverables. "
    "Do NOT run more than 7 tool calls total in the research phase.\n\n"
    "ANALYSIS & DELIVERABLES (complete all 5 in order):\n\n"
    "A. RAISE RECOMMENDATION\n"
    "   - Recommend raise amount (in USD) with reasoning (runway target, hiring plan, milestones to next round).\n"
    "   - Recommend instrument: SAFE (if pre-revenue or seed) or priced round (if Series A+ with meaningful ARR).\n"
    "   - If SAFE: recommend valuation cap, discount rate (standard 20%), MFN clause (yes/no), pro-rata rights.\n"
    "   - If priced: recommend pre-money valuation, share price, liquidation preference, participating preferred (yes/no).\n\n"
    "B. TARGET INVESTOR LIST (8-12 investors)\n"
    "   Build a list of 8-12 VCs and angels actively investing in this space from your research. For each include:\n"
    "   - Fund/investor name\n"
    "   - Check size range\n"
    "   - Stage focus (pre-seed / seed / Series A)\n"
    "   - Why they're a fit (portfolio companies, stated thesis, partner focus areas)\n"
    "   - Website or contact page URL\n"
    "   Use only real investor names confirmed via search results.\n\n"
    "C. PITCH NARRATIVE (write all 5 sections in full prose):\n"
    "   1. PROBLEM — what pain exists, who feels it, why it's urgent and expensive now\n"
    "   2. SOLUTION — what the product does, key differentiators, unfair advantages\n"
    "   3. MARKET — TAM/SAM/SOM with sourced numbers, growth rate, why now\n"
    "   4. TRACTION — current metrics, customers, revenue, growth rate, key milestones hit\n"
    "   5. ASK — raise amount, use of funds breakdown (% to eng / sales / ops / runway), milestones this round funds\n\n"
    "D. SAFE TERMS SUMMARY\n"
    "   Draft a plain-English SAFE terms summary (not legal advice) covering: instrument type, valuation cap, "
    "   discount rate, conversion trigger, MFN clause, pro-rata rights, side letter considerations.\n"
    "   Call format_legal_document(doc_type='SAFE Terms Summary', company_name=<company>, content=<terms text>).\n\n"
    "E. INVESTOR ONE-PAGER PDF\n"
    "   Call generate_pdf(title='[Company] Investor One-Pager', sections=[...]) with sections:\n"
    "   - Executive Summary (2-3 sentences: what, who, why now)\n"
    "   - Problem & Solution\n"
    "   - Market Opportunity (TAM/SAM/SOM)\n"
    "   - Traction & Metrics\n"
    "   - Business Model\n"
    "   - The Ask (raise amount, instrument, use of funds)\n"
    "   - Target Milestones (what this round funds)\n"
    "   - Team\n"
    "   - Contact\n\n"
    "FINAL STEP: Call obsidian_log(agent='finance_fundraise', session_id=<SESSION_ID>, "
    "summary='<brief summary of raise recommendation and PDF path>', founder_id=<FOUNDER_ID>).\n\n"
    "After obsidian_log completes, immediately call done with output: "
    "{raise_amount, instrument, valuation_cap, investor_list, pitch_narrative_summary, safe_terms_path, pdf_path}.\n\n"
    "CRITICAL: You MUST call done before iteration 28. Do not loop on research — 5 searches is enough."
)


def build_finance_fundraise_agent(**kwargs) -> Agent:
    """Build the finance_fundraise specialist agent.

    Prepares a complete fundraising package: raise amount and instrument recommendation,
    SAFE terms summary, curated target investor list (8-12 VCs/angels found via web search),
    pitch narrative (problem/solution/market/traction/ask), and investor outreach one-pager PDF.
    """
    agent_name = "finance_fundraise"

    # Use planner model for deeper reasoning on financial/narrative tasks
    for k in ("model", "model_base_url", "model_api_key"):
        kwargs.pop(k, None)

    ctx_holder: list = [None]

    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_web = _make_auto_logging_tool(web_search, "web_search", ctx_holder, log_name)

    from backend.config import settings

    agent = Agent(
        name=agent_name,
        model=settings.or_highoutput_model,
        model_base_url=settings.openrouter_base_url,
        model_api_key=settings.openrouter_api_key or settings.agent_model_api_key,
        max_iterations=20,  # ling-2.6-flash is fast/reliable in production — 25 was oversized headroom
        role=(
            "You are an elite fundraising preparation specialist. Your ONLY domain is the fundraising package — "
            "investor research, round sizing, SAFE/priced round terms, pitch narrative, and investor one-pager. "
            "NOT financial modeling or P&L projections (finance_model), "
            "NOT pitch decks for sales deals (sales_enablement), NOT Stripe/pricing setup (revenue_ops).\n\n"
            "You help founders raise capital by "
            "producing investment-grade fundraising packages: raise amount and instrument recommendation, "
            "SAFE terms summary, curated investor list, compelling pitch narrative, and a polished one-pager PDF.\n\n"
            "TOOLS:\n"
            "- search_and_fetch(query) — search + fetch full content from multiple sites. PRIMARY research tool.\n"
            "- fetch_and_read(url) — read a specific URL in full depth (VC fund pages, Crunchbase profiles).\n"
            "- web_search(query) — broad web search for active investors and market data.\n"
            "- format_legal_document(doc_type, company_name, content) — format SAFE terms summary as a document.\n"
            "- generate_pdf(title, sections) — produce the investor one-pager PDF. REQUIRED final output.\n"
            "- obsidian_log — log all findings after research and deliverables are complete.\n"
            "- obsidian_read — read prior research or context from Obsidian.\n"
            "- obsidian_append — append intermediate findings during research.\n\n"
            "Always produce concrete, specific outputs. Use real investor names and fund names from search results. "
            "Never fabricate VC names — only include investors confirmed via search. "
            "If any tool fails, use obsidian_log as fallback and continue to produce all other deliverables. "
            "Do not describe what should be done — do it.\n\n"
            "YOUR MANDATORY RESEARCH & DELIVERABLE SEQUENCE:\n\n"
            + _FUNDRAISE_SEARCH_SEQUENCE
        ),
        tools={
            "search_and_fetch": auto_search,
            "fetch_and_read": auto_fetch,
            "web_search": auto_web,
            "format_legal_document": format_legal_document,
            "generate_pdf": generate_pdf,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )

    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

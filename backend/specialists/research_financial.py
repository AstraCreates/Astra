"""Financial research specialist — unit economics benchmarks, fundraising comps, burn rate norms, revenue multiples, investor return expectations."""
import functools
import re as _re

from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read, deep_research, sonar_research
from backend.tools.web_search import web_search, news_search
from backend.tools.pdf_generator import generate_pdf


def _make_auto_logging_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "research_financial"):
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


_FINANCIAL_SEARCH_SEQUENCE = (
    "FINANCIAL BENCHMARKS RESEARCH:\n"
    "1. deep_research([\n"
    "     '{topic} unit economics CAC LTV payback period benchmark 2025',\n"
    "     '{topic} burn rate monthly cash burn benchmark seed Series A startup',\n"
    "     '{topic} ARR revenue multiple valuation SaaS B2B 2025',\n"
    "     '{topic} fundraising rounds seed Series A valuation 2024 2025 Crunchbase',\n"
    "     '{topic} investor return expectations IRR MOIC venture capital',\n"
    "     '{topic} gross margin net margin operating expenses benchmark',\n"
    "     '{topic} NRR net revenue retention ARR growth rate benchmark',\n"
    "     '{topic} Rule of 40 magic number sales efficiency benchmark',\n"
    "   ]) — deep_research fetches and synthesizes authoritative sources internally.\n"
    "2. web_search('{topic} recent funding rounds investors Series A 2024 2025')\n"
    "3. news_search('{topic} funding raised valuation 2025')\n"
    "4. Use fetch_and_read only for specific Bessemer/OpenView/a16z/PitchBook report URLs sonar could not fully read.\n\n"
    "FINAL STEPS (in order):\n"
    "A. obsidian_log with sections: UNIT ECONOMICS (CAC, LTV, LTV:CAC, payback period), "
    "BURN & RUNWAY NORMS, REVENUE MULTIPLES & VALUATION, FUNDRAISING COMPS (recent rounds, investors, "
    "check sizes), INVESTOR RETURN EXPECTATIONS (IRR, MOIC, ownership targets), KEY BENCHMARKS SUMMARY.\n"
    "B. generate_pdf — compile all findings into a structured Financial Benchmarks PDF with the sections above.\n"
    "C. Call done with output containing: summary (2-3 sentence recap), key_benchmarks (dict of the most important numbers found), pdf_path (from generate_pdf result), sources (list of URLs cited)."
)


def build_research_financial_agent(**kwargs) -> Agent:
    """Build the research_financial specialist agent.

    Researches unit economics benchmarks (CAC, LTV, payback period),
    fundraising comparables, burn rate norms, revenue multiples, and
    investor return expectations for the target industry, then produces
    a financial benchmarks PDF.
    """
    agent_name = "research_financial"

    ctx_holder: list = [None]

    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_sonar = _make_auto_logging_tool(sonar_research, "sonar_research", ctx_holder, log_name)
    auto_web = _make_auto_logging_tool(web_search, "web_search", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder, log_name)

    kwargs.setdefault("max_tool_calls", {
        "deep_research": 2, "search_and_fetch": 1, "fetch_and_read": 2,
        "web_search": 2, "news_search": 2, "obsidian_read": 1, "obsidian_log": 1,
    })

    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    model = kwargs.pop("model", settings.research_agent_model)
    model_base_url = kwargs.pop("model_base_url", settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", get_openrouter_key() or settings.agent_model_api_key)

    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=25,
        role=(
            "You are an elite financial research specialist. Your ONLY domain is quantitative financial benchmarks — "
            "CAC/LTV ratios, SaaS ARR multiples, burn rate norms, funding round sizing, and investor return expectations. "
            "NOT market opportunity sizing (research), NOT competitor profiling (research_competitors), "
            "NOT regulatory mapping (research_regulatory). "
            "You extract precise, cited numbers — not vague ranges — from authoritative sources "
            "(Bessemer Venture Partners, OpenView, a16z, NFX, SaaStr, Crunchbase, PitchBook, "
            "CB Insights, Meritech Capital public comps, and primary investor blogs).\n\n"
            "TOOLS:\n"
            "- deep_research(queries) — PRIMARY tool. List of questions → synthesized cited answers. Replaces search_and_fetch + fetch_and_read loops.\n"
            "- sonar_research(queries) — compatibility alias for deep_research.\n"
            "- fetch_and_read(url) — read a specific URL in full depth (only for paywalled reports deep_research missed).\n"
            "- web_search(query) — broad web search for recent data.\n"
            "- news_search(query) — recent news and announcements.\n"
            "- obsidian_log — log structured findings after ALL searches complete.\n"
            "- generate_pdf(title, sections) — produce the final Financial Benchmarks PDF.\n\n"
            "YOUR MANDATORY SEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + _FINANCIAL_SEARCH_SEQUENCE
        ),
        tools={
            "deep_research": auto_sonar,
            "sonar_research": auto_sonar,
            "search_and_fetch": auto_search,
            "fetch_and_read": auto_fetch,
            "web_search": auto_web,
            "news_search": auto_news,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "generate_pdf": generate_pdf,
        },
        **kwargs,
    )

    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

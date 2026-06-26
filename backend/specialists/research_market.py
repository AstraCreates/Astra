"""Market research specialist — TAM/SAM/SOM sizing, ICP definition, pricing benchmarks, and market opportunity framing."""
import functools
import re as _re
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read, sonar_research
from backend.tools.web_search import web_search, news_search


def _make_auto_logging_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "research_market"):
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


_MARKET_RESEARCH_SEARCHES = (
    "MARKET SIZING & ICP RESEARCH:\n"
    "1. sonar_research([\n"
    "     '{topic} total addressable market TAM SAM SOM size 2025 billion statistics',\n"
    "     '{topic} market size growth rate CAGR forecast 2025 2026 2027 2030',\n"
    "     '{topic} industry report grand view mordor ibisworld statista market research',\n"
    "     '{topic} target customer ICP demographics firmographics buyer persona',\n"
    "     '{topic} pricing model subscription tiers enterprise SMB cost benchmark 2025',\n"
    "     '{topic} competitor pricing how much does it cost per user per month',\n"
    "     '{topic} willingness to pay price sensitivity customer survey',\n"
    "     '{topic} market opportunity whitespace unmet need underserved segment',\n"
    "   ]) — sonar fetches and synthesizes sources internally, no separate URL fetching needed.\n"
    "2. news_search('{topic} market growth investment funding opportunity 2025 2026')\n"
    "3. Use fetch_and_read only for specific analyst report URLs or paywalled pages sonar could not fully read.\n\n"
    "obsidian_log with ALL of the following sections:\n"
    "- TAM: total addressable market with dollar figure, source, and methodology\n"
    "- SAM: serviceable addressable market with rationale for how it narrows from TAM\n"
    "- SOM: serviceable obtainable market for year 1-3 with assumptions\n"
    "- GROWTH RATE: CAGR, key growth drivers, headwinds\n"
    "- ICP DEFINITION: demographics, firmographics, psychographics, job titles, company size, geography\n"
    "- BUYING TRIGGERS: what prompts the ICP to buy, urgency signals, decision-making process\n"
    "- PRICING BENCHMARKS: competitor pricing tiers (free/starter/pro/enterprise), price per seat/month, "
    "packaging patterns, and recommended price positioning\n"
    "- MARKET OPPORTUNITY SUMMARY: 2-3 sentence pitch-ready framing of the opportunity with numbers\n"
    "- DATA SOURCES: citations for all statistics used\n\n"
    "After obsidian_log completes, call done with output containing: "
    "summary (2-3 sentence market opportunity recap with numbers), "
    "tam (dollar figure + source), sam (dollar figure + rationale), "
    "som (year-1 target + assumptions), cagr (growth rate), "
    "icp (ideal customer profile summary), pricing_benchmarks (key pricing data found), "
    "sources (list of URLs cited)."
)


def build_research_market_agent(**kwargs) -> Agent:
    """Build a market research specialist agent focused on TAM/SAM/SOM, ICP, pricing, and opportunity framing."""
    agent_name = "research_market"
    ctx_holder: list = [None]

    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder, log_name)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder, log_name)
    auto_sonar = _make_auto_logging_tool(sonar_research, "sonar_research", ctx_holder, log_name)
    auto_web = _make_auto_logging_tool(web_search, "web_search", ctx_holder, log_name)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder, log_name)

    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    model = kwargs.pop("model", settings.or_light_model)
    model_base_url = kwargs.pop("model_base_url", settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", get_openrouter_key() or settings.agent_model_api_key)
    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=40,
        role=(
            "You are an elite market research analyst. You produce investment-grade market sizing, "
            "ICP definitions, pricing benchmarks, and opportunity framing that founders use in pitch decks "
            "and go-to-market strategies. Be THOROUGH: run multiple search rounds and read 10-15 sources "
            "(analyst reports, primary data, competitor pages) so every output section is backed by hard "
            "numbers from named, cited sources.\n\n"
            "TOOLS:\n"
            "- sonar_research(queries) — PRIMARY tool. Pass a list of research questions; each returns a synthesized cited answer with sources. Replaces search_and_fetch + fetch_and_read loops.\n"
            "- fetch_and_read(url) — read a specific URL in full depth (only for paywalled reports sonar missed).\n"
            "- web_search(query) — targeted web search for specific facts or sources.\n"
            "- news_search(query) — recent news and market developments.\n"
            "- obsidian_log — FINAL step only, called once after ALL searches and fetches are complete.\n\n"
            "YOUR MANDATORY RESEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + _MARKET_RESEARCH_SEARCHES
        ),
        tools={
            "sonar_research": auto_sonar,
            "search_and_fetch": auto_search,
            "fetch_and_read": auto_fetch,
            "web_search": auto_web,
            "news_search": auto_news,
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

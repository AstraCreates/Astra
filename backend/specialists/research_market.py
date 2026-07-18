"""Market research specialist — TAM/SAM/SOM sizing, ICP definition, pricing benchmarks, and market opportunity framing."""
import functools
import re as _re
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import build_research_queries, run_research_pipeline


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
    "1. build_research_queries(topic='{topic}', focus='market') for focused query planning.\n"
    "2. run_research_pipeline(topic='{topic}', focus='market') for native-search evidence, coverage status, and citations.\n"
    "3. If coverage.ready is false, make one refined run_research_pipeline call, then synthesize with uncertainty clearly marked.\n\n"
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
    "pricing_benchmarks (key pricing data found), "
    "sources (list of URLs cited)."
)


def build_research_market_agent(**kwargs) -> Agent:
    """Build a market research specialist agent focused on TAM/SAM/SOM, ICP, pricing, and opportunity framing."""
    agent_name = "research_market"
    ctx_holder: list = [None]

    log_name = _re.sub(r"_\d+$", "", agent_name)
    auto_pipeline = _make_auto_logging_tool(run_research_pipeline, "run_research_pipeline", ctx_holder, log_name)
    auto_queries = _make_auto_logging_tool(build_research_queries, "build_research_queries", ctx_holder, log_name)

    kwargs.setdefault("max_tool_calls", {
        "run_research_pipeline": 2, "build_research_queries": 1, "obsidian_read": 1, "obsidian_log": 1,
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
        max_iterations=25,  # ling-2.6-flash is fast/reliable in production — 40 was oversized headroom
        role=(
            "You are an elite market research analyst. You produce investment-grade market sizing, "
            "ICP definitions, pricing benchmarks, and opportunity framing that founders use in pitch decks "
            "and go-to-market strategies. Be thorough, but prefer concise evidence: run targeted search rounds and read only as many sources as needed "
            "(analyst reports, primary data, competitor pages) so every output section is backed by hard "
            "numbers from named, cited sources.\n\n"
            "TOOLS:\n"
            "- run_research_pipeline(topic, focus) — PRIMARY native-search research pass with typed coverage and citations.\n"
            "- build_research_queries(topic, focus) — create a focused query plan only when the topic needs refinement.\n"
            "- obsidian_log — FINAL step only, called once after ALL searches and fetches are complete.\n\n"
            "YOUR MANDATORY RESEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + _MARKET_RESEARCH_SEARCHES
        ),
        tools={
            "run_research_pipeline": auto_pipeline,
            "build_research_queries": auto_queries,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
        },
        **kwargs,
    )

    _original_run = agent.run

    async def _patched_run(ctx: AgentContext):
        ctx_holder[0] = ctx
        return await _original_run(ctx)

    agent.run = _patched_run
    return agent

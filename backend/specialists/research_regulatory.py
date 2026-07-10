"""Research Regulatory specialist — compliance, licensing, and legal risk research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read, deep_research, sonar_research
from backend.tools.web_search import web_search, news_search
from backend.tools.patent_search import patent_search
from backend.tools.pdf_generator import generate_pdf


def _make_auto_logging_tool(tool_fn, tool_name: str, ctx_holder: list, agent_name: str = "research_regulatory"):
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


_REGULATORY_SEARCHES = (
    "REGULATORY & COMPLIANCE RESEARCH:\n"
    "1. deep_research([\n"
    "     '{topic} regulatory requirements compliance 2025',\n"
    "     '{topic} GDPR CCPA data privacy compliance requirements',\n"
    "     '{topic} HIPAA SOC2 ISO27001 compliance requirements',\n"
    "     '{topic} industry-specific regulations federal state licensing',\n"
    "     '{topic} legal risks liability exposure startup',\n"
    "     '{topic} FTC FCC SEC FDA regulatory oversight enforcement',\n"
    "     '{topic} international regulations EU UK APAC compliance',\n"
    "   ]) — deep_research fetches government sites and legal publishers internally.\n"
    "2. news_search('{topic} regulatory enforcement fine penalty 2024 2025')\n"
    "3. web_search('{topic} compliance framework checklist requirements')\n"
    "4. patent_search('{topic} regulatory technology compliance')\n"
    "5. Use fetch_and_read only for specific government/official body URLs sonar could not fully read. Max 3 calls.\n\n"
    "IMMEDIATELY AFTER the fetches, call generate_pdf BEFORE obsidian_log:\n"
    "generate_pdf(title='Regulatory Risk Report', sections=[{\"heading\": \"APPLICABLE REGULATIONS\", \"body\": \"...\"}, {\"heading\": \"DATA PRIVACY REQUIREMENTS\", \"body\": \"...\"}, {\"heading\": \"RISK FLAGS\", \"body\": \"...\"}, {\"heading\": \"RECOMMENDED ACTIONS\", \"body\": \"...\"}])\n\n"
    "Then obsidian_log with a structured RISK FLAG REPORT containing:\n"
    "- APPLICABLE REGULATIONS (name, jurisdiction, key requirements, penalty exposure)\n"
    "- DATA PRIVACY REQUIREMENTS (GDPR, CCPA, HIPAA — what applies, what's needed)\n"
    "- LICENSING & PERMITS (required licenses, certifications, timelines, costs)\n"
    "- INDUSTRY-SPECIFIC RULES (sector regulator, specific mandates)\n"
    "- INTERNATIONAL COMPLIANCE (key cross-border obligations)\n"
    "- RISK FLAGS (HIGH / MEDIUM / LOW — specific legal risks with rationale)\n"
    "- RECOMMENDED ACTIONS (prioritized compliance roadmap for a startup)\n\n"
    "Then call done with the structured output."
)


def build_research_regulatory_agent(**kwargs) -> Agent:
    """Build the regulatory & compliance research specialist agent."""
    ctx_holder: list = [None]

    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder)
    auto_sonar = _make_auto_logging_tool(sonar_research, "sonar_research", ctx_holder)
    auto_web = _make_auto_logging_tool(web_search, "web_search", ctx_holder)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder)

    kwargs.setdefault("max_tool_calls", {
        "deep_research": 2, "search_and_fetch": 1, "fetch_and_read": 2,
        "web_search": 2, "news_search": 2, "patent_search": 1,
        "obsidian_read": 1, "obsidian_log": 1,
    })

    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    model = kwargs.pop("model", settings.research_agent_model)
    model_base_url = kwargs.pop("model_base_url", settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", get_openrouter_key() or settings.agent_model_api_key)

    agent = Agent(
        name="research_regulatory",
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        max_iterations=25,
        role=(
            "You are an elite regulatory and compliance research specialist. "
            "Your ONLY job is mapping the REGULATORY RISK LANDSCAPE — which regulations apply, what they require, "
            "and the legal risk exposure of the business model. "
            "NOT implementing compliance programmes (legal_compliance), NOT drafting contracts (legal_contracts), "
            "NOT entity formation (legal_entity). "
            "You think like a compliance attorney combined with a startup risk advisor.\n\n"
            "TOOLS:\n"
            "- deep_research(queries) — PRIMARY tool. List of questions → synthesized cited answers from authoritative sources. Replaces search_and_fetch + fetch_and_read loops.\n"
            "- sonar_research(queries) — compatibility alias for deep_research.\n"
            "- fetch_and_read(url) — read a specific URL (only for official government/legal sources deep_research missed, max 3).\n"
            "- web_search(query) — targeted web search.\n"
            "- news_search(query) — recent regulatory enforcement news.\n"
            "- patent_search(query) — IP and regtech landscape.\n"
            "- generate_pdf(title, sections) — produce a shareable PDF risk report. sections must be a JSON array of objects with 'heading' and 'body' keys, e.g. [{\"heading\": \"GDPR Requirements\", \"body\": \"...\"}]\n"
            "- obsidian_log — FINAL step after ALL searches and PDF generation.\n\n"
            "YOUR MANDATORY SEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + _REGULATORY_SEARCHES
        ),
        tools={
            "deep_research": auto_sonar,
            "sonar_research": auto_sonar,
            "search_and_fetch": auto_search,
            "fetch_and_read": auto_fetch,
            "web_search": auto_web,
            "news_search": auto_news,
            "patent_search": auto_patent,
            "generate_pdf": generate_pdf,
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

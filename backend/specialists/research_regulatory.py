"""Research Regulatory specialist — compliance, licensing, and legal risk research."""
import functools
from backend.core.agent import Agent, AgentContext
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.browser_research import search_and_fetch, fetch_and_read
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
    "REGULATORY & COMPLIANCE RESEARCH (run ALL 12):\n"
    "1. search_and_fetch('{topic} regulatory requirements compliance 2024 2025')\n"
    "2. search_and_fetch('{topic} GDPR data privacy compliance requirements')\n"
    "3. search_and_fetch('{topic} HIPAA SOC2 ISO27001 compliance requirements')\n"
    "4. search_and_fetch('{topic} industry specific regulations federal state')\n"
    "5. search_and_fetch('{topic} licensing requirements permits certifications')\n"
    "6. search_and_fetch('{topic} legal risks liability exposure startup')\n"
    "7. search_and_fetch('{topic} FTC FCC SEC FDA regulatory oversight enforcement')\n"
    "8. search_and_fetch('{topic} international regulations EU UK APAC compliance')\n"
    "9. search_and_fetch('{topic} terms of service privacy policy requirements')\n"
    "10. news_search('{topic} regulatory enforcement fine penalty 2024 2025')\n"
    "11. web_search('{topic} compliance framework checklist requirements')\n"
    "12. patent_search('{topic} regulatory technology compliance')\n\n"
    "Then 3 fetch_and_read calls on the most authoritative regulatory sources found "
    "(government sites, official bodies, legal publishers). Do NOT do more than 3 fetch_and_read calls.\n\n"
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
    # Strip model overrides — always uses planner model
    for k in ("model", "model_base_url", "model_api_key"):
        kwargs.pop(k, None)

    ctx_holder: list = [None]

    auto_search = _make_auto_logging_tool(search_and_fetch, "search_and_fetch", ctx_holder)
    auto_fetch = _make_auto_logging_tool(fetch_and_read, "fetch_and_read", ctx_holder)
    auto_web = _make_auto_logging_tool(web_search, "web_search", ctx_holder)
    auto_news = _make_auto_logging_tool(news_search, "news_search", ctx_holder)
    auto_patent = _make_auto_logging_tool(patent_search, "patent_search", ctx_holder)

    from backend.config import settings

    agent = Agent(
        name="research_regulatory",
        model="deepseek-ai/DeepSeek-V4-Flash",
        model_base_url=settings.agent_model_base_url,
        model_api_key=settings.agent_model_api_key,
        max_iterations=25,
        role=(
            "You are an elite regulatory and compliance research specialist. "
            "Your job is to identify every regulation, licensing requirement, data privacy obligation, "
            "and legal risk that applies to a given business idea or industry. "
            "You think like a compliance attorney combined with a startup risk advisor.\n\n"
            "TOOLS:\n"
            "- search_and_fetch(query) — searches + fetches full content. PRIMARY tool.\n"
            "- fetch_and_read(url) — read a specific URL in full depth.\n"
            "- web_search(query) — targeted web search.\n"
            "- news_search(query) — recent regulatory enforcement news.\n"
            "- patent_search(query) — IP and regtech landscape.\n"
            "- generate_pdf(title, sections) — produce a shareable PDF risk report. sections must be a JSON array of objects with 'heading' and 'body' keys, e.g. [{\"heading\": \"GDPR Requirements\", \"body\": \"...\"}]\n"
            "- obsidian_log — FINAL step after ALL searches and PDF generation.\n\n"
            "YOUR MANDATORY SEARCH SEQUENCE (replace {topic} with the actual subject):\n\n"
            + _REGULATORY_SEARCHES
        ),
        tools={
            "search_and_fetch": auto_search,
            "fetch_and_read": auto_fetch,
            "web_search": auto_web,
            "news_search": auto_news,
            "patent_search": auto_patent,
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

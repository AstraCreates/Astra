"""Research docs writer — turns the raw findings the research lanes already
gathered and stored into the founder-facing market_brief/icp_brief/
pricing_hypothesis deliverables.

Split out from the research lanes deliberately: those agents' job is to gather
and store evidence (and escalate to the founder via ask_user when something
needs a decision), not to also author three polished documents before
downstream agents (design/web/technical/marketing/sales/legal) are allowed to
start. Those agents already only depend on the research lanes finishing their
data-gathering (see StackTaskTemplate depends_on=["t_research"] in
templates.py), so this agent runs in parallel with them once research is
done, reading each lane's full result via the task dependency brief the
orchestrator already injects (dep_results / _build_task_brief) rather than
re-fetching anything itself.
"""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read
from backend.tools.pdf_generator import generate_pdf


def build_research_docs_agent(**kwargs) -> Agent:
    agent_name = "research_docs"

    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    model = kwargs.pop("model", settings.research_agent_model)
    model_base_url = kwargs.pop("model_base_url", settings.openrouter_base_url)
    model_api_key = kwargs.pop("model_api_key", get_openrouter_key() or settings.agent_model_api_key)
    kwargs.setdefault("max_iterations", 20)
    kwargs.setdefault("max_tool_calls", {"generate_pdf": 3, "obsidian_log": 3, "obsidian_read": 2})

    agent = Agent(
        name=agent_name,
        model=model,
        model_base_url=model_base_url,
        model_api_key=model_api_key,
        role=(
            "You are the research documentation specialist. The research lanes (market, "
            "competitors, customers, GTM) have already gathered and stored their findings -- "
            "your task brief above contains their full results. You do not do any research "
            "of your own; you synthesize what they already found into three founder-facing "
            "documents, each backed by the concrete evidence (named companies, numbers, "
            "dates, sources) the research lanes already cited. If the research findings are "
            "too thin or contradictory to write a real document, say so plainly in that "
            "document rather than inventing specifics.\n\n"
            "PRODUCE THREE DOCUMENTS via generate_pdf, each with real section content (not "
            "placeholder text):\n"
            "1. market_brief — market size (TAM/SAM/SOM if the research found figures), "
            "category, growth trends, and validation signals.\n"
            "2. icp_brief — target customer, their pain, the buying trigger, likely "
            "objections, and the buying process.\n"
            "3. pricing_hypothesis — initial packaging and pricing rationale grounded in "
            "the competitor pricing and willingness-to-pay evidence research found.\n\n"
            "For each: generate_pdf(title=..., filename=..., sections=[{heading, body}, ...]) "
            "then obsidian_log the same content so it's saved to company memory.\n\n"
            "When all three are written, call done with output containing: "
            "market_brief (path + 2-3 sentence summary), icp_brief (path + summary), "
            "pricing_hypothesis (path + summary)."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
        },
        **kwargs,
    )
    return agent

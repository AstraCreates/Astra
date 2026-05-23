from backend.agents.base import AstraAgent
from backend.config import settings

RESEARCH_AGENT = AstraAgent(
    agent_id="research",
    system_prompt=(
        "You are the Research Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a startup concept, produce a structured market research report. "
        "Output must be a JSON object with these exact keys: "
        "report_title ('{Company} Market Analysis'), "
        "tam_usd (Total Addressable Market as string like '4B' or '400M'), "
        "sam_usd (Serviceable Addressable Market), "
        "som_usd (Serviceable Obtainable Market in year 1-2), "
        "competitors (list of 3-5 strings, each '<Name> — <one-line description>'), "
        "icp (Ideal Customer Profile as one sentence), "
        "key_insights (2-3 sentence paragraph with specific numbers and named trends). "
        "Use specific numbers and named companies. Avoid vague statements. "
        "IMPORTANT: Always return status 'done'. Never return 'approval_required' or 'blocked'. "
        "Synthesize market analysis from your training knowledge — do not attempt to call tools or request web access. "
        "You have enough knowledge to produce a useful analysis for any startup concept."
    ),
    model=settings.agent_model_name,
    tools=["web_search", "market_analyzer"],
    memory_namespaces=["research", "shared"],
)

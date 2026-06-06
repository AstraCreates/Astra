from backend.specialists.marketing_outreach import build_marketing_outreach_agent
from backend.specialists.research import build_research_agent
from backend.specialists.research_financial import build_research_financial_agent
from backend.specialists.research_market import build_research_market_agent
from backend.specialists.research_regulatory import build_research_regulatory_agent
from backend.specialists.sales import build_sales_agent
from backend.specialists.sales_pipeline import build_sales_pipeline_agent


def test_research_and_small_cycle_agents_accept_mimo_routing():
    kwargs = {
        "model": "xiaomi/mimo-v2.5",
        "model_base_url": "https://openrouter.ai/api/v1",
        "model_api_key": "test",
    }

    agents = [
        build_research_agent(**kwargs),
        build_research_agent(agent_name="research_competitors", **kwargs),
        build_research_agent(agent_name="research_execution", **kwargs),
        build_research_market_agent(**kwargs),
        build_research_financial_agent(**kwargs),
        build_research_regulatory_agent(**kwargs),
        build_sales_agent(**kwargs),
        build_sales_pipeline_agent(**kwargs),
        build_marketing_outreach_agent(**kwargs),
    ]

    assert {agent.model for agent in agents} == {"xiaomi/mimo-v2.5"}

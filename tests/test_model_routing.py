from backend.config import settings
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


def test_research_defaults_to_ling_on_openrouter_even_when_local_endpoint_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "research_default_provider", "openrouter")
    monkeypatch.setattr(settings, "local_research_base_url", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "local_research_model", "qwen-local")
    monkeypatch.setattr(settings, "research_agent_model", "inclusionai/ling-2.6-flash")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")

    agent = build_research_agent()

    assert agent.model == "inclusionai/ling-2.6-flash"
    assert agent._model_base_url == "https://openrouter.ai/api/v1"


def test_research_can_still_opt_into_local_default(monkeypatch):
    monkeypatch.setattr(settings, "research_default_provider", "local")
    monkeypatch.setattr(settings, "local_research_base_url", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "local_research_model", "qwen-local")

    agent = build_research_agent()

    assert agent.model == "qwen-local"
    assert agent._model_base_url == "http://localhost:1234/v1"


def test_research_lanes_have_bounded_closed_tool_surface():
    for name in ("research_competitors", "research_customers", "research_gtm", "research_market", "research_financial", "research_regulatory"):
        agent = build_research_agent(agent_name=name, model="inclusionai/ling-2.6-flash")
        assert "obsidian_append" not in agent.tools
        assert "company_brain_search" not in agent.tools
        assert "search_examples" not in agent.tools
        assert agent._max_tool_calls["obsidian_read"] == 1
        assert agent._max_tool_calls["obsidian_log"] == 1

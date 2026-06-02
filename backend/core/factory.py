"""
Builds the live Orchestrator with all specialists and the planner agent.
Called once at startup; cached as a module-level singleton.
"""
from backend.core.agent import Agent
from backend.core.orchestrator import Orchestrator
from backend.config import settings
from backend.specialists.research import build_research_agent
from backend.specialists.web import build_web_agent
from backend.specialists.marketing import build_marketing_agent
from backend.specialists.technical import build_technical_agent
from backend.specialists.legal import build_legal_agent
from backend.specialists.ops import build_ops_agent
from backend.specialists.sales import build_sales_agent
from backend.specialists.design import build_design_agent
from backend.specialists.research_market import build_research_market_agent
from backend.specialists.research_financial import build_research_financial_agent
from backend.specialists.research_regulatory import build_research_regulatory_agent
from backend.specialists.legal_docs import build_legal_docs_agent
from backend.specialists.legal_entity import build_legal_entity_agent
from backend.specialists.legal_ip import build_legal_ip_agent
from backend.specialists.marketing_content import build_marketing_content_agent
from backend.specialists.marketing_outreach import build_marketing_outreach_agent
from backend.specialists.marketing_seo import build_marketing_seo_agent
from backend.specialists.marketing_paid import build_marketing_paid_agent
from backend.specialists.sales_pipeline import build_sales_pipeline_agent
from backend.specialists.sales_enablement import build_sales_enablement_agent
from backend.specialists.technical_scaffold import build_technical_scaffold_agent
from backend.specialists.technical_infra import build_technical_infra_agent
from backend.specialists.technical_data import build_technical_data_agent
from backend.specialists.finance_model import build_finance_model_agent
from backend.specialists.finance_fundraise import build_finance_fundraise_agent

_orchestrator: Orchestrator | None = None


def reload_model_overrides() -> None:
    """Invalidate the orchestrator singleton so it is rebuilt with new model settings on next call."""
    global _orchestrator
    _orchestrator = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _coder_kwargs = dict(
            model="deepseek-ai/DeepSeek-V4-Flash",
            model_base_url=settings.planner_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        _highoutput_kwargs = dict(
            model=settings.highoutput_model_name,
            model_base_url=settings.highoutput_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        _small_kwargs = dict(
            model="meta-llama/Llama-4-Scout-17B-16E-Instruct",
            model_base_url=settings.agent_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        # research_financial/regulatory need 1M ctx to handle large research dumps
        _large_ctx_kwargs = dict(
            model="deepseek-ai/DeepSeek-V4-Flash",
            model_base_url=settings.agent_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        specialists = {
            # Research — Llama-4-Scout (fast, 320k ctx, good synthesis)
            "research": build_research_agent(agent_name="research", use_computer=True),
            "research_competitors": build_research_agent(agent_name="research_competitors", use_computer=True),
            "research_execution": build_research_agent(agent_name="research_execution", use_computer=True),
            "research_market": build_research_market_agent(use_computer=True),
            # Financial/regulatory research needs 1M ctx for large data dumps
            "research_financial": build_research_financial_agent(use_computer=True, **_large_ctx_kwargs),
            "research_regulatory": build_research_regulatory_agent(use_computer=True, **_large_ctx_kwargs),
            # Code agents — DeepSeek-V4-Flash (1M ctx, strong at code)
            "web": build_web_agent(use_computer=True, **_coder_kwargs),
            "technical": build_technical_agent(use_computer=True, **_coder_kwargs),
            "technical_scaffold": build_technical_scaffold_agent(use_computer=True, **_coder_kwargs),
            "technical_infra": build_technical_infra_agent(use_computer=True, **_coder_kwargs),
            "technical_data": build_technical_data_agent(use_computer=True, **_coder_kwargs),
            # Writing agents — Mistral-Small-3.2 ($0.075/$0.20, 125k ctx, great long-form)
            "marketing": build_marketing_agent(use_computer=True, **_highoutput_kwargs),
            "legal": build_legal_agent(use_computer=True, **_highoutput_kwargs),
            "ops": build_ops_agent(use_computer=True, **_highoutput_kwargs),
            "design": build_design_agent(use_computer=False, **_highoutput_kwargs),
            "legal_docs": build_legal_docs_agent(use_computer=True, **_highoutput_kwargs),
            "legal_entity": build_legal_entity_agent(use_computer=True, **_highoutput_kwargs),
            "legal_ip": build_legal_ip_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_content": build_marketing_content_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_outreach": build_marketing_outreach_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_seo": build_marketing_seo_agent(use_computer=True, max_tool_calls={"search_and_fetch": 3, "web_search": 5}, **_highoutput_kwargs),
            "marketing_paid": build_marketing_paid_agent(use_computer=True, max_tool_calls={"search_and_fetch": 4, "web_search": 6}, **_highoutput_kwargs),
            "sales_enablement": build_sales_enablement_agent(use_computer=False, **_highoutput_kwargs),
            "finance_model": build_finance_model_agent(use_computer=True, **_highoutput_kwargs),
            "finance_fundraise": build_finance_fundraise_agent(use_computer=True, **_highoutput_kwargs),
            # Simple task agents — Llama-4-Scout (fast, cheap)
            "sales": build_sales_agent(use_computer=False, max_iterations=15, **_small_kwargs),
            "sales_pipeline": build_sales_pipeline_agent(use_computer=False, **_small_kwargs),
        }
        from backend.tools.company_brain import (
            add_company_brain_record,
            ask_company_brain,
            company_brain_agent_context,
            configure_company_brain_sync,
            get_company_brain_sync_status,
            ingest_company_brain_records,
            maintain_company_brain,
            run_due_company_brain_syncs,
            run_company_brain_sync,
            search_company_brain,
            sync_company_brain,
        )
        from backend.tools.company_brain_connectors import (
            import_company_brain_source,
            import_company_brain_sources,
        )
        for agent in specialists.values():
            agent.tools.setdefault("company_brain_search", search_company_brain)
            agent.tools.setdefault("company_brain_sync", sync_company_brain)
            agent.tools.setdefault("company_brain_add_record", add_company_brain_record)
            agent.tools.setdefault("company_brain_ingest_records", ingest_company_brain_records)
            agent.tools.setdefault("company_brain_maintain", maintain_company_brain)
            agent.tools.setdefault("company_brain_agent_context", company_brain_agent_context)
            agent.tools.setdefault("company_brain_ask", ask_company_brain)
            agent.tools.setdefault("company_brain_configure_sync", configure_company_brain_sync)
            agent.tools.setdefault("company_brain_sync_status", get_company_brain_sync_status)
            agent.tools.setdefault("company_brain_run_sync", run_company_brain_sync)
            agent.tools.setdefault("company_brain_run_due_syncs", run_due_company_brain_syncs)
            agent.tools.setdefault("company_brain_import_source", import_company_brain_source)
            agent.tools.setdefault("company_brain_import_sources", import_company_brain_sources)
        planner = Agent(
            name="planner",
            role="planning coordinator. Decompose founder goals into specialist tasks scoped to each agent's actual capabilities.",
            tools={},
            sub_agents=list(specialists.values()),
            model=settings.planner_model_name,
            model_base_url=settings.planner_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        _orchestrator = Orchestrator(planner=planner, specialists=specialists)
    return _orchestrator

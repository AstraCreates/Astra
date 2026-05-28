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

_orchestrator: Orchestrator | None = None


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
        # Qwen3-235B for agents that must follow strict prompt rules
        _instruct_kwargs = dict(
            model="Qwen/Qwen3-32B",
            model_base_url=settings.agent_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        specialists = {
            "research": build_research_agent(agent_name="research", use_computer=True),
            "research_2": build_research_agent(agent_name="research_2", use_computer=True),
            "research_3": build_research_agent(agent_name="research_3", use_computer=True),
            "research_4": build_research_agent(agent_name="research_4", use_computer=True),
            "research_competitors": build_research_agent(agent_name="research_competitors", use_computer=True),
            "research_competitors_2": build_research_agent(agent_name="research_competitors_2", use_computer=True),
            "research_competitors_3": build_research_agent(agent_name="research_competitors_3", use_computer=True),
            "research_competitors_4": build_research_agent(agent_name="research_competitors_4", use_computer=True),
            "research_execution": build_research_agent(agent_name="research_execution", use_computer=True),
            "research_execution_2": build_research_agent(agent_name="research_execution_2", use_computer=True),
            "research_execution_3": build_research_agent(agent_name="research_execution_3", use_computer=True),
            "research_execution_4": build_research_agent(agent_name="research_execution_4", use_computer=True),
            "web": build_web_agent(use_computer=True, **_coder_kwargs),
            "marketing": build_marketing_agent(use_computer=True, **_highoutput_kwargs),
            "technical": build_technical_agent(use_computer=True, **_coder_kwargs),
            "legal": build_legal_agent(use_computer=True, **_highoutput_kwargs),
            "ops": build_ops_agent(use_computer=True, **_highoutput_kwargs),
            "sales": build_sales_agent(use_computer=False, **_coder_kwargs),
            "design": build_design_agent(use_computer=False, **_instruct_kwargs),
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

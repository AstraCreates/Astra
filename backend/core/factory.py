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
            model="Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo",
            model_base_url=settings.planner_model_base_url,
            model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
        )
        specialists = {
            "research": build_research_agent(use_computer=True),
            "web": build_web_agent(use_computer=True, **_coder_kwargs),
            "marketing": build_marketing_agent(use_computer=True),
            "technical": build_technical_agent(use_computer=True, **_coder_kwargs),
            "legal": build_legal_agent(use_computer=True),
            "ops": build_ops_agent(use_computer=True),
            "sales": build_sales_agent(use_computer=False),
            "design": build_design_agent(use_computer=False),
        }
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

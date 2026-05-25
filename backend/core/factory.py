"""
Builds the live Orchestrator with all specialists and the planner agent.
Called once at startup; cached as a module-level singleton.
"""
from backend.core.agent import Agent
from backend.core.orchestrator import Orchestrator
from backend.specialists.research import build_research_agent
from backend.specialists.web import build_web_agent
from backend.specialists.marketing import build_marketing_agent
from backend.specialists.technical import build_technical_agent
from backend.specialists.legal import build_legal_agent
from backend.specialists.ops import build_ops_agent

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        specialists = {
            "research": build_research_agent(use_computer=True),
            "web": build_web_agent(use_computer=True),
            "marketing": build_marketing_agent(use_computer=True),
            "technical": build_technical_agent(use_computer=True),
            "legal": build_legal_agent(use_computer=True),
            "ops": build_ops_agent(use_computer=True),
        }
        planner = Agent(
            name="planner",
            role="planning coordinator. Decompose founder goals into specialist tasks scoped to each agent's actual capabilities.",
            tools={},
            sub_agents=list(specialists.values()),
        )
        _orchestrator = Orchestrator(planner=planner, specialists=specialists)
    return _orchestrator

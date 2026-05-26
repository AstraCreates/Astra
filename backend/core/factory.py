"""
Builds the live Orchestrator with all specialists and the planner agent.
Called once at startup; cached as a module-level singleton.

Model assignments (all via DeepInfra OpenAI-compatible API):
  planner    — Kimi-K2.5        (strong planning/decomposition)
  research   — Step-3.5-Flash   (fast, low latency research)
  web        — Qwen3-Coder-480B (code generation + deployment)
  marketing  — Llama-4-Maverick (creative content, social copy)
  technical  — Qwen3-Coder-480B (scaffolding, PRs, infra)
  legal      — Kimi-K2.5        (careful multi-step drafting)
  ops        — Kimi-K2.5        (coordination, investor comms)
  sales      — Llama-4-Scout    (fast, good at lead/outreach)
  design     — Llama-4-Maverick (creative specs, wireframe briefs)
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

_DI_BASE = "https://api.deepinfra.com/v1/openai"


def _di(model: str) -> dict:
    """Kwargs for a DeepInfra-hosted model."""
    return dict(
        model=model,
        model_base_url=_DI_BASE,
        model_api_key=settings.deepinfra_api_key or settings.planner_model_api_key,
    )


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        specialists = {
            "research": build_research_agent(
                hermes_toolsets=["web", "browser"],
                **_di("stepfun-ai/Step-3.5-Flash"),
            ),
            "web": build_web_agent(
                hermes_toolsets=["web", "browser", "code_execution", "terminal", "file"],
                **_di("Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo"),
            ),
            "marketing": build_marketing_agent(
                hermes_toolsets=["web", "browser", "image_gen"],
                **_di("mistralai/Mistral-Small-3.2-24B-Instruct-2506"),
            ),
            "technical": build_technical_agent(
                hermes_toolsets=["web", "browser", "code_execution", "terminal", "file"],
                **_di("Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo"),
            ),
            "legal": build_legal_agent(
                hermes_toolsets=["web", "file"],
                **_di("moonshotai/Kimi-K2.5"),
            ),
            "ops": build_ops_agent(
                hermes_toolsets=["web", "file"],
                **_di("moonshotai/Kimi-K2.5"),
            ),
            "sales": build_sales_agent(
                hermes_toolsets=["web", "browser"],
                **_di("meta-llama/Meta-Llama-3.3-70B-Instruct"),
            ),
            "design": build_design_agent(
                hermes_toolsets=["web", "browser", "image_gen", "vision"],
                **_di("mistralai/Mistral-Small-3.2-24B-Instruct-2506"),
            ),
        }
        planner = Agent(
            name="planner",
            role="planning coordinator. Decompose founder goals into specialist tasks scoped to each agent's actual capabilities.",
            tools={},
            sub_agents=list(specialists.values()),
            **_di(settings.planner_model_name or "moonshotai/Kimi-K2.5"),
        )
        _orchestrator = Orchestrator(planner=planner, specialists=specialists)
    return _orchestrator

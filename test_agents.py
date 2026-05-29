"""Quick smoke-test each specialist agent: 3 iterations, shared goal."""
import asyncio, logging, time, json, sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
# Silence noisy HTTP/network internals — show only our app logs
for noisy in ("httpx", "httpcore", "openai", "openai._base_client", "primp", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

from backend.core.agent import AgentContext
from backend.config import settings

GOAL = (
    "Startup idea: AI-powered fitness coach app that personalizes workouts and nutrition "
    "based on biometrics. Target market: busy professionals aged 25-45. "
    "Founder has $50k budget and 6 months runway."
)

CTX = AgentContext(founder_id="test_founder", session_id="agent_smoke_test", goal=GOAL)

FLASH = dict(
    model="deepseek-ai/DeepSeek-V4-Flash",
    model_base_url=settings.planner_model_base_url,
    model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
)
SCOUT = dict(
    model="meta-llama/Llama-4-Scout-17B-16E-Instruct",
    model_base_url=settings.agent_model_base_url,
    model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
)


# Agents that need more steps to complete their mandatory workflow
_ITER_OVERRIDES = {
    "web": 6,      # obsidian_read(design) + HTML gen + vercel + log + done + 1 buffer
    "ops": 5,      # PDF + stripe + log + done
    "legal": 6,    # read + patent + 3 PDFs + log + done
    "technical": 6,
    "design": 5,
}

async def test(name: str, agent):
    agent._max_iterations = _ITER_OVERRIDES.get(name, 3)
    t0 = time.time()
    print(f"  ⏳ {name:<25} starting...", flush=True)
    try:
        result = await agent.run(CTX)
        elapsed = time.time() - t0
        status = result.get("status", "GOAL_DONE") if isinstance(result, dict) else "GOAL_DONE"
        keys = [k for k in result.keys() if k != "status"] if isinstance(result, dict) else []
        print(f"  ✅ {name:<25} {elapsed:5.1f}s  [{status}]  output keys: {keys}", flush=True)
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ {name:<25} {elapsed:5.1f}s  {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


async def main():
    from backend.specialists.research import build_research_agent
    from backend.specialists.web import build_web_agent
    from backend.specialists.marketing import build_marketing_agent
    from backend.specialists.technical import build_technical_agent
    from backend.specialists.legal import build_legal_agent
    from backend.specialists.ops import build_ops_agent
    from backend.specialists.sales import build_sales_agent
    from backend.specialists.design import build_design_agent

    agents = [
        ("research",            build_research_agent(agent_name="research", use_computer=False)),
        ("research_competitors", build_research_agent(agent_name="research_competitors", use_computer=False)),
        ("research_execution",  build_research_agent(agent_name="research_execution", use_computer=False)),
        ("web",                 build_web_agent(use_computer=False, **FLASH)),
        ("marketing",           build_marketing_agent(use_computer=False, **FLASH)),
        ("technical",           build_technical_agent(use_computer=False, **FLASH)),
        ("legal",               build_legal_agent(use_computer=False, **FLASH)),
        ("ops",                 build_ops_agent(use_computer=False, **FLASH)),
        ("sales",               build_sales_agent(use_computer=False, **SCOUT)),
        ("design",              build_design_agent(use_computer=False, **SCOUT)),
    ]

    print(f"\nTesting {len(agents)} agents (3-6 iterations each)...\n")
    results = []
    for name, agent in agents:
        ok = await test(name, agent)
        results.append(ok)

    passed = sum(results)
    print(f"\n{passed}/{len(agents)} passed")
    sys.exit(0 if passed == len(agents) else 1)


asyncio.run(main())

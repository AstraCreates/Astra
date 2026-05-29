import asyncio, logging, time

logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(name)s  %(message)s")

# Show everything from our code
logging.getLogger("backend").setLevel(logging.DEBUG)

# Silence noisy internals
for noisy in ("httpx", "httpcore", "openai", "openai._base_client", "primp", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

from backend.core.agent import AgentContext
from backend.config import settings
from backend.specialists.web import build_web_agent

GOAL = (
    "Startup idea: AI-powered fitness coach app that personalizes workouts and nutrition "
    "based on biometrics. Target market: busy professionals aged 25-45. "
    "Founder has $50k budget and 6 months runway."
)
CTX = AgentContext(founder_id="test_founder", session_id="agent_smoke_test", goal=GOAL, bypass_approvals=True)
FLASH = dict(
    model="deepseek-ai/DeepSeek-V4-Flash",
    model_base_url=settings.planner_model_base_url,
    model_api_key=settings.planner_model_api_key or settings.agent_model_api_key,
)

async def main():
    agent = build_web_agent(use_computer=False, **FLASH)
    agent._max_iterations = 6
    t0 = time.time()
    result = await agent.run(CTX)
    elapsed = time.time() - t0
    print(f"\n{elapsed:.1f}s  {result}")

asyncio.run(main())

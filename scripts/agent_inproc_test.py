"""In-process agent tester — runs specialists directly (no HTTP/auth/credits).

Usage (inside backend container):
    python -m scripts.agent_inproc_test web technical          # specific agents
    python -m scripts.agent_inproc_test ALL                    # every specialist

For each agent: builds an AgentContext, runs it with a timeout, and prints
PASS/FAIL plus a compact summary or the exception/traceback.
"""
import asyncio
import sys
import time
import traceback

GOAL = "Build ClearNotes, a SaaS that turns meeting recordings into action items and email drafts."
FOUNDER = "inproc_test_founder"
PER_AGENT_TIMEOUT = 300  # seconds


def _summarize(result) -> str:
    if not isinstance(result, dict):
        return str(result)[:300]
    if result.get("error"):
        return f"ERROR: {str(result['error'])[:300]}"
    for k in ("summary", "output_summary", "formatted_text", "report", "repo_url", "deploy_url", "url"):
        v = result.get(k)
        if isinstance(v, str) and v.strip():
            return f"{k}={v.strip()[:240]}"
    keys = ", ".join(list(result.keys())[:10])
    return f"(no summary; keys: {keys})"


async def run_one(name, agent, shared) -> dict:
    from backend.core.agent import AgentContext
    start = time.time()
    ctx = AgentContext(goal=GOAL, founder_id=FOUNDER, session_id=f"inproc_{name}", shared=dict(shared))
    out = {"agent": name, "status": "?", "detail": "", "elapsed": 0.0}
    try:
        result = await asyncio.wait_for(agent.run(ctx), timeout=PER_AGENT_TIMEOUT)
        if isinstance(result, dict) and result.get("error"):
            out["status"] = "FAIL"
            out["detail"] = f"ERROR: {str(result['error'])[:300]}"
        else:
            out["status"] = "PASS"
            out["detail"] = _summarize(result)
    except asyncio.TimeoutError:
        out["status"] = "TIMEOUT"
        out["detail"] = f"exceeded {PER_AGENT_TIMEOUT}s"
    except Exception as exc:
        out["status"] = "EXC"
        out["detail"] = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exc()[-800:])
    out["elapsed"] = round(time.time() - start, 1)
    return out


async def main(names):
    from backend.core.factory import get_orchestrator
    orch = get_orchestrator()
    specialists = orch.specialists
    if names == ["ALL"]:
        names = list(specialists.keys())
    shared = {"company_name": "ClearNotes", "constraints": {}}
    print(f"\nIn-process testing {len(names)} agent(s)\n{'-'*64}")
    results = []
    for name in names:
        agent = specialists.get(name)
        if agent is None:
            print(f"  ✗ {name:<24} UNKNOWN (not in orchestrator)")
            results.append({"agent": name, "status": "UNKNOWN", "detail": "", "elapsed": 0})
            continue
        print(f"  … running {name} …", flush=True)
        r = await run_one(name, agent, shared)
        icon = {"PASS": "✓", "FAIL": "✗", "TIMEOUT": "⏳", "EXC": "✗", "UNKNOWN": "?"}.get(r["status"], "?")
        print(f"  {icon} {name:<24} {r['status']:<8} {r['elapsed']}s  {r['detail'][:200]}", flush=True)
        results.append(r)

    print(f"\n{'='*64}")
    passed = [r["agent"] for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] not in ("PASS",)]
    print(f"PASSED ({len(passed)}/{len(results)}): {', '.join(passed)}")
    if failed:
        print(f"\nFAILED ({len(failed)}):")
        for r in failed:
            print(f"\n--- {r['agent']} [{r['status']}] ---\n{r['detail']}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:] or ["ALL"]
    asyncio.run(main(args))

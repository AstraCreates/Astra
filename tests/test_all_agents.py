"""
Smoke-test every agent individually.
Posts a single-agent goal, streams events until agent_done/goal_done/goal_error or timeout.
"""
import asyncio
import json
import sys
import time
import httpx

BASE = "http://localhost:8000"
GOAL = "Build a SaaS tool for freelancers to track invoices and payments."
TIMEOUT = 120  # seconds per agent
CONCURRENCY = 4  # agents running in parallel

AGENTS = [
    "research",
    "research_market",
    "research_financial",
    "research_regulatory",
    "legal",
    "legal_docs",
    "legal_entity",
    "legal_ip",
    "web",
    "marketing",
    "marketing_content",
    "marketing_outreach",
    "marketing_seo",
    "marketing_paid",
    "technical",
    "technical_scaffold",
    "technical_infra",
    "technical_data",
    "ops",
    "sales",
    "sales_pipeline",
    "sales_enablement",
    "finance_model",
    "finance_fundraise",
    "design",
]

RESULTS: dict[str, dict] = {}


async def run_agent_check(agent: str, client: httpx.AsyncClient) -> None:
    start = time.time()
    result = {"agent": agent, "status": "unknown", "events": [], "error": None, "elapsed": 0}

    try:
        # Submit goal with single agent
        r = await client.post(
            f"{BASE}/goal",
            json={
                "instruction": GOAL,
                "founder_id": "test_founder",
                "constraints": {"stack_id": "custom", "agents": [agent]},
            },
            headers={"x-astra-internal-test": "1"},
            timeout=30,
        )
        if r.status_code != 200:
            result["status"] = "submit_failed"
            result["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            RESULTS[agent] = result
            return

        session_id = r.json().get("session_id") or r.json().get("goal_id")
        if not session_id:
            result["status"] = "no_session_id"
            result["error"] = str(r.json())
            RESULTS[agent] = result
            return

        # Stream events
        deadline = time.time() + TIMEOUT
        async with client.stream("GET", f"{BASE}/stream/{session_id}", timeout=TIMEOUT) as stream:
            async for line in stream.aiter_lines():
                if time.time() > deadline:
                    result["status"] = "timeout"
                    break
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue

                etype = evt.get("type", "")
                result["events"].append(etype)

                if etype == "agent_start" and result["status"] == "unknown":
                    result["status"] = "started"
                elif etype == "agent_done":
                    result["status"] = "done"
                    break
                elif etype == "goal_done":
                    result["status"] = "done"
                    break
                elif etype == "goal_error":
                    result["status"] = "error"
                    result["error"] = evt.get("error") or evt.get("message", "unknown error")
                    break

    except Exception as exc:
        result["status"] = "exception"
        result["error"] = str(exc)

    result["elapsed"] = round(time.time() - start, 1)
    RESULTS[agent] = result
    icon = "✓" if result["status"] == "done" else ("⏳" if result["status"] in ("started", "timeout") else "✗")
    print(f"  {icon} {agent:<25} {result['status']:<12} {result['elapsed']}s")
    sys.stdout.flush()


async def main() -> None:
    print(f"\nTesting {len(AGENTS)} agents against {BASE}\n")
    print(f"  {'AGENT':<25} {'STATUS':<12} TIME")
    print(f"  {'-'*50}")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def guarded(agent: str) -> None:
            async with sem:
                await run_agent_check(agent, client)

        await asyncio.gather(*[guarded(a) for a in AGENTS])

    print(f"\n{'='*60}")
    done = [a for a, r in RESULTS.items() if r["status"] == "done"]
    started = [a for a, r in RESULTS.items() if r["status"] in ("started", "timeout")]
    failed = [a for a, r in RESULTS.items() if r["status"] not in ("done", "started", "timeout")]

    print(f"  PASSED  ({len(done)}): {', '.join(done)}")
    if started:
        print(f"  PARTIAL ({len(started)}): {', '.join(started)}")
    if failed:
        print(f"\n  FAILED  ({len(failed)}):")
        for a in failed:
            r = RESULTS[a]
            print(f"    {a}: [{r['status']}] {r['error']}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

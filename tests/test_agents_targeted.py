"""Quick targeted smoke test — 2 concurrent, 300s timeout."""
import asyncio, json, sys, time, httpx

BASE = "http://localhost:8000"
GOAL = "Build a SaaS tool for freelancers to track invoices and payments."
TIMEOUT = 300
CONCURRENCY = 2

# Test all 25; run 2 at a time to avoid saturating the server
AGENTS = [
    "research", "research_market", "research_financial", "research_regulatory",
    "legal", "legal_docs", "legal_entity", "legal_ip",
    "web",
    "marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid",
    "technical", "technical_scaffold", "technical_infra", "technical_data",
    "ops", "sales", "sales_pipeline", "sales_enablement",
    "finance_model", "finance_fundraise", "design",
]

RESULTS: dict = {}

async def run_agent_check(agent: str, client: httpx.AsyncClient) -> None:
    start = time.time()
    result = {"status": "unknown", "error": None, "events": []}
    try:
        r = await client.post(f"{BASE}/goal", json={
            "instruction": GOAL,
            "founder_id": "test_founder",
            "constraints": {"stack_id": "custom", "agents": [agent]},
        }, timeout=30)
        if r.status_code != 200:
            result.update(status="submit_failed", error=f"HTTP {r.status_code}: {r.text[:200]}")
            RESULTS[agent] = result; _print(agent, result, time.time()-start); return

        session_id = r.json().get("session_id") or r.json().get("goal_id")
        deadline = time.time() + TIMEOUT
        async with client.stream("GET", f"{BASE}/stream/{session_id}", timeout=TIMEOUT) as stream:
            async for line in stream.aiter_lines():
                if time.time() > deadline:
                    result["status"] = "timeout"; break
                if not line.startswith("data:"): continue
                try: evt = json.loads(line[5:].strip())
                except: continue
                et = evt.get("type","")
                result["events"].append(et)
                if et == "agent_start" and result["status"] == "unknown":
                    result["status"] = "started"
                elif et == "agent_done":
                    result["status"] = "done"; break
                elif et == "goal_done":
                    result["status"] = "done"; break
                elif et == "goal_error":
                    result["status"] = "error"
                    result["error"] = evt.get("error") or evt.get("message","")
                    break
    except Exception as e:
        result["status"] = "exception"; result["error"] = str(e)

    elapsed = round(time.time()-start, 1)
    RESULTS[agent] = result
    _print(agent, result, elapsed)

def _print(agent, result, elapsed):
    icon = "✓" if result["status"] == "done" else ("⏳" if result["status"] in ("started","timeout") else "✗")
    print(f"  {icon} {agent:<25} {result['status']:<12} {elapsed}s", flush=True)

async def main():
    print(f"\nTesting {len(AGENTS)} agents ({CONCURRENCY} parallel, {TIMEOUT}s timeout)\n")
    print(f"  {'AGENT':<25} {'STATUS':<12} TIME\n  {'-'*50}")
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        async def g(a):
            async with sem: await run_agent_check(a, client)
        await asyncio.gather(*[g(a) for a in AGENTS])

    done = [a for a,r in RESULTS.items() if r["status"]=="done"]
    partial = [a for a,r in RESULTS.items() if r["status"] in ("started","timeout")]
    failed = [a for a,r in RESULTS.items() if r["status"] not in ("done","started","timeout")]
    print(f"\n{'='*60}")
    print(f"  DONE    ({len(done)}): {', '.join(done)}")
    if partial: print(f"  RUNNING ({len(partial)}): {', '.join(partial)}")
    if failed:
        print(f"\n  FAILED  ({len(failed)}):")
        for a in failed:
            print(f"    {a}: [{RESULTS[a]['status']}] {RESULTS[a]['error']}")
    print()

if __name__ == "__main__":
    asyncio.run(main())

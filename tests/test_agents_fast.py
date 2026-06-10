"""One representative per category — serial, 90s timeout."""
import asyncio, json, time, httpx

BASE = "http://localhost:8000"
GOAL = "Build a SaaS for freelancers to track invoices."
TIMEOUT = 90

AGENTS = [
    "research_market",
    "research_financial",
    "research_regulatory",
    "legal_docs",
    "legal_entity",
    "legal_ip",
    "marketing_content",
    "marketing_outreach",
    "marketing_seo",
    "marketing_paid",
    "sales_pipeline",
    "sales_enablement",
    "technical_scaffold",
    "technical_infra",
    "technical_data",
    "finance_model",
    "finance_fundraise",
    "design",
    "ops",
    "web",
    "research",
    "legal",
    "marketing",
    "technical",
    "sales",
]

async def run_agent_check(agent: str, client: httpx.AsyncClient) -> tuple[str, str, float]:
    start = time.time()
    status = "unknown"
    error = ""
    try:
        r = await client.post(f"{BASE}/goal", json={
            "instruction": GOAL,
            "founder_id": "test_founder",
            "constraints": {"stack_id": "custom", "agents": [agent]},
        }, timeout=30)
        if r.status_code != 200:
            return agent, f"submit_failed:{r.status_code}", round(time.time()-start, 1)

        session_id = r.json().get("session_id") or r.json().get("goal_id")
        deadline = time.time() + TIMEOUT
        async with client.stream("GET", f"{BASE}/stream/{session_id}", timeout=TIMEOUT+5) as stream:
            async for line in stream.aiter_lines():
                if time.time() > deadline:
                    status = "timeout"; break
                if not line.startswith("data:"): continue
                try: evt = json.loads(line[5:].strip())
                except: continue
                et = evt.get("type","")
                if et == "agent_start": status = "started"
                elif et in ("agent_done", "goal_done"): status = "done"; break
                elif et == "goal_error":
                    status = "error"
                    error = (evt.get("error") or evt.get("message",""))[:120]
                    break
    except Exception as e:
        status = "exception"
        error = str(e)[:120]

    elapsed = round(time.time()-start, 1)
    icon = "✓" if status == "done" else ("⏳" if status in ("started","timeout") else "✗")
    print(f"  {icon} {agent:<25} {status:<12} {elapsed}s{(' — '+error) if error else ''}", flush=True)
    return agent, status, elapsed

async def main():
    print(f"\nFast agent test — serial, 90s timeout each\n")
    print(f"  {'AGENT':<25} {'STATUS':<12} TIME\n  {'-'*55}")
    results = []
    async with httpx.AsyncClient() as client:
        for agent in AGENTS:
            r = await run_agent_check(agent, client)
            results.append(r)

    done = [a for a,s,_ in results if s == "done"]
    started = [a for a,s,_ in results if s in ("started","timeout")]
    failed = [a for a,s,_ in results if s not in ("done","started","timeout")]
    print(f"\n{'='*60}")
    print(f"  DONE ({len(done)}): {', '.join(done) or 'none'}")
    if started: print(f"  STARTED/TIMEOUT ({len(started)}): {', '.join(started)}")
    if failed: print(f"  FAILED ({len(failed)}): {', '.join(failed)}")
    print()

if __name__ == "__main__":
    asyncio.run(main())

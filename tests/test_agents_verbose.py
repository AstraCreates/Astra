"""Verbose agent smoke test — serial, 300s timeout, every SSE event printed."""
import asyncio, json, time, httpx, sys

BASE = "https://167.235.151.204"
GOAL = "Build a SaaS for freelancers to track invoices."
TIMEOUT = 300
CONCURRENCY = 1

AGENTS = [
    "research", "research_market", "research_financial", "research_regulatory",
    "legal", "legal_docs", "legal_entity", "legal_ip",
    "web",
    "marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid",
    "technical", "technical_scaffold", "technical_infra", "technical_data",
    "ops", "sales", "sales_pipeline", "sales_enablement",
    "finance_model", "finance_fundraise", "design",
]

_lock = asyncio.Lock()

async def log(msg: str):
    async with _lock:
        print(msg, flush=True)

async def test_agent(agent: str, client: httpx.AsyncClient) -> tuple[str, str]:
    start = time.time()
    status = "unknown"
    error = ""

    await log(f"\n[{agent}] SUBMITTING")
    try:
        r = None
        for attempt in range(1, 4):
            try:
                r = await client.post(f"{BASE}/goal", json={
                    "instruction": GOAL,
                    "founder_id": "test_founder",
                    "constraints": {
                        "stack_id": "custom",
                        "agents": [agent],
                        "bypass_planner": True,
                        "company_name": "InvoiceAI",
                    },
                }, timeout=30)
                if r.status_code != 502:
                    break
                await log(f"[{agent}] 502 on attempt {attempt}/3, retrying in 5s...")
                if attempt < 3:
                    await asyncio.sleep(5)
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as conn_err:
                await log(f"[{agent}] Connection error on attempt {attempt}/3: {conn_err}")
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    return agent, "submit_failed:connection_error"

        if r is None or r.status_code != 200:
            code = r.status_code if r is not None else "no_response"
            text = r.text[:300] if r is not None else ""
            await log(f"[{agent}] SUBMIT FAILED {code}: {text}")
            return agent, f"submit_failed:{code}"

        session_id = r.json().get("session_id") or r.json().get("goal_id")
        await log(f"[{agent}] session={session_id}")

        deadline = time.time() + TIMEOUT
        async with client.stream("GET", f"{BASE}/stream/{session_id}", timeout=TIMEOUT+10) as stream:
            async for line in stream.aiter_lines():
                if time.time() > deadline:
                    await log(f"[{agent}] TIMEOUT after {round(time.time()-start)}s")
                    status = "timeout"
                    break
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue

                et = evt.get("type", "")
                elapsed = round(time.time() - start, 1)

                # Print every meaningful event
                if et == "agent_start":
                    status = "started"
                    await log(f"[{agent}] +{elapsed}s  AGENT_START agent={evt.get('agent')}")
                elif et == "agent_action":
                    tool = evt.get("tool") or evt.get("action") or ""
                    await log(f"[{agent}] +{elapsed}s  ACTION  {tool}")
                elif et == "agent_action_result":
                    tool = evt.get("tool") or ""
                    snippet = str(evt.get("result") or "")[:80].replace("\n"," ")
                    await log(f"[{agent}] +{elapsed}s  RESULT  {tool} → {snippet}")
                elif et == "agent_done":
                    status = "done"
                    await log(f"[{agent}] +{elapsed}s  AGENT_DONE ✓")
                    break
                elif et == "goal_done":
                    status = "done"
                    await log(f"[{agent}] +{elapsed}s  GOAL_DONE ✓")
                    break
                elif et == "goal_error":
                    status = "error"
                    error = (evt.get("error") or evt.get("message") or "")[:200]
                    await log(f"[{agent}] +{elapsed}s  GOAL_ERROR: {error}")
                    break
                elif et == "plan_done":
                    tasks = evt.get("tasks") or []
                    await log(f"[{agent}] +{elapsed}s  PLAN_DONE tasks={[t.get('agent') for t in tasks]}")
                else:
                    await log(f"[{agent}] +{elapsed}s  {et}")

    except Exception as e:
        status = "exception"
        error = str(e)[:200]
        await log(f"[{agent}] EXCEPTION: {error}")

    elapsed = round(time.time() - start, 1)
    icon = "✓" if status == "done" else ("⏳" if status in ("started", "timeout") else "✗")
    await log(f"\n{icon} {agent} → {status} ({elapsed}s)")
    return agent, status


async def main():
    print(f"Verbose agent test — {CONCURRENCY} parallel, {TIMEOUT}s timeout")
    print(f"Testing {len(AGENTS)} agents\n{'='*60}")

    results = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run(a):
        async with sem:
            return await test_agent(a, client)

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        batch_results = await asyncio.gather(*[run(a) for a in AGENTS])
        results.extend(batch_results)

    print(f"\n{'='*60}\nSUMMARY")
    done    = [a for a,s in results if s == "done"]
    partial = [a for a,s in results if s in ("started","timeout")]
    failed  = [a for a,s in results if s not in ("done","started","timeout")]
    print(f"  DONE    ({len(done)}): {', '.join(done) or 'none'}")
    print(f"  RUNNING ({len(partial)}): {', '.join(partial) or 'none'}")
    print(f"  FAILED  ({len(failed)}): {', '.join(failed) or 'none'}")

asyncio.run(main())

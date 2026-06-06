"""End-to-end pipeline test — runs the FULL orchestrator once and reports.

Verifies (in one real run):
  - every planned agent runs and returns output (per-agent PASS/FAIL)
  - the dependency-driven scheduler ordering (start times per agent)
  - the continuous-operating bootstrap fired (company_goal + missions created)

Run inside the backend container:
    python -u -m backend._e2e_test
"""
import asyncio
import time

GOAL = "Build ClearNotes, a SaaS that turns meeting recordings into action items and email drafts for solo founders."
FOUNDER = "pipeline_e2e_founder"


async def main():
    from backend.core.factory import get_orchestrator
    from backend.core import events as _events

    # Tap the event stream to record agent start/finish ordering + terminal event.
    starts: dict[str, float] = {}
    dones: dict[str, float] = {}
    terminal = {"type": None, "error": None, "incomplete": None}
    company_operating = {"seen": False, "mission_count": None}
    t0 = time.time()

    orig_publish = _events.publish

    async def tap(session_id, event):
        et = event.get("type")
        ag = event.get("agent")
        now = round(time.time() - t0, 1)
        if et == "agent_start" and ag and ag not in starts:
            starts[ag] = now
        elif et in ("agent_done", "agent_error") and ag and ag not in dones:
            dones[ag] = now
        elif et in ("goal_done", "goal_error"):
            terminal["type"] = et
            terminal["error"] = event.get("error")
            terminal["incomplete"] = event.get("incomplete_tasks")
        elif et == "company_operating":
            company_operating["seen"] = True
            company_operating["mission_count"] = event.get("mission_count")
        return await orig_publish(session_id, event)

    _events.publish = tap
    orch = get_orchestrator()

    print(f"\n=== E2E full-pipeline run: {GOAL[:60]}… ===\n", flush=True)
    result = await orch.run(goal=GOAL, founder_id=FOUNDER, session_id="e2e_pipeline")
    elapsed = round(time.time() - t0, 1)

    completed = (result or {}).get("results", {})
    print(f"\n=== RESULTS (total {elapsed}s) ===", flush=True)
    print(f"{'AGENT':<22}{'START':>7}{'DONE':>7}  STATUS  SUMMARY", flush=True)
    for tid, res in completed.items():
        ag = res.get("agent", tid) if isinstance(res, dict) else tid
        st = starts.get(ag)
        dn = dones.get(ag)
        ok = isinstance(res, dict) and not res.get("error") and not res.get("timed_out")
        icon = "PASS" if ok else "FAIL"
        summ = ""
        if isinstance(res, dict):
            summ = str(res.get("summary") or res.get("repo_url") or res.get("deploy_url")
                       or res.get("error") or list(res.keys()))[:90]
        print(f"{ag:<22}{(str(st)+'s') if st is not None else '-':>7}{(str(dn)+'s') if dn is not None else '-':>7}  {icon:<6}  {summ}", flush=True)

    print(f"\nterminal event: {terminal['type']}", flush=True)
    if terminal["incomplete"]:
        print(f"incomplete: {terminal['incomplete']}", flush=True)
    print(f"company_operating event seen: {company_operating['seen']} (missions={company_operating['mission_count']})", flush=True)

    # Verify operating-system persistence
    try:
        from backend.missions.company_goal import get_company_goal
        from backend.missions.store import list_missions
        cg = get_company_goal(FOUNDER)
        ms = list_missions(FOUNDER)
        print(f"company_goal persisted: {bool(cg)}; missions persisted: {len(ms)}", flush=True)
        if cg:
            print(f"north_star: {str(cg.get('north_star'))[:120]}", flush=True)
        for m in ms[:8]:
            print(f"  - [{m.get('department')}] {m.get('name')} ({len(m.get('tasks') or [])} tasks, status={m.get('status')})", flush=True)
    except Exception as exc:
        print(f"operating-state check error: {exc}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

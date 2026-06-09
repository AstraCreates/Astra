"""Focused technical-agent test — verifies run_mvp_loop builds + deploys.

Creates a real GitHub repo, runs the technical specialist against it with a
realistic goal + research context, and reports repo_url / deploy_url / files /
error. Run inside the backend container:

    python -u -m backend._tech_test
"""
import asyncio
import time

GOAL = "Build the ClearNotes product MVP: Next.js 15 app with NextAuth sign-in, a dashboard that lists meeting recordings, and an action-items view. No Clerk."
FOUNDER = "tech_test_founder"


async def main():
    t0 = time.time()
    from backend.tools.github_scaffold import github_create_repo
    from backend.core.factory import get_orchestrator
    from backend.core.agent import AgentContext

    print("=== create repo ===", flush=True)
    repo = await asyncio.to_thread(
        github_create_repo,
        repo_name="clearnotes-techtest",
        description="ClearNotes MVP technical-agent test",
        founder_id=FOUNDER,
    )
    repo_url = repo.get("repo_url", "")
    print(f"repo created={repo.get('created')} url={repo_url} err={repo.get('error')}", flush=True)

    orch = get_orchestrator()
    tech = orch.specialists["technical"]
    ctx = AgentContext(
        goal=GOAL,
        founder_id=FOUNDER,
        session_id="tech_test",
        shared={
            "company_name": "ClearNotes",
            "repo_url": repo_url,
            "result_web": {"repo_url": repo_url, "deploy_url": ""},
            "constraints": {},
        },
    )
    print("\n=== run technical agent ===", flush=True)
    try:
        result = await asyncio.wait_for(tech.run(ctx), timeout=2400)
    except asyncio.TimeoutError:
        print(f"TIMEOUT after {round(time.time()-t0)}s", flush=True)
        return
    except Exception as exc:
        import traceback
        print(f"EXCEPTION: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1200:]}", flush=True)
        return

    elapsed = round(time.time() - t0)
    print(f"\n=== RESULT ({elapsed}s) ===", flush=True)
    if isinstance(result, dict):
        for k in ("error", "repo_url", "deploy_url", "url", "files_in_repo", "summary"):
            if k in result:
                print(f"  {k}: {str(result[k])[:200]}", flush=True)
        ok = not result.get("error") and (result.get("files_in_repo") or result.get("repo_url"))
        print(f"\n  VERDICT: {'PASS' if ok else 'FAIL'}", flush=True)
    else:
        print(f"  non-dict result: {str(result)[:300]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

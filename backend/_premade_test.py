"""Premade-research agent tester.

Seeds a realistic "session so far" (research + upstream notes in the vault, plus
shared-context artifacts) then runs each downstream specialist against it exactly
like a normal run would — capturing PASS/FAIL, per-agent result summary, and any
exception/traceback.

Run inside the backend container:
    python -u -m backend._premade_test legal marketing sales ops design
    python -u -m backend._premade_test ALL
"""
import asyncio
import logging
import sys
import time
import traceback

# Surface agent iteration logs ([agent] iter=N action=...) so progress is visible.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
for _noisy in ("httpx", "openai", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

FOUNDER = "premade_test_founder"
COMPANY = "ClearNotes"
GOAL = ("Company/project name: ClearNotes\n\nBuild ClearNotes, a SaaS that turns meeting "
        "recordings into action items and email drafts for solo founders and small teams.")
PER_AGENT_TIMEOUT = 360

# ── Premade research / upstream outputs (what a normal session would have) ──────
MARKET_BRIEF = (
    "Category: AI meeting-notes & action-item automation for SMB/solo founders. "
    "TAM $18.4B (2025) -> $42B (2030), CAGR 17.9%. SAM $2.1B (English-speaking SMB). "
    "SOM Y1 $0.4-1.2M ARR. Trends: 68% of SMBs now run hybrid meetings; AI summarization "
    "adoption up 90% YoY; buyers want action items + CRM/email sync, not just transcripts."
)
ICP_BRIEF = (
    "Primary ICP: solo founders & 2-10 person teams running 10-25 meetings/week. "
    "Pain: notes never become action; follow-up emails slip. Budget $15-40/user/mo. "
    "Channels: Twitter/X, IndieHackers, LinkedIn, Product Hunt. Decision maker = founder."
)
PRICING = (
    "Free (3 meetings/mo); Pro $19/user/mo (unlimited, action items, email drafts); "
    "Team $39/user/mo (CRM sync, shared workspace). Anchor vs $25-50 takeout of manual VA time."
)
COMPETITORS = (
    "Otter.ai (transcription-led, weak action items), Fireflies (CRM sync, pricey), "
    "Fathom (free, Zoom-only), Granola (founder-favorite, Mac-only), tl;dv. "
    "Gap: action-item + email-draft automation tuned for solo founders, cross-platform."
)
COLOR_PALETTE = {"primary": "#2b45ff", "accent": "#16a34a", "neutral": "#111827", "bg": "#ffffff"}
BRAND_DIRECTION = ("Trustworthy, calm, productivity-forward. Chakra Petch headings, IBM Plex "
                   "Mono body. Square corners, generous whitespace, electric-blue primary.")


def _research_md(agent: str, body: str) -> str:
    return (f"---\nagent: {agent}\nfounder_id: {FOUNDER}\n---\n\n# {agent.title()} Notes\n\n"
            f"## Summary\n{body}\n")


def _seed_vault():
    from backend.tools.obsidian_logger import obsidian_log
    sid = "premade_seed"
    obsidian_log(agent="research", session_id=sid, founder_id=FOUNDER,
                 summary=MARKET_BRIEF,
                 output={"market_brief": MARKET_BRIEF, "icp_brief": ICP_BRIEF, "pricing_hypothesis": PRICING})
    obsidian_log(agent="research_competitors", session_id=sid, founder_id=FOUNDER,
                 summary=COMPETITORS, output={"competitor_analysis": COMPETITORS})
    obsidian_log(agent="research_execution", session_id=sid, founder_id=FOUNDER,
                 summary=MARKET_BRIEF + " " + ICP_BRIEF,
                 output={"market_brief": MARKET_BRIEF, "icp_brief": ICP_BRIEF, "pricing_hypothesis": PRICING})
    obsidian_log(agent="design", session_id=sid, founder_id=FOUNDER,
                 summary=BRAND_DIRECTION,
                 output={"color_palette": COLOR_PALETTE, "brand_direction": BRAND_DIRECTION})
    obsidian_log(agent="technical", session_id=sid, founder_id=FOUNDER,
                 summary="MVP: Next.js + Supabase. Upload recording -> Whisper transcript -> GPT action items + email draft.",
                 output={"mvp_roadmap": "Auth, upload, transcribe, summarize, action items, email draft, dashboard."})


def _shared():
    # Mirrors what the orchestrator accumulates into shared + prior_results.
    research = {
        "market_brief_summary": MARKET_BRIEF, "icp_brief": ICP_BRIEF,
        "pricing_hypothesis": PRICING, "competitor_analysis": COMPETITORS,
        "artifacts_produced": ["market_brief", "icp_brief", "pricing_hypothesis"],
    }
    design = {"color_palette": COLOR_PALETTE, "brand_direction": BRAND_DIRECTION,
              "design_spec": BRAND_DIRECTION}
    technical = {"mvp_roadmap": "Auth, upload, transcribe, summarize, action items, email draft.",
                 "repo_url": "https://github.com/premade/clearnotes"}
    web = {"landing_page": "https://clearnotes-preview.example.com", "website_copy": "Turn meetings into momentum."}
    return {
        "company_name": COMPANY,
        "creative_brief": {"company_name": COMPANY, "brand_direction": BRAND_DIRECTION},
        "market_brief": MARKET_BRIEF, "icp_brief": ICP_BRIEF, "pricing_hypothesis": PRICING,
        "competitor_analysis": COMPETITORS,
        "prior_results": {
            "t_research": research, "t_research_competitors": {"competitor_analysis": COMPETITORS},
            "t_design": design, "t_technical": technical, "t_web": web,
        },
    }


def _summarize(result) -> str:
    if not isinstance(result, dict):
        return str(result)[:300]
    if result.get("error"):
        return f"ERROR: {str(result['error'])[:400]}"
    for k in ("summary", "output_summary", "formatted_text", "report", "repo_url", "deploy_url", "url", "documents"):
        v = result.get(k)
        if v:
            return f"{k}={str(v)[:240]}"
    return "(ok; keys: " + ", ".join(list(result.keys())[:12]) + ")"


async def run_one(name, agent, shared) -> dict:
    from backend.core.agent import AgentContext
    from backend.tools.obsidian_logger import format_vault_context
    start = time.time()
    sh = dict(shared)
    try:
        sh["prior_vault_notes"] = format_vault_context("research", 3, FOUNDER)
    except Exception:
        pass
    ctx = AgentContext(goal=GOAL, founder_id=FOUNDER, session_id=f"premade_{name}",
                       shared=sh, unlimited_credits=True, bypass_approvals=True)
    out = {"agent": name, "status": "?", "detail": "", "elapsed": 0.0}
    try:
        result = await asyncio.wait_for(agent.run(ctx), timeout=PER_AGENT_TIMEOUT)
        if isinstance(result, dict) and result.get("error"):
            out["status"] = "FAIL"; out["detail"] = f"ERROR: {str(result['error'])[:400]}"
        else:
            out["status"] = "PASS"; out["detail"] = _summarize(result)
    except asyncio.TimeoutError:
        out["status"] = "TIMEOUT"; out["detail"] = f"exceeded {PER_AGENT_TIMEOUT}s"
    except Exception as exc:
        out["status"] = "EXC"
        out["detail"] = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exc()[-1200:])
    out["elapsed"] = round(time.time() - start, 1)
    return out


async def main(names):
    from backend.core.factory import get_orchestrator
    orch = get_orchestrator()
    specialists = orch.specialists
    _seed_vault()
    shared = _shared()
    if names == ["ALL"]:
        names = [n for n in specialists.keys() if not n.startswith("research")]
    print(f"Seeded premade research for founder={FOUNDER}. Testing: {names}\n", flush=True)
    for name in names:
        agent = specialists.get(name)
        if agent is None:
            print(f"[{name}] SKIP — no such specialist", flush=True)
            continue
        print(f"[{name}] running...", flush=True)
        r = await run_one(name, agent, shared)
        print(f"[{name}] {r['status']} ({r['elapsed']}s) :: {r['detail']}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["ALL"]))

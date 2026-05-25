"""
Hierarchical orchestrator. Receives a goal, plans task graph, dispatches specialists.
Specialists run in dependency order; results flow back into shared context.
"""
import asyncio
import logging
import uuid
from typing import Any

from backend.core.agent import Agent, AgentContext
from backend.core.bus import AgentBus

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, planner: Agent, specialists: dict[str, Agent]):
        self.planner = planner
        self.specialists = specialists
        self.bus = AgentBus()
        for agent in specialists.values():
            self.bus.register(agent)
        self.bus.register(planner)

    async def _plan(self, goal: str, session_id: str) -> list[dict]:
        """Direct LLM planning call — no agent loop, retries up to 5 times."""
        import json, re
        system = (
            "You are a planning coordinator for an AI startup assistant. Output ONLY a JSON object, no prose.\n\n"
            "SPECIALIST CAPABILITIES — assign tasks ONLY within each agent's scope:\n"
            "  research   — web search, market analysis, competitor research, patent search. Use for: market sizing, industry data, company background.\n"
            "  legal      — draft legal documents (NDAs, privacy policy, terms, founder agreements), generate PDFs. Use for: any legal doc creation.\n"
            "  web        — build and deploy landing pages to Vercel, create GitHub repos, web search. Use for: websites, pages, repos.\n"
            "  marketing  — create social content (reels, TikTok, Meta ads), email campaigns, post to LinkedIn/Gmail. Use for: content, campaigns, posts.\n"
            "  technical  — scaffold GitHub repos, open issues/PRs, create Linear tickets, Notion pages, calendar events. Use for: dev infra, project setup, ticketing.\n"
            "  ops        — project tracking (Linear), fundraising docs, investor email outreach, scheduling (Calendar), Notion SOPs, exec summary PDFs. Use for: coordination, fundraising, comms.\n"
            "  sales      — lead discovery, lead enrichment, outreach sequence generation, inbox warming setup, CRM contact tracking, cold email sending. Use for: finding customers, building pipeline, outbound sales.\n"
            "  design     — wireframes, color palettes, design specifications, logo briefs, UI/UX mockups. Use for: any visual design, brand identity, UX planning.\n\n"
            "Rules:\n"
            "- Only assign agents whose capabilities match the task. Do NOT give web agent research-only tasks — use research for that.\n"
            "- Only include agents whose work is actually needed for this specific goal. Skip agents with nothing relevant to do.\n"
            "- Set depends_on so research always runs first. web/marketing/legal/sales/design can run after research. technical/ops run last or in parallel.\n"
            "- Give each agent a clear, specific instruction scoped to what that agent can actually DO.\n\n"
            "Format:\n"
            '{\"tasks\": [\n'
            '  {\"id\": \"t1\", \"agent\": \"<specialist>\", \"instruction\": \"...\", \"depends_on\": []},\n'
            '  {\"id\": \"t2\", \"agent\": \"<specialist>\", \"instruction\": \"...\", \"depends_on\": [\"t1\"]}\n'
            ']}'
        )
        user = f"Goal: {goal}\n\nOutput the task plan JSON now."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        logger.info("Planner using model=%s base_url=%s", self.planner.model, self.planner._model_base_url)

        for attempt in range(5):
            raw = await asyncio.to_thread(self.planner._call_llm, messages)
            # try to extract tasks array directly or from wrapper
            for pattern in [raw, raw[raw.find("{"):raw.rfind("}")+1]]:
                try:
                    parsed = json.loads(pattern)
                    tasks = parsed.get("tasks", [])
                    if tasks and all("agent" in t for t in tasks):
                        return tasks
                except Exception:
                    pass
            # also try finding tasks: [...] directly
            m = re.search(r'"tasks"\s*:\s*(\[.*?\])', raw, re.DOTALL)
            if m:
                try:
                    tasks = json.loads(m.group(1))
                    if tasks:
                        return tasks
                except Exception:
                    pass
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Invalid format. Output ONLY the JSON object with a tasks array."})
            logger.warning("Planner attempt %d unparseable", attempt + 1)

        return []

    async def run(self, goal: str, founder_id: str, constraints: dict = None, session_id: str = None) -> dict[str, Any]:
        session_id = session_id or uuid.uuid4().hex[:8]
        shared: dict[str, Any] = {"constraints": constraints or {}}

        from backend.core.events import publish
        await publish(session_id, {"type": "goal_start", "goal": goal, "founder_id": founder_id})

        # Proprietary engine: pre-run context (graph + fingerprints + observer alerts)
        proprietary_engine = None
        try:
            from proprietary_agent.engine import ProprietaryEngine
            proprietary_engine = ProprietaryEngine(founder_id=founder_id)
            pre_ctx = await proprietary_engine.pre_run(goal=goal)
            if pre_ctx.get("proprietary_context"):
                shared["proprietary_context"] = pre_ctx["proprietary_context"]
        except Exception as _pe:
            logger.warning("Proprietary engine pre_run skipped: %s", _pe)

        # Step 1: direct planning call (no agent loop — avoids infinite retry)
        tasks = await self._plan(goal, session_id)

        if not tasks:
            logger.warning("Planner failed — running goal directly on all specialists in parallel")
            tasks = [
                {"id": f"t{i}", "agent": name, "instruction": goal, "depends_on": []}
                for i, name in enumerate(self.specialists)
            ]

        from backend.core.events import publish

        await publish(session_id, {
            "type": "plan_done",
            "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in tasks],
            "planner_model": self.planner.model,
        })

        # Step 2: execute tasks in dependency order
        completed: dict[str, dict] = {}

        async def _run_task(task: dict) -> None:
            tid = task["id"]
            agent_name = task["agent"]
            agent = self.specialists.get(agent_name)
            if agent is None:
                logger.error("No specialist named %s", agent_name)
                completed[tid] = {"error": f"unknown agent {agent_name}"}
                await publish(session_id, {"type": "agent_error", "agent": agent_name, "task_id": tid, "error": f"unknown agent {agent_name}"})
                return

            dep_results = {dep: completed.get(dep, {}) for dep in task.get("depends_on", [])}

            # Load agent's prior Obsidian context as readable markdown (not raw JSON)
            vault_context_text = ""
            try:
                from backend.tools.obsidian_logger import format_vault_context
                vault_context_text = await asyncio.to_thread(
                    format_vault_context, agent_name, 3, founder_id
                )
            except Exception:
                pass

            ctx = AgentContext(
                goal=task["instruction"],
                founder_id=founder_id,
                session_id=session_id,
                shared={
                    **shared,
                    "prior_results": dep_results,
                    "prior_vault_notes": vault_context_text,  # readable text, not raw dict
                },
            )
            if proprietary_engine:
                proprietary_engine.on_agent_start(agent_name)

            await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": tid, "instruction": task["instruction"]})
            result = await agent.run(ctx)

            # Mirror review
            if proprietary_engine:
                try:
                    output_str = str(result)
                    mirror_result = proprietary_engine.on_agent_done(agent_name, output_str, session_id)
                    result["mirror_verdict"] = mirror_result.verdict
                    result["mirror_critique"] = mirror_result.critique
                    await publish(session_id, {
                        "type": "mirror_verdict",
                        "agent": agent_name,
                        "verdict": mirror_result.verdict,
                        "critique": mirror_result.critique,
                    })
                    if mirror_result.verdict == "block":
                        logger.warning("Mirror BLOCKED %s — flagging for founder", agent_name)
                except Exception as _me:
                    logger.warning("Mirror review failed for %s: %s", agent_name, _me)

            # Auto-log to Obsidian if agent didn't call obsidian_log itself
            try:
                from backend.tools.obsidian_logger import auto_log_if_missing
                auto_wrote = await asyncio.to_thread(
                    auto_log_if_missing, agent_name, session_id, result, founder_id
                )
                if auto_wrote:
                    logger.debug("Auto-logged Obsidian note for %s", agent_name)
            except Exception as _ole:
                logger.warning("Obsidian auto-log failed for %s: %s", agent_name, _ole)

            completed[tid] = result
            shared[f"result_{tid}"] = result
            logger.info("Task %s (%s) done", tid, agent_name)

        # Topological execution — simple wave scheduler
        remaining = list(tasks)
        in_flight: set[str] = set()

        while remaining or in_flight:
            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.get("depends_on", []))
            ]
            for t in ready:
                remaining.remove(t)
                in_flight.add(t["id"])

            if not ready and not in_flight:
                logger.error("Dependency cycle or missing dep — aborting")
                break

            if not ready:
                await asyncio.sleep(0)
                continue

            await asyncio.gather(*[_run_task(t) for t in ready])
            for t in ready:
                in_flight.discard(t["id"])

        await publish(session_id, {"type": "goal_done", "results": completed})

        # Write session index linking all agent notes
        try:
            from backend.tools.obsidian_logger import obsidian_session_index
            agents_ran = [t["agent"] for t in tasks]
            await asyncio.to_thread(
                obsidian_session_index, session_id, goal, agents_ran, founder_id
            )
        except Exception as _sie:
            logger.warning("Obsidian session index failed: %s", _sie)

        # Proprietary engine: post-run fingerprint
        if proprietary_engine:
            try:
                await proprietary_engine.post_run(
                    session_id=session_id,
                    goal=goal,
                    results={t["agent"]: completed.get(t["id"], {}) for t in tasks},
                )
            except Exception as _pe:
                logger.warning("Proprietary engine post_run failed: %s", _pe)

        return {"session_id": session_id, "results": completed, "shared": shared}

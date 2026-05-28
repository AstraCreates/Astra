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

    _AGENT_CAPS = (
        "SPECIALIST CAPABILITIES:\n"
        "  research   — web search, market analysis, competitor research, patent search.\n"
        "  legal      — draft legal docs (privacy policy, terms, NDAs, founder agreements), generate PDFs.\n"
        "  web        — build and deploy landing pages to Vercel via GitHub + Claude Code.\n"
        "  marketing  — create social content (reels, TikTok, Meta ads), email campaigns.\n"
        "  technical  — build COMPLETE working MVP: GitHub repo, 6 rounds of Claude Code (frontend+backend+auth+DB), deploy to Vercel.\n"
        "  ops        — fundraising docs, investor outreach, calendar scheduling, Notion SOPs, exec summary PDFs.\n"
        "  sales      — lead discovery, enrichment, outreach sequences, CRM tracking.\n"
        "  design     — wireframes, color palettes, design specs, logo briefs, UI/UX mockups.\n"
    )

    @staticmethod
    def _is_web_fallback_html(html: str) -> bool:
        if not isinstance(html, str):
            return False
        h = html.lower()
        fallback_markers = (
            "astra-fallback-template",
            "--bg: #06080f",
            "--bg2: #0d1117",
            "define your goal",
            "astra builds it",
        )
        return any(marker in h for marker in fallback_markers)

    async def _parse_tasks(self, raw: str) -> list[dict]:
        import json, re
        for pattern in [raw, raw[raw.find("{"):raw.rfind("}")+1]]:
            try:
                parsed = json.loads(pattern)
                tasks = parsed.get("tasks", [])
                if tasks and all("agent" in t for t in tasks):
                    seen: set[str] = set()
                    return [t for t in tasks if t["agent"] not in seen and not seen.add(t["agent"])]  # type: ignore
            except Exception:
                pass
        m = re.search(r'"tasks"\s*:\s*(\[.*?\])', raw, re.DOTALL)
        if m:
            try:
                tasks = json.loads(m.group(1))
                if tasks:
                    seen: set[str] = set()
                    return [t for t in tasks if t.get("agent") not in seen and not seen.add(t.get("agent", ""))]  # type: ignore
            except Exception:
                pass
        return []

    async def _llm_plan(self, messages: list[dict]) -> list[dict]:
        for attempt in range(5):
            raw = await asyncio.to_thread(self.planner._call_llm, messages)
            tasks = await self._parse_tasks(raw)
            if tasks:
                return tasks
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Invalid format. Output ONLY valid JSON with a tasks array."})
            logger.warning("Planner attempt %d unparseable", attempt + 1)
        return []

    async def _initial_plan(self, goal: str) -> list[dict]:
        """Phase 1: decide which agents to use. Always puts research first if relevant."""
        system = (
            "You are a planning coordinator for an AI startup assistant. Output ONLY a JSON object, no prose.\n\n"
            + self._AGENT_CAPS +
            "\nRules:\n"
            "- Each agent appears AT MOST ONCE.\n"
            "- Only include agents whose work is actually needed for this goal.\n"
            "- ALWAYS include research as the first task (id: t1, depends_on: []).\n"
            "- ALWAYS include web — every startup needs a public landing page.\n"
            "- ALWAYS include technical — every startup needs an MVP codebase.\n"
            "- All other agents MUST have depends_on: [\"t1\"] — they wait for research.\n"
            "- Instructions at this stage are brief placeholders — they will be rewritten with research context later.\n\n"
            "Format: {\"tasks\": [{\"id\": \"t1\", \"agent\": \"research\", \"instruction\": \"...\", \"depends_on\": []}, ...]}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Goal: {goal}\n\nOutput the task plan JSON now."},
        ]
        return await self._llm_plan(messages)

    async def _replan_with_research(self, goal: str, research_result: dict, agents_needed: list[str]) -> list[dict]:
        """Phase 2: replan non-research agents with full research context. Returns detailed instructions."""
        import json
        research_summary = ""
        # Priority 1: extract the structured obsidian report if present
        obs = (
            research_result.get("obsidian_content")
            or research_result.get("formatted_text")
            or research_result.get("report")
            or ""
        )
        if isinstance(obs, str) and len(obs) > 200:
            research_summary = obs[:6000]
        else:
            # Fallback: concatenate all string fields with a generous budget
            for k, v in research_result.items():
                if v and isinstance(v, str) and len(v) > 10:
                    research_summary += f"\n### {k}\n{v[:1500]}"
                    if len(research_summary) > 6000:
                        break
            if not research_summary:
                research_summary = json.dumps(research_result, default=str)[:4000]

        system = (
            "You are a planning coordinator. Research on the goal is complete. "
            "Use the research findings to write DETAILED, SPECIFIC task instructions for each specialist.\n\n"
            + self._AGENT_CAPS +
            "\nRules:\n"
            "- Each agent appears AT MOST ONCE. All run in parallel (depends_on: []).\n"
            "- Instructions MUST reference specific findings from the research: competitor names, market size, tech stack choices, target users, pricing strategy, etc.\n"
            "- Instructions must be 2-4 sentences. No generic placeholders. No 'SaaS platform' — use the actual product name and specifics.\n"
            "- technical agent instruction MUST include: product name, core features to build, auth approach, DB schema hint.\n"
            "- web agent instruction MUST include: product name, hero copy, key value props from research, color/style direction.\n"
            "- marketing agent instruction MUST include: target persona from research, specific pain points, competitor differentiation angle.\n\n"
            "Format: {\"tasks\": [{\"id\": \"t1\", \"agent\": \"<name>\", \"instruction\": \"<detailed>\", \"depends_on\": []}]}"
        )
        agents_str = ", ".join(agents_needed)
        user = (
            f"Goal: {goal}\n\n"
            f"Agents to assign: {agents_str}\n\n"
            f"Research findings:\n{research_summary}\n\n"
            "Write detailed task instructions for each agent using the research above."
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self._llm_plan(messages)

    async def _generate_detailed_plan(self, goal: str, research_summary: str, tasks: list[dict]) -> list[dict]:
        """Generate a rich branching plan tree for the Plan overlay UI."""
        import json
        agents_str = ", ".join(t["agent"] for t in tasks)
        task_instructions = "\n".join(f"- {t['agent']}: {t['instruction']}" for t in tasks)
        system = (
            "You are a startup execution planner. Generate a detailed branching plan tree.\n"
            "Output ONLY valid JSON — no prose, no markdown fences.\n\n"
            "Each node has:\n"
            "  id: unique string\n"
            "  agent: agent name (from the task list)\n"
            "  title: short phase title (4-6 words)\n"
            "  description: 1-2 sentences of exactly what will happen, referencing specific research findings\n"
            "  steps: array of 3-6 concrete subtask strings (each 10-25 words, specific not generic)\n"
            "  depends_on: [] or [\"id\"] of upstream node this waits for\n"
            "  estimated_time: e.g. '2-4 hours', '1 day'\n\n"
            "Format: {\"nodes\": [{...}, ...]}\n"
            "Rules:\n"
            "- 1 node per agent. All nodes must be present.\n"
            "- steps must be concrete: name real tools, real files, real decisions.\n"
            "- Use actual data from research: competitor names, market size, tech choices, pricing.\n"
            "- No placeholder text. No 'TBD'. No 'lorem ipsum'.\n"
        )
        user = (
            f"Goal: {goal}\n\n"
            f"Agents: {agents_str}\n\n"
            f"Agent instructions:\n{task_instructions}\n\n"
            f"Research findings (use specific details):\n{research_summary[:5000]}\n\n"
            "Generate the detailed branching plan tree now."
        )
        for attempt in range(3):
            raw = await asyncio.to_thread(self.planner._call_llm, [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
            try:
                # strip markdown fences
                import re as _re
                clean = _re.sub(r"```(?:json)?|```", "", raw).strip()
                parsed = json.loads(clean)
                nodes = parsed.get("nodes", [])
                if nodes and all("agent" in n and "steps" in n for n in nodes):
                    return nodes
            except Exception:
                pass
        return []

    async def _generate_company_name(self, goal: str) -> str:
        """Extract or invent a company/product name from the goal."""
        import re
        # Explicit name patterns: frontend sends "Company name: X." or "called X", quoted names
        for pattern in [
            r'[Cc]ompany\s+name[:\s]+([A-Za-z][a-zA-Z0-9]{2,})',
            r'(?:called|named|building)\s+"?([A-Z][a-zA-Z0-9]{2,})"?',
            r'"([A-Z][a-zA-Z0-9]{2,20})"',
        ]:
            m = re.search(pattern, goal)
            if m:
                return m.group(1).strip()
        # Generate one
        try:
            from openai import OpenAI
            from backend.config import settings
            client = OpenAI(
                base_url=settings.planner_model_base_url or "https://api.deepinfra.com/v1/openai",
                api_key=settings.planner_model_api_key or settings.agent_model_api_key,
            )
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model="deepseek-ai/DeepSeek-V4-Flash",
                messages=[
                    {"role": "system", "content": (
                        "Output ONLY a single company/product name for this startup idea. "
                        "1-2 words max. CamelCase. Memorable, domain-friendly, not generic. "
                        "No explanation. No punctuation. Just the name."
                    )},
                    {"role": "user", "content": goal[:300]},
                ],
                max_tokens=10,
                temperature=0.85,
            )
            raw = (resp.choices[0].message.content or "").strip().split()[0]
            name = re.sub(r"[^a-zA-Z0-9]", "", raw)
            if len(name) >= 3:
                return name
        except Exception as e:
            logger.warning("Company name generation failed: %s", e)
        return "Venture"

    async def _expand_goal(self, goal: str, session_id: str) -> str:
        """Expand a terse founder prompt into a rich, specific goal using Qwen3-235B."""
        from backend.config import settings
        from backend.core.events import publish
        system = (
            "You are a startup idea expander. A founder gave you a short goal. "
            "Expand it into 3-5 sentences that are specific and actionable:\n"
            "- Name the target user and their exact pain point\n"
            "- Name 2-3 key competitors and what gap exists\n"
            "- Describe the core product differentiator\n"
            "- Suggest a monetization model\n"
            "Output ONLY the expanded goal. No headers, no lists, no meta-commentary."
        )
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=settings.planner_model_base_url or "https://api.deepinfra.com/v1/openai",
                api_key=settings.planner_model_api_key or settings.agent_model_api_key,
            )
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model="deepseek-ai/DeepSeek-V4-Flash",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": goal},
                ],
                max_tokens=400,
                temperature=0.7,
            )
            expanded = resp.choices[0].message.content.strip()
            if expanded and len(expanded) > len(goal):
                logger.info("Goal expanded: %s → %s", goal[:60], expanded[:80])
                await publish(session_id, {"type": "goal_expanded", "original": goal, "expanded": expanded})
                return expanded
        except Exception as e:
            logger.warning("Goal expansion failed (%s) — using original", e)
        return goal

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
            logger.warning("Proprietary engine pre_run skipped: %s", _pe, exc_info=True)

        try:
            from backend.tools.company_brain import company_brain_context, sync_company_brain
            await asyncio.to_thread(sync_company_brain, founder_id, None)
            shared["company_brain_context"] = await asyncio.to_thread(
                company_brain_context, founder_id, goal, 8
            )
        except Exception as _cb:
            logger.warning("Company brain pre-run context skipped: %s", _cb)

        from backend.core.events import publish

        # Generate company name before expansion so it feeds into expanded goal
        company_name = await self._generate_company_name(goal)
        shared["company_name"] = company_name
        await publish(session_id, {"type": "company_name", "name": company_name})
        logger.info("Company name: %s", company_name)

        # Expand the goal with Qwen3-235B before anything else
        goal = await self._expand_goal(goal, session_id)

        # Phase 1: initial plan — research always runs first
        initial_tasks = await self._initial_plan(goal)
        if not initial_tasks:
            initial_tasks = [{"id": "t1", "agent": "research", "instruction": f"Research the market and competitive landscape for: {goal}", "depends_on": []}]

        _RESEARCH_AGENTS = {
            "research",
            "research_competitors",
            "research_execution",
        }
        research_task = next((t for t in initial_tasks if t["agent"] == "research"), None)
        other_agents_initial = [t for t in initial_tasks if t["agent"] not in _RESEARCH_AGENTS]

        # Force-include web + technical if planner omitted them
        _existing_agents = {t["agent"] for t in other_agents_initial}
        _mandatory = [
            ("web", "Build and deploy a public landing page for this product."),
            ("technical", f"Build a complete working MVP for: {goal}"),
        ]
        for _i, (_ag, _instr) in enumerate(_mandatory):
            if _ag not in _existing_agents and _ag in self.specialists:
                other_agents_initial.append({"id": f"forced_{_ag}", "agent": _ag, "instruction": _instr, "depends_on": []})

        # Run only configured research specialists in parallel.
        research_instruction = research_task["instruction"] if research_task else f"Research market, competitors, and execution strategy for: {goal}"
        candidate_research = [
            ("r_market",          "research"),
            ("r_competitors",     "research_competitors"),
            ("r_execution",       "research_execution"),
        ]
        parallel_research_tasks = [
            {"id": tid, "agent": agent_name, "instruction": research_instruction, "depends_on": []}
            for tid, agent_name in candidate_research
            if agent_name in self.specialists
        ]

        # Emit initial plan
        await publish(session_id, {
            "type": "plan_done",
            "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in parallel_research_tasks + other_agents_initial],
            "planner_model": self.planner.model,
        })

        # Step 2: execute tasks in dependency order
        completed: dict[str, dict] = {}
        tasks = initial_tasks  # will be replaced after research

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

            # Web quality gate: retry with stricter instructions when fallback template is detected.
            if agent_name == "web":
                retry_count = 0
                while retry_count < 2:
                    html_result = result.get("html") if isinstance(result, dict) else None
                    used_fallback = isinstance(html_result, str) and self._is_web_fallback_html(html_result)
                    if not used_fallback:
                        break
                    retry_count += 1
                    await publish(session_id, {
                        "type": "agent_action_result",
                        "agent": agent_name,
                        "tool": "generate_landing_page_html",
                        "result": {"error": f"fallback template detected (attempt {retry_count}); rerunning with stricter instruction"},
                    })
                    retry_ctx = AgentContext(
                        goal=(
                            task["instruction"]
                            + "\n\nSTRICT QUALITY RETRY: The previous HTML used fallback template output. "
                              "You MUST regenerate custom HTML with explicit brand colors/fonts and concrete product copy. "
                              "Use semantic sections and realistic metrics. Do not return fallback/template output."
                        ),
                        founder_id=founder_id,
                        session_id=session_id,
                        shared={**ctx.shared, "web_quality_retry": True, "web_quality_retry_count": retry_count},
                    )
                    await publish(session_id, {
                        "type": "agent_start",
                        "agent": agent_name,
                        "task_id": f"{tid}_retry_{retry_count}",
                        "instruction": f"Quality retry {retry_count} after fallback detection",
                    })
                    retry_result = await agent.run(retry_ctx)
                    if isinstance(retry_result, dict):
                        result = retry_result
                html_result = result.get("html") if isinstance(result, dict) else None
                if isinstance(html_result, str) and self._is_web_fallback_html(html_result):
                    if isinstance(result, dict):
                        result["web_quality_error"] = "fallback_template_persisted_after_retries"
                    await publish(session_id, {
                        "type": "agent_error",
                        "agent": agent_name,
                        "task_id": tid,
                        "error": "Web output still used fallback template after retries",
                    })

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

            if isinstance(result, dict) and "agent" not in result:
                result["agent"] = agent_name
            completed[tid] = result
            shared[f"result_{tid}"] = result
            shared[f"result_{agent_name}"] = result  # also keyed by agent name for downstream context
            logger.info("Task %s (%s) done", tid, agent_name)

        # Phase A: run all 3 research agents in parallel
        await asyncio.gather(*[_run_task(t) for t in parallel_research_tasks])

        if True:
            # Phase B: merge all research notes then replan
            from backend.tools.obsidian_logger import _note_path
            research_result = {}
            merged_notes: list[str] = []
            _seen_note_paths: set[str] = set()
            for rt in parallel_research_tasks:
                research_result.update(completed.get(rt["id"], {}))
                try:
                    # _2/_3/_4 variants write to same base agent name — deduplicate
                    import re as _re
                    base_agent = _re.sub(r"_\d+$", "", rt["agent"])
                    note_file = _note_path(base_agent, session_id, founder_id)
                    note_key = str(note_file)
                    if note_file.exists() and note_key not in _seen_note_paths:
                        _seen_note_paths.add(note_key)
                        merged_notes.append(f"## {base_agent.upper()}\n\n{note_file.read_text()}")
                except Exception as _re:
                    logger.debug("Could not read %s obsidian note: %s", rt["agent"], _re)
            if merged_notes:
                research_result["obsidian_content"] = "\n\n---\n\n".join(merged_notes)
            agents_needed = [t["agent"] for t in other_agents_initial]
            if agents_needed:
                detailed_tasks = await self._replan_with_research(goal, research_result, agents_needed)
                if detailed_tasks:
                    # Re-emit updated plan with detailed instructions
                    await publish(session_id, {
                        "type": "plan_done",
                        "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in detailed_tasks],
                        "planner_model": self.planner.model,
                        "phase": "detailed",
                    })
                    # Emit rich branching plan tree in background — don't block agents
                    async def _bg_detailed_plan():
                        try:
                            _rs = research_result.get("obsidian_content") or ""
                            if not _rs:
                                import json as _json
                                _rs = _json.dumps(research_result, default=str)[:5000]
                            tree_nodes = await self._generate_detailed_plan(goal, _rs, detailed_tasks)
                            if tree_nodes:
                                await publish(session_id, {"type": "detailed_plan", "nodes": tree_nodes})
                        except Exception as _dp_err:
                            logger.warning("detailed_plan generation failed: %s", _dp_err)
                    asyncio.create_task(_bg_detailed_plan())
                    tasks = parallel_research_tasks + detailed_tasks
                else:
                    tasks = parallel_research_tasks + other_agents_initial

            remaining = [t for t in tasks if t["agent"] not in _RESEARCH_AGENTS]

        # design must finish before web (web uses brand colors/fonts from design output)
        _design_task = next((t for t in remaining if t["agent"] == "design"), None)
        _web_task = next((t for t in remaining if t["agent"] == "web"), None)
        if _design_task and _web_task:
            _web_task.setdefault("depends_on", [])
            if _design_task["id"] not in _web_task["depends_on"]:
                _web_task["depends_on"].append(_design_task["id"])

        # Run remaining agents in parallel (all depends_on research which is done)
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
            from backend.tools.obsidian_logger import obsidian_session_index, obsidian_backend_log
            from backend.core.events import _event_log
            agents_ran = [t["agent"] for t in tasks]
            await asyncio.to_thread(
                obsidian_session_index, session_id, goal, agents_ran, founder_id
            )
            await asyncio.to_thread(
                obsidian_backend_log,
                session_id,
                founder_id,
                goal,
                _event_log.get(session_id, []),
                completed,
            )
        except Exception as _sie:
            logger.warning("Obsidian session log/index failed: %s", _sie)

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

    async def continue_run(
        self,
        instruction: str,
        founder_id: str,
        prior_session_id: str,
        agents: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Continue work on an existing company. Loads full vault context from prior sessions,
        runs the specified agents (or plans which agents to run) with the new instruction.
        """
        session_id = session_id or uuid.uuid4().hex[:8]
        from backend.core.events import publish
        from backend.tools.obsidian_logger import format_vault_context, _note_path

        await publish(session_id, {"type": "goal_start", "goal": instruction, "founder_id": founder_id, "continue_from": prior_session_id})

        # Load all prior vault notes for this founder to give full company context
        shared: dict[str, Any] = {"prior_session_id": prior_session_id}
        try:
            vault_summary_parts = []
            for agent_name in self.specialists:
                ctx_text = await asyncio.to_thread(format_vault_context, agent_name, 5, founder_id)
                if ctx_text:
                    vault_summary_parts.append(f"## {agent_name}\n{ctx_text}")
            shared["company_vault_context"] = "\n\n".join(vault_summary_parts)
        except Exception as _ve:
            logger.warning("Vault load failed: %s", _ve)

        try:
            from backend.tools.company_brain import company_brain_context, sync_company_brain
            await asyncio.to_thread(sync_company_brain, founder_id, None)
            shared["company_brain_context"] = await asyncio.to_thread(
                company_brain_context, founder_id, instruction, 10
            )
        except Exception as _cb:
            logger.warning("Company brain continuation context skipped: %s", _cb)

        # If agents explicitly specified, skip planning
        if agents:
            tasks = [
                {"id": f"c_{a}", "agent": a, "instruction": instruction, "depends_on": []}
                for a in agents if a in self.specialists
            ]
        else:
            # Ask planner which agents are needed for this follow-up
            system = (
                "You are a planning coordinator. A founder wants to continue working on their company.\n"
                + self._AGENT_CAPS
                + "\nReturn a task plan JSON for the agents needed. All depends_on: [].\n"
                "Format: {\"tasks\": [{\"id\": \"c1\", \"agent\": \"<name>\", \"instruction\": \"<specific>\", \"depends_on\": []}]}"
            )
            user = (
                f"Follow-up instruction: {instruction}\n\n"
                f"Prior company context (vault notes):\n{shared.get('company_vault_context', '')[:4000]}\n\n"
                "Which agents should handle this? Write their specific instructions referencing the prior context."
            )
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            tasks = await self._llm_plan(messages)
            if not tasks:
                tasks = [{"id": "c1", "agent": "technical", "instruction": instruction, "depends_on": []}]

        await publish(session_id, {
            "type": "plan_done",
            "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in tasks],
            "planner_model": self.planner.model,
        })

        completed: dict[str, dict] = {}

        async def _run_task(task: dict) -> None:
            tid = task["id"]
            agent_name = task["agent"]
            agent = self.specialists.get(agent_name)
            if agent is None:
                completed[tid] = {"error": f"unknown agent {agent_name}"}
                return
            vault_ctx = await asyncio.to_thread(format_vault_context, agent_name, 5, founder_id)
            ctx = AgentContext(
                goal=task["instruction"],
                founder_id=founder_id,
                session_id=session_id,
                shared={
                    **shared,
                    "prior_vault_notes": vault_ctx,
                    "is_continuation": True,
                    "prior_session_id": prior_session_id,
                },
            )
            await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": tid, "instruction": task["instruction"]})
            result = await agent.run(ctx)
            try:
                from backend.tools.obsidian_logger import auto_log_if_missing
                await asyncio.to_thread(auto_log_if_missing, agent_name, session_id, result, founder_id)
            except Exception:
                pass
            completed[tid] = result
            shared[f"result_{agent_name}"] = result
            logger.info("Continue task %s (%s) done", tid, agent_name)

        await asyncio.gather(*[_run_task(t) for t in tasks])
        await publish(session_id, {"type": "goal_done", "results": completed})
        try:
            from backend.tools.obsidian_logger import obsidian_backend_log
            from backend.core.events import _event_log
            await asyncio.to_thread(
                obsidian_backend_log,
                session_id,
                founder_id,
                instruction,
                _event_log.get(session_id, []),
                completed,
            )
        except Exception as _bl:
            logger.warning("Continuation backend log failed: %s", _bl)
        return {"session_id": session_id, "results": completed}

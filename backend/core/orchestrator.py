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

    async def _replan_with_research(self, goal: str, research_result: dict, agents_needed: list[str], stack_context: str = "") -> list[dict]:
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
            f"Stack context:\n{stack_context}\n\n"
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
                api_key=settings.openrouter_api_key or settings.planner_model_api_key or settings.agent_model_api_key,
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
        """Expand a terse founder prompt using the planner model (fast, low latency)."""
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
                api_key=settings.openrouter_api_key or settings.planner_model_api_key or settings.agent_model_api_key,
            )
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.planner_model_name,  # Llama-4-Scout — fast, cheap
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

    @staticmethod
    def _artifact_preview(result: Any, artifact_key: str) -> str:
        """Create a compact preview for a typed stack artifact event."""
        if not isinstance(result, dict):
            return str(result)[:280]
        candidates = [
            result.get(artifact_key),
            result.get("summary"),
            result.get("output_summary"),
            result.get("formatted_text"),
            result.get("report"),
            result.get("text"),
            result.get("url"),
            result.get("preview_url"),
            result.get("html"),
        ]
        for candidate in candidates:
            if candidate:
                if isinstance(candidate, str):
                    return candidate.replace("\n", " ").strip()[:360]
                return str(candidate)[:360]
        return str(result)[:360]

    async def _publish_stack_artifacts(
        self,
        session_id: str,
        task: dict,
        result: Any,
        stack_template: Any,
    ) -> None:
        """Emit typed artifact events for artifacts owned by the completed task."""
        from backend.core.events import publish

        agent_name = task.get("agent", "")
        expected_keys = task.get("expected_artifacts") or []
        if not expected_keys and stack_template:
            expected_keys = [
                artifact.key
                for artifact in getattr(stack_template, "artifacts", [])
                if artifact.owner_agent == agent_name
            ]
        artifact_by_key = {
            artifact.key: artifact
            for artifact in getattr(stack_template, "artifacts", [])
        }
        for artifact_key in expected_keys:
            artifact = artifact_by_key.get(artifact_key)
            if not artifact:
                continue
            await publish(session_id, {
                "type": "stack_artifact",
                "artifact": {
                    "key": artifact.key,
                    "title": artifact.title,
                    "owner_agent": artifact.owner_agent,
                    "description": artifact.description,
                    "required": artifact.required,
                    "status": "ready",
                    "task_id": task.get("id", ""),
                    "preview": self._artifact_preview(result, artifact.key),
                },
            })

    async def _publish_outcomes(self, session_id: str, task: dict, result: Any) -> None:
        """Emit measurable Outcome Ledger events from a completed task result."""
        from backend.core.events import publish
        from backend.outcomes import build_outcome_events

        for outcome in build_outcome_events(task.get("agent", ""), result, task):
            await publish(session_id, {"type": "outcome_recorded", "outcome": outcome})

    async def _persist_brain_record(
        self,
        founder_id: str,
        title: str,
        content: str,
        kind: str,
        canonical: bool = False,
        stale_risk: str = "medium",
    ) -> None:
        """Best-effort write of operator records into the Company Brain."""
        try:
            from backend.tools.company_brain import add_company_brain_record
            await asyncio.to_thread(
                add_company_brain_record,
                founder_id=founder_id,
                source="astra",
                title=title,
                content=content,
                kind=kind,
                canonical=canonical,
                stale_risk=stale_risk,
            )
        except Exception as exc:
            logger.warning("Company brain record write failed for %s: %s", title, exc)

    async def run(self, goal: str, founder_id: str, constraints: dict = None, session_id: str = None) -> dict[str, Any]:
        session_id = session_id or uuid.uuid4().hex[:8]
        shared: dict[str, Any] = {"constraints": constraints or {}}

        from backend.core.events import publish
        await publish(session_id, {"type": "goal_start", "goal": goal, "founder_id": founder_id})

        from backend.stacks import build_approval_queue, build_stack_execution_blueprint, build_stack_execution_contract, build_stack_manifest, build_stack_operating_plan, get_stack_template, task_execution_guidance
        stack_template = get_stack_template((constraints or {}).get("stack_id"))
        approval_queue = build_approval_queue(stack_template)
        operating_plan = build_stack_operating_plan(stack_template, goal)
        stack_manifest = build_stack_manifest(stack_template, goal)
        stack_execution_contract = build_stack_execution_contract(stack_template)
        stack_execution_blueprint = build_stack_execution_blueprint(stack_template, goal)
        shared["stack_template"] = stack_template.to_public_dict()
        shared["approval_queue"] = approval_queue
        shared["stack_operating_plan"] = operating_plan
        shared["stack_manifest"] = stack_manifest
        shared["stack_execution_contract"] = stack_execution_contract
        shared["stack_execution_blueprint"] = stack_execution_blueprint
        stack_context = (
            f"{stack_template.name}: {stack_template.primary_outcome}\n"
            f"Target user: {stack_template.target_user}\n"
            f"North star: {stack_execution_contract.get('north_star', '')}\n"
            f"Quality gates: " + "; ".join(stack_execution_contract.get("quality_gates", [])[:4]) + "\n"
            f"Expected artifacts: "
            + ", ".join(a.title for a in stack_template.artifacts)
            + "\nConnector requirements: "
            + ", ".join(
                f"{connector.label} ({connector.category})"
                for connector in getattr(stack_template, "connector_requirements", [])
            )
        )
        await publish(session_id, {
            "type": "stack_selected",
            "stack": stack_template.to_public_dict(),
        })
        await publish(session_id, {
            "type": "stack_operating_plan",
            "operating_plan": operating_plan,
        })
        await publish(session_id, {
            "type": "stack_manifest",
            "manifest": stack_manifest,
        })
        await publish(session_id, {
            "type": "stack_execution_contract",
            "execution_contract": stack_execution_contract,
        })
        await publish(session_id, {
            "type": "stack_execution_blueprint",
            "execution_blueprint": stack_execution_blueprint,
        })
        await publish(session_id, {
            "type": "stack_approval_queue",
            "approval_queue": approval_queue,
        })
        for lane in stack_execution_blueprint.get("lanes", []):
            await publish(session_id, {
                "type": "stack_lane_status",
                "lane_id": lane.get("id"),
                "agent": lane.get("agent"),
                "status": "waiting",
                "phase": lane.get("phase"),
                "title": lane.get("title"),
                "expected_artifacts": lane.get("deliverables", []),
                "next_actor": "agent",
            })

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
            # Reduced timeout: company brain is nice-to-have, not blocking
            shared["company_brain_context"] = await asyncio.wait_for(
                asyncio.to_thread(company_brain_context, founder_id, goal, 4),
                timeout=3.0,
            )
        except (asyncio.TimeoutError, Exception) as _cb:
            logger.warning("Company brain pre-run context skipped: %s", _cb)

        from backend.core.events import publish

        _bypass_planner = bool((constraints or {}).get("bypass_planner"))

        if _bypass_planner:
            # Fast path for testing — skip all LLM pre-run calls, go straight to agent dispatch
            company_name = (constraints or {}).get("company_name") or "TestCo"
            shared["company_name"] = company_name
            await publish(session_id, {"type": "company_name", "name": company_name})
            logger.info("bypass_planner=True — skipping company_name LLM, genome, goal_expand")
        else:
            # Run company name generation and goal expansion in parallel
            company_name, goal = await asyncio.gather(
                self._generate_company_name(goal),
                self._expand_goal(goal, session_id),
            )
            shared["company_name"] = company_name
            operating_plan = build_stack_operating_plan(stack_template, goal, company_name)
            stack_manifest = build_stack_manifest(stack_template, goal, company_name)
            stack_execution_blueprint = build_stack_execution_blueprint(stack_template, goal, company_name)
            shared["stack_operating_plan"] = operating_plan
            shared["stack_manifest"] = stack_manifest
            shared["stack_execution_blueprint"] = stack_execution_blueprint
            await publish(session_id, {"type": "company_name", "name": company_name})
            await publish(session_id, {"type": "stack_operating_plan", "operating_plan": operating_plan})
            await publish(session_id, {"type": "stack_manifest", "manifest": stack_manifest})
            await publish(session_id, {"type": "stack_execution_contract", "execution_contract": build_stack_execution_contract(stack_template)})
            await publish(session_id, {"type": "stack_execution_blueprint", "execution_blueprint": stack_execution_blueprint})
            for lane in stack_execution_blueprint.get("lanes", []):
                await publish(session_id, {
                    "type": "stack_lane_status",
                    "lane_id": lane.get("id"),
                    "agent": lane.get("agent"),
                    "status": "waiting",
                    "phase": lane.get("phase"),
                    "title": lane.get("title"),
                    "expected_artifacts": lane.get("deliverables", []),
                    "next_actor": "agent",
                })
            try:
                import json as _json
                await self._persist_brain_record(
                    founder_id=founder_id,
                    title=f"Stack Operating Plan - {company_name}",
                    content=_json.dumps(operating_plan, indent=2),
                    kind="operating_plan",
                    canonical=True,
                    stale_risk="low",
                )
                await self._persist_brain_record(
                    founder_id=founder_id,
                    title=f"Agent Department Manifest - {company_name}",
                    content=_json.dumps(stack_manifest, indent=2),
                    kind="department_manifest",
                    canonical=True,
                    stale_risk="low",
                )
            except Exception as _op:
                logger.warning("Stack manifest brain record failed: %s", _op)
            logger.info("Company name: %s", company_name)

            try:
                from backend.tools.company_brain import add_company_brain_record
                await asyncio.to_thread(
                    add_company_brain_record,
                    founder_id=founder_id,
                    source="astra",
                    title="Company Identity",
                    content=f"Company name: {company_name}\nFounder goal: {goal}\nSession: {session_id}",
                    kind="fact",
                    canonical=True,
                    stale_risk="low",
                )
            except Exception as _bi:
                logger.warning("Brain identity record failed: %s", _bi)

            # Build genome in background — doesn't block agents from starting
            async def _build_genome_bg():
                try:
                    from backend.genome import build_company_genome
                    genome = build_company_genome(
                        session_id=session_id, founder_id=founder_id,
                        company_name=company_name, goal=goal,
                        stack_template=stack_template,
                        brain_context=str(shared.get("company_brain_context", "")),
                    )
                    shared["company_genome"] = genome
                    await publish(session_id, {"type": "company_genome", "genome": genome})
                except Exception as _ge:
                    logger.warning("Company genome build failed: %s", _ge)
            asyncio.create_task(_build_genome_bg())

        # Phase 1: stack plan — default to the productized outcome stack.
        _agent_filter: list[str] | None = (constraints or {}).get("agents") or (constraints or {}).get("agent_filter") or None
        _is_custom = bool(_agent_filter)

        initial_tasks = [
            task for task in stack_template.build_tasks(goal)
            if task["agent"] in self.specialists
        ]
        task_template_by_id = {task.id: task for task in stack_template.tasks}
        for task in initial_tasks:
            template_task = task_template_by_id.get(task.get("id", ""))
            if template_task:
                task["instruction"] = f"{task['instruction']}\n\n{task_execution_guidance(stack_template, template_task)}"
        if not initial_tasks:
            initial_tasks = await self._initial_plan(goal)
        if not initial_tasks:
            initial_tasks = [{"id": "t1", "agent": "research", "instruction": f"Research the market and competitive landscape for: {goal}", "depends_on": []}]

        # Custom stack: keep only user-selected agents (research always required)
        if _is_custom:
            _allowed = set(_agent_filter) | {"research"}
            initial_tasks = [t for t in initial_tasks if t["agent"] in _allowed]
            if not initial_tasks:
                initial_tasks = [{"id": "t1", "agent": a, "instruction": goal, "depends_on": []} for a in _agent_filter if a in self.specialists]

        _RESEARCH_AGENTS = {
            "research",
            "research_competitors",
            "research_execution",
        }
        stack_task_by_agent = {t.agent: t for t in stack_template.tasks}
        research_task = next((t for t in initial_tasks if t["agent"] == "research"), None)
        other_agents_initial = [t for t in initial_tasks if t["agent"] not in _RESEARCH_AGENTS]

        # Force-include web + technical if planner omitted them (skip for custom stacks)
        if not _is_custom:
            _existing_agents = {t["agent"] for t in other_agents_initial}
            _mandatory = [
                ("web", "Build and deploy a public landing page for this product."),
                ("technical", f"Build a complete working MVP for: {goal}"),
            ]
            for _i, (_ag, _instr) in enumerate(_mandatory):
                if _ag not in _existing_agents and _ag in self.specialists:
                    other_agents_initial.append({"id": f"forced_{_ag}", "agent": _ag, "instruction": _instr, "depends_on": []})

        # bypass_planner: skip research wave + replan, dispatch requested agents immediately
        if _bypass_planner and _is_custom:
            _test_model = (constraints or {}).get("test_model")
            _original_models: dict[str, str] = {}
            if _test_model:
                for _name, _ag in self.specialists.items():
                    _original_models[_name] = _ag.model
                    _ag.model = _test_model
            bypass_tasks = [
                {"id": f"bp_{a}", "agent": a, "instruction": goal, "depends_on": []}
                for a in (_agent_filter or [])
                if a in self.specialists
            ]
            await publish(session_id, {
                "type": "plan_done",
                "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in bypass_tasks],
                "planner_model": "bypass",
            })
            completed: dict[str, dict] = {}
            stack_lane_by_agent = {
                lane.get("agent"): lane
                for lane in (shared.get("stack_execution_blueprint") or {}).get("lanes", [])
                if lane.get("agent")
            }

            async def _run_task(task: dict) -> None:  # noqa: F811
                tid = task["id"]
                agent_name = task["agent"]
                agent = self.specialists.get(agent_name)
                stack_lane = stack_lane_by_agent.get(agent_name, {})
                lane_id = stack_lane.get("id") or task.get("id")
                if agent is None:
                    completed[tid] = {"error": f"unknown agent {agent_name}"}
                    return
                dep_results = {}
                vault_context_text = ""
                try:
                    from backend.tools.obsidian_logger import format_vault_context
                    vault_context_text = await asyncio.wait_for(
                        asyncio.to_thread(format_vault_context, agent_name, 3, founder_id),
                        timeout=5.0,
                    )
                except Exception:
                    pass
                ctx = AgentContext(
                    goal=goal,
                    session_id=session_id,
                    founder_id=founder_id,
                    task_id=tid,
                    shared=shared,
                    dep_results=dep_results,
                    vault_context=vault_context_text,
                    bypass_approvals=True,  # bypass_planner path skips approval gates for testing
                )
                await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": tid, "lane_id": lane_id})
                try:
                    result = await agent.run(ctx)
                    completed[tid] = result
                    await publish(session_id, {"type": "agent_done", "agent": agent_name, "task_id": tid, "result": result})
                except Exception as _agent_exc:
                    err_msg = str(_agent_exc)[:400]
                    completed[tid] = {"error": err_msg}
                    await publish(session_id, {"type": "agent_error", "agent": agent_name, "task_id": tid, "error": err_msg})

            await asyncio.gather(*[_run_task(t) for t in bypass_tasks])
            await publish(session_id, {"type": "goal_done", "session_id": session_id})
            if _original_models:
                for _name, _orig in _original_models.items():
                    self.specialists[_name].model = _orig
            return {"session_id": session_id, "results": completed}

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
        stack_lane_by_agent = {
            lane.get("agent"): lane
            for lane in (shared.get("stack_execution_blueprint") or {}).get("lanes", [])
            if lane.get("agent")
        }

        async def _run_task(task: dict) -> None:
            tid = task["id"]
            agent_name = task["agent"]
            agent = self.specialists.get(agent_name)
            stack_lane = stack_lane_by_agent.get(agent_name, {})
            lane_id = stack_lane.get("id") or task.get("id")
            if agent is None:
                logger.error("No specialist named %s", agent_name)
                completed[tid] = {"error": f"unknown agent {agent_name}"}
                await publish(session_id, {"type": "agent_error", "agent": agent_name, "task_id": tid, "error": f"unknown agent {agent_name}"})
                await publish(session_id, {
                    "type": "stack_lane_status",
                    "lane_id": lane_id,
                    "agent": agent_name,
                    "task_id": tid,
                    "status": "blocked",
                    "phase": stack_lane.get("phase"),
                    "title": stack_lane.get("title") or task.get("stack_task_title") or agent_name,
                    "blockers": [f"unknown agent {agent_name}"],
                    "next_actor": "founder",
                })
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
                unlimited_credits=bool((constraints or {}).get("unlimited_credits", False)),
                shared={
                    **shared,
                    "prior_results": dep_results,
                    "prior_vault_notes": vault_context_text,
                },
            )
            if proprietary_engine:
                proprietary_engine.on_agent_start(agent_name)

            await publish(session_id, {"type": "agent_start", "agent": agent_name, "task_id": tid, "instruction": task["instruction"]})
            await publish(session_id, {
                "type": "stack_lane_status",
                "lane_id": lane_id,
                "agent": agent_name,
                "task_id": tid,
                "status": "running",
                "phase": stack_lane.get("phase"),
                "title": stack_lane.get("title") or task.get("stack_task_title") or agent_name,
                "expected_artifacts": stack_lane.get("deliverables") or [
                    {"artifact_key": key, "title": key, "required": True}
                    for key in task.get("expected_artifacts", [])
                ],
                "next_actor": "agent",
            })
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
            try:
                from backend.stacks import verify_task_artifacts
                artifact_verification = verify_task_artifacts(
                    task,
                    result,
                    shared.get("stack_execution_blueprint"),
                )
            except Exception as _verify_exc:
                logger.warning("Artifact verification failed for %s: %s", agent_name, _verify_exc)
                artifact_verification = {
                    "task_id": tid,
                    "lane_id": lane_id,
                    "agent": agent_name,
                    "status": "needs_review",
                    "summary": f"Artifact verification failed: {_verify_exc}",
                    "artifacts": [],
                }
            await self._publish_stack_artifacts(session_id, task, result, stack_template)
            await publish(session_id, {
                "type": "stack_artifact_verification",
                "verification": artifact_verification,
            })
            await self._publish_outcomes(session_id, task, result)
            lane_status_value = artifact_verification.get("status", "passed")
            lane_status_event = {
                "passed": "done",
                "needs_review": "ready_for_review",
                "blocked": "blocked",
            }.get(lane_status_value, "ready_for_review")
            await publish(session_id, {
                "type": "stack_lane_status",
                "lane_id": lane_id,
                "agent": agent_name,
                "task_id": tid,
                "status": "blocked" if isinstance(result, dict) and result.get("web_quality_error") else lane_status_event,
                "phase": stack_lane.get("phase"),
                "title": stack_lane.get("title") or task.get("stack_task_title") or agent_name,
                "summary": result.get("summary", "") if isinstance(result, dict) else str(result)[:220],
                "ready_artifacts": task.get("expected_artifacts", []),
                "next_actor": "founder_review",
                "artifact_verification": artifact_verification,
                "blockers": (
                    [result.get("web_quality_error")] if isinstance(result, dict) and result.get("web_quality_error")
                    else artifact_verification.get("required_missing", [])
                ),
            })
            logger.info("Task %s (%s) done", tid, agent_name)

        # Phase A: start ALL agents immediately in parallel — research and specialists together.
        # Research results flow into shared context as they arrive; specialists pick them up
        # via shared["result_research"] etc. Replan runs in background and enriches instructions.

        def _collect_research() -> tuple[dict, list[str]]:
            from backend.tools.obsidian_logger import _note_path
            import re as _re2
            result: dict = {}
            notes: list[str] = []
            seen: set[str] = set()
            for rt in parallel_research_tasks:
                result.update(completed.get(rt["id"], {}))
                try:
                    base = _re2.sub(r"_\d+$", "", rt["agent"])
                    nf = _note_path(base, session_id, founder_id)
                    key = str(nf)
                    if nf.exists() and key not in seen:
                        seen.add(key)
                        notes.append(f"## {base.upper()}\n\n{nf.read_text()}")
                except Exception:
                    pass
            return result, notes

        # Launch research in background
        research_bg_tasks = [
            asyncio.create_task(_run_task(t)) for t in parallel_research_tasks
        ]

        # Background replan: when research is ready, update shared with enriched instructions
        async def _bg_replan():
            try:
                # Wait for at least one research agent to finish
                done, _ = await asyncio.wait(
                    research_bg_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=600,
                )
                if not done:
                    return
                research_result, merged_notes = _collect_research()
                if merged_notes:
                    research_result["obsidian_content"] = "\n\n---\n\n".join(merged_notes)
                agents_needed = [t["agent"] for t in other_agents_initial]
                if not agents_needed:
                    return
                detailed_tasks = await self._replan_with_research(goal, research_result, agents_needed, stack_context)
                if detailed_tasks:
                    # Update shared so any agent that hasn't started yet gets enriched instructions
                    for dt in detailed_tasks:
                        shared[f"enriched_instruction_{dt['agent']}"] = dt["instruction"]
                    await publish(session_id, {
                        "type": "plan_done",
                        "tasks": [{"id": t["id"], "agent": t["agent"], "instruction": t["instruction"]} for t in detailed_tasks],
                        "planner_model": self.planner.model,
                        "phase": "detailed",
                    })
                    # Detailed plan tree in background
                    async def _bg_detailed_plan():
                        try:
                            _rs = research_result.get("obsidian_content") or ""
                            tree_nodes = await self._generate_detailed_plan(goal, _rs, detailed_tasks)
                            if tree_nodes:
                                await publish(session_id, {"type": "detailed_plan", "nodes": tree_nodes})
                        except Exception as _dp_err:
                            logger.warning("detailed_plan generation failed: %s", _dp_err)
                    asyncio.create_task(_bg_detailed_plan())
            except Exception as _rp_err:
                logger.warning("Background replan failed: %s", _rp_err)

        asyncio.create_task(_bg_replan())

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
        try:
            from backend.core.events import _event_log
            from backend.session_digest import build_session_digest
            from backend.workflow_state import save_session_state
            import json as _json
            digest = build_session_digest(session_id, _event_log.get(session_id, []))
            await self._persist_brain_record(
                founder_id=founder_id,
                title=f"Run Digest - {company_name} - {session_id}",
                content=_json.dumps(digest, indent=2),
                kind="run_digest",
                canonical=False,
                stale_risk="low",
            )
            save_session_state(session_id, _event_log.get(session_id, []))
        except Exception as _digest_err:
            logger.warning("Run digest brain record failed: %s", _digest_err)

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
            await self._publish_outcomes(session_id, task, result)
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

"""
Base agent. Local-first LLM via OpenAI-compatible endpoint (MLX/ollama).
Each agent has: identity, tools, memory, P2P messaging, optional computer use.
"""
import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import openai

from backend.config import settings

logger = logging.getLogger(__name__)


def _format_tool_result(tool_name: str, result: Any) -> str:
    """
    Format tool results as readable text for LLM context.
    Raw JSON is hard for the LLM to parse — structured text is much better.
    """
    if not isinstance(result, dict):
        text = str(result)
        # HTML/large blobs: only confirm success + char count, don't dump full content
        if tool_name == "generate_landing_page_html" or (len(text) > 2000 and text.strip().startswith("<")):
            return f"HTML generated successfully ({len(text):,} chars). Pass it directly to vercel_deploy."
        return text

    # Web search — format as numbered list
    if tool_name in ("web_search", "news_search") and "formatted" in result:
        return result["formatted"]

    # Page fetcher / search_and_read — format as readable article sections
    if tool_name in ("fetch_page", "search_and_read"):
        if "results" in result:  # search_and_read
            lines = [f"Search: {result.get('query', '')}\n"]
            for r in result.get("results", []):
                lines.append(f"### {r.get('title', r.get('url', ''))}")
                lines.append(f"URL: {r.get('url', '')}")
                content = r.get("page_content") or r.get("snippet", "")
                if content:
                    lines.append(content[:1500])
                lines.append("")
            return "\n".join(lines)
        # fetch_page
        title = result.get("title", "")
        text = result.get("text", "")
        url = result.get("url", "")
        lines = []
        if title:
            lines.append(f"# {title}")
        if url:
            lines.append(f"Source: {url}")
        if text:
            lines.append(text)
        return "\n".join(lines)

    # Browser read_page
    if tool_name == "computer_use" or (isinstance(result, dict) and "body_text" in result):
        text = result.get("body_text", result.get("text", ""))
        title = result.get("title", "")
        url = result.get("url", "")
        out = []
        if title:
            out.append(f"Page: {title}")
        if url:
            out.append(f"URL: {url}")
        if text:
            out.append(text)
        return "\n".join(out) if out else json.dumps(result)

    # Obsidian tools — compact
    if tool_name in ("obsidian_log", "obsidian_read", "obsidian_append"):
        if tool_name == "obsidian_read":
            notes = result.get("notes", [])
            if not notes:
                return "No prior notes found."
            lines = [f"{len(notes)} prior session(s) found:\n"]
            for n in notes:
                lines.append(f"--- {n.get('file', '')} ---")
                lines.append(n.get("content", "")[:500])
            return "\n".join(lines)
        return json.dumps(result)

    # Default: compact JSON — hard cap at 1000 chars to limit context bloat
    try:
        text = json.dumps(result, indent=2)
        if len(text) > 1000:
            return text[:1000] + "\n... (truncated)"
        return text
    except Exception:
        return str(result)[:1000]



@dataclass
class Message:
    sender: str
    recipient: str
    content: str
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class AgentContext:
    goal: str
    founder_id: str
    session_id: str
    shared: dict = field(default_factory=dict)  # P2P shared state
    bypass_approvals: bool = False  # set True in tests to skip SafeRun approval gates
    task_id: str = ""
    dep_results: dict = field(default_factory=dict)
    vault_context: str = ""


class Agent:
    """
    Hierarchical + P2P capable agent.
    - Calls local LLM (MLX/ollama OpenAI-compatible endpoint)
    - Executes tools with real return values (no hallucination path)
    - Can send/receive messages to/from other agents via bus
    - Can spawn sub-agents
    - Optionally controls browser via computer_use
    """

    def __init__(
        self,
        name: str,
        role: str,
        tools: dict[str, Callable] = None,
        sub_agents: list["Agent"] = None,
        use_computer: bool = False,
        model: str = None,
        model_base_url: str = None,
        model_api_key: str = None,
        max_iterations: int = None,
        max_tool_calls: dict[str, int] | None = None,
    ):
        self.name = name
        self.role = role
        self.tools = tools or {}
        self.sub_agents = {a.name: a for a in (sub_agents or [])}
        self.use_computer = use_computer
        self.model = model or settings.agent_model_name
        self._model_base_url = model_base_url or settings.agent_model_base_url
        self._model_api_key = model_api_key or settings.agent_model_api_key
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls or {}
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._llm: Optional[openai.OpenAI] = None

    def _get_llm(self) -> openai.OpenAI:
        if self._llm is None:
            self._llm = openai.OpenAI(
                base_url=self._model_base_url,
                api_key=self._model_api_key,
            )
        return self._llm

    def _call_llm(self, messages: list[dict]) -> str:
        resp = self._get_llm().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            timeout=300.0,
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        # Strip DeepSeek-R1 <think> blocks
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # Strip markdown fences
        content = re.sub(r"^```(?:json)?\s*", "", content).rstrip("```").strip()
        return content

    def _parse_json(self, raw: str) -> dict:
        # Strategy 1: direct parse
        try:
            return json.loads(raw)
        except Exception:
            pass

        # Strategy 2: find outermost { ... }
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                pass

        # Strategy 3: find all JSON-like blobs and try each
        for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', raw, re.DOTALL):
            try:
                return json.loads(m.group())
            except Exception:
                continue

        return {}

    def _system_prompt(self) -> str:
        import inspect
        def _sig(name, fn):
            try:
                sig = inspect.signature(fn)
                params = ", ".join(
                    f"{pname}={repr(param.default)}" if param.default is not inspect.Parameter.empty else pname
                    for pname, param in sig.parameters.items()
                )
                doc = (fn.__doc__ or "").split("\n")[0].strip()
                return f"  - {name}({params})\n    {doc}"
            except Exception:
                return f"  - {name}: {fn.__doc__ or ''}"

        tool_list = "\n".join(_sig(name, fn) for name, fn in self.tools.items())
        sub_list = "\n".join(f"  - {n}" for n in self.sub_agents)
        computer_section = (
            "\nTo control the browser:\n"
            '{"action": "computer_use", "action_detail": {"action": "<cmd>", ...params}, "reasoning": "..."}\n'
            "Commands:\n"
            "  navigate      {url}  → go to URL\n"
            "  read_page     {}     → extract clean readable content from current page (preferred over get_text)\n"
            "  find_elements {}     → list interactive elements (buttons, inputs, links)\n"
            "  click         {selector} or {x, y}\n"
            "  type          {selector, text}\n"
            "  key           {key}  e.g. Enter, Tab\n"
            "  scroll        {delta_y}\n"
            "  scroll_to     {text} or {selector}  → scroll until element is visible\n"
            "  extract_table {}     → extract table data from page\n"
            "  get_text      {selector}  → read specific element text\n"
            "  wait          {ms}\n"
            "After each action you receive: result + current URL + clean page content.\n"
            "PREFER read_page over get_text — it returns clean article content without ads/nav.\n"
            "Use find_elements to discover selectors before clicking.\n"
        ) if self.use_computer else ""

        return (
            f"You are {self.name}, {self.role}.\n\n"
            f"TOOLS:\n{tool_list or '  (none)'}\n\n"
            f"SUB-AGENTS YOU CAN DELEGATE TO:\n{sub_list or '  (none)'}\n\n"
            "RESPONSE FORMAT — YOU MUST RESPOND WITH A SINGLE JSON OBJECT ONLY. NO PROSE. NO MARKDOWN. NO EXPLANATION.\n\n"
            "Call a tool:\n"
            '{"action": "tool", "tool": "<name>", "args": {<kwargs>}, "reasoning": "<one line>"}\n\n'
            "Delegate to sub-agent:\n"
            '{"action": "delegate", "agent": "<name>", "task": "...", "reasoning": "<one line>"}\n\n'
            + computer_section +
            "Task complete:\n"
            '{"action": "done", "output": {<result>}, "reasoning": "<one line>"}\n\n'
            "RULES:\n"
            "- Output ONLY the JSON object. Nothing before it, nothing after it.\n"
            "- Never invent tool results. Only report what tools actually returned.\n"
            "- If a tool fails, put the error in output and call done.\n"
            "- Use exact arg names from tool descriptions."
        )

    async def run(self, ctx: AgentContext) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": (
                f"GOAL: {ctx.goal}\n"
                f"FOUNDER_ID: {ctx.founder_id}\n"
                f"SESSION: {ctx.session_id}\n"
                f"SHARED CONTEXT: {json.dumps(ctx.shared, indent=2)}"
            )},
        ]

        browser = None
        if self.use_computer:
            from backend.computer_use.browser import BrowserSession
            browser = BrowserSession(headless=True)  # lazy-starts on first computer_use action

        try:
            return await self._run_loop(messages, ctx, browser)
        finally:
            if browser and browser._started:
                await browser.stop()

    async def _emit(self, ctx: AgentContext, event_type: str, **kwargs) -> None:
        from backend.core.events import publish
        await publish(ctx.session_id, {"type": event_type, "agent": self.name, **kwargs})

    async def _run_loop(self, messages: list[dict], ctx: AgentContext, browser=None) -> dict[str, Any]:
        i = 0
        MAX_ITERATIONS = self._max_iterations or 5
        # Track consecutive failures per tool to break infinite retry loops
        _tool_fail_counts: dict[str, int] = {}
        _large_results: dict[str, Any] = {}  # stores large non-dict results (HTML etc.) by tool name
        # One-shot tools: hard-blocked after first success
        _ONE_SHOT_TOOLS = {"generate_landing_page_html", "vercel_deploy", "claude_code_scaffold",
                           "obsidian_log"}
        _one_shot_done: set[str] = set()
        _called_tools: set[str] = set()
        _attempted_tools: set[str] = set()  # includes failed attempts
        _tool_attempt_counts: dict[str, int] = {}  # total attempts per tool (success + failure)
        _tool_results: list[tuple[str, dict[str, Any]]] = []

        while i < MAX_ITERATIONS:
            i += 1
            # Inject any founder steer messages before calling LLM
            try:
                from backend.core.events import steer_pull
                for directive in steer_pull(ctx.session_id):
                    messages.append({"role": "user", "content": f"[FOUNDER DIRECTIVE] {directive}\nAdjust your current plan accordingly and continue."})
                    logger.info("%s received founder directive: %s", self.name, directive[:80])
            except Exception:
                pass
            raw = await asyncio.to_thread(self._call_llm, messages)
            parsed = self._parse_json(raw)

            if not parsed:
                logger.warning("%s iteration %d: unparseable response — raw: %r", self.name, i, raw[:300])
                await self._emit(ctx, "agent_thinking", iteration=i, hint=raw[:80])
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Respond with valid JSON only. No prose. No markdown. Start with {."})
                continue

            action = parsed.get("action")
            reasoning = parsed.get("reasoning", "")
            tool_hint = parsed.get("tool", "")
            logger.info("[%s] iter=%d  action=%-12s  %s", self.name, i, action, (tool_hint or reasoning)[:80])
            messages.append({"role": "assistant", "content": raw})

            if action == "done":
                required_by_agent = {
                    "legal": {"format_legal_document", "generate_pdf"},
                    "legal_docs": {"format_legal_document", "generate_pdf"},
                    "legal_ip": {"format_legal_document", "generate_pdf", "patent_search"},
                    "sales": {"find_leads", "build_outreach_sequence", "build_crm_contact"},
                    "design": {"generate_design_spec", "generate_wireframe", "generate_logo_brief"},
                    "sales_enablement": {"generate_pdf", "obsidian_log"},
                }
                missing = sorted(required_by_agent.get(self.name, set()) - _called_tools)
                if missing:
                    messages.append({"role": "user", "content": (
                        f"You cannot call done yet. Missing required tool calls: {', '.join(missing)}. "
                        "Execute those tool calls now, then call done."
                    )})
                    continue
                output = parsed.get("output", {})
                if isinstance(output, dict):
                    output = self._normalize_done_output(output, _tool_results)
                    missing_output = self._missing_required_output(output, _attempted_tools)
                    if missing_output:
                        messages.append({"role": "user", "content": (
                            "You cannot call done yet. Output is missing required fields: "
                            f"{', '.join(missing_output)}. "
                            "Call the necessary tools, then call done with a complete output payload."
                        )})
                        continue
                await self._emit(ctx, "agent_done", result=output)
                logger.info("[%s] DONE — output keys: %s", self.name, list(output.keys()) if isinstance(output, dict) else type(output).__name__)
                # Auto-log to obsidian if agent never called it
                if "obsidian_log" in self.tools and "obsidian_log" not in _called_tools and ctx.founder_id and ctx.session_id:
                    try:
                        summary = output.get("summary", "") if isinstance(output, dict) else ""
                        await asyncio.to_thread(
                            self.tools["obsidian_log"],
                            agent=self.name,
                            session_id=ctx.session_id,
                            summary=summary or json.dumps(output)[:500],
                            output=output,
                            founder_id=ctx.founder_id,
                        )
                        logger.info("[%s] auto-logged done output to obsidian", self.name)
                    except Exception as oe:
                        logger.warning("[%s] obsidian auto-log failed: %s", self.name, oe)
                return output

            elif action == "tool":
                tool_name = parsed.get("tool")
                args = parsed.get("args", {})
                # Hard-block repeated calls to one-shot tools
                if tool_name in _ONE_SHOT_TOOLS and tool_name in _one_shot_done:
                    messages.append({"role": "user", "content": (
                        f"BLOCKED: {tool_name} already ran successfully this session. "
                        f"You MUST NOT call it again. Call done with the results you already have."
                    )})
                    continue
                # Enforce per-tool call limits (e.g. max 3 search calls for marketing)
                # Count ALL attempts (success + failure) so retries don't bypass the cap.
                _tool_call_limit = self._max_tool_calls.get(tool_name)
                if _tool_call_limit is not None:
                    _tool_total_attempts = _tool_attempt_counts.get(tool_name, 0)
                    if _tool_total_attempts >= _tool_call_limit:
                        _tool_success_count = sum(1 for tn, _ in _tool_results if tn == tool_name)
                        messages.append({"role": "user", "content": (
                            f"BLOCKED: {tool_name} has already been attempted {_tool_total_attempts} time(s) "
                            f"({_tool_success_count} succeeded, limit={_tool_call_limit}). You have enough research data. "
                            f"Stop calling {tool_name} and move on to content creation tools now."
                        )})
                        continue
                # Always use the actual cached HTML — LLM may pass a truncated/regenerated version
                if tool_name == "vercel_deploy" and _large_results.get("generate_landing_page_html"):
                    args["html"] = _large_results["generate_landing_page_html"]
                    logger.debug("[%s] forced cached HTML into vercel_deploy args (%d chars)", self.name, len(args["html"]))
                await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                _attempted_tools.add(tool_name)
                _tool_attempt_counts[tool_name] = _tool_attempt_counts.get(tool_name, 0) + 1
                result = await self._execute_tool(tool_name, args, ctx)
                await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
                if "error" not in result:
                    _called_tools.add(tool_name)
                    if isinstance(result, dict):
                        _tool_results.append((tool_name, result))
                    elif isinstance(result, str) and len(result) > 2000:
                        _large_results[tool_name] = result
                if "error" in result:
                    _tool_fail_counts[tool_name] = _tool_fail_counts.get(tool_name, 0) + 1
                    if _tool_fail_counts[tool_name] >= 3:
                        # Force the agent to give up on this tool
                        messages.append({"role": "user", "content": (
                            f"TOOL {tool_name} FAILED {_tool_fail_counts[tool_name]} TIMES IN A ROW: {json.dumps(result)}\n"
                            f"STOP trying {tool_name}. It will not work. "
                            f"Either use a different tool or call done with what you have accomplished so far. "
                            f"Do NOT call {tool_name} again."
                        )})
                    else:
                        messages.append({"role": "user", "content": (
                            f"TOOL FAILED: {json.dumps(result)}\n"
                            f"You MUST fix the arguments and retry, or call done with the error in output. "
                            f"Do NOT report this tool as successful."
                        )})
                else:
                    _tool_fail_counts[tool_name] = 0  # reset on success
                    if tool_name in _ONE_SHOT_TOOLS:
                        _one_shot_done.add(tool_name)
                    content = f"Tool result ({tool_name}):\n{_format_tool_result(tool_name, result)}"
                    if i >= 15:
                        content += f"\n\n[Iteration {i}/{MAX_ITERATIONS}] You are near the iteration limit. Wrap up: call obsidian_log then done unless one more tool call is critical."
                    if tool_name in _ONE_SHOT_TOOLS:
                        content += f"\n\nIMPORTANT: {tool_name} completed. Proceed to the next step — do NOT call {tool_name} again."
                    messages.append({"role": "user", "content": content})

            elif action == "delegate":
                agent_name = parsed.get("agent")
                task = parsed.get("task", "")
                await self._emit(ctx, "agent_action", action="delegate", target=agent_name, task=task, reasoning=reasoning)
                result = await self._delegate(agent_name, task, ctx)
                messages.append({"role": "user", "content": f"Sub-agent result: {json.dumps(result)}"})

            elif action == "computer_use" and browser is not None:
                detail = parsed.get("action_detail", {})
                await self._emit(ctx, "agent_action", action="computer_use", detail=detail, reasoning=reasoning)
                result = await browser.execute_action(detail)
                state = await browser.page_state()
                await self._emit(ctx, "agent_action_result", action="computer_use", url=state.get("url"), title=state.get("title"))
                messages.append({"role": "user", "content": (
                    f"Browser result: {json.dumps({k: v for k, v in result.items() if k != 'screenshot_b64'})}\n"
                    f"URL: {state.get('url', 'unknown')}\n"
                    f"Title: {state.get('title', '')}\n"
                    f"Page text: {state.get('body_text', '')}"
                )})

            elif action == "computer_use" and browser is None:
                messages.append({"role": "user", "content": "computer_use not available. Use tool or delegate."})

            elif action in self.tools:
                # Model used action name directly instead of {"action":"tool","tool":"<name>"}
                tool_name = action
                # Args may be nested under "args" key or spread at top level
                if "args" in parsed and isinstance(parsed["args"], dict):
                    args = parsed["args"]
                else:
                    args = {k: v for k, v in parsed.items() if k not in ("action", "reasoning", "tool")}
                await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                result = await self._execute_tool(tool_name, args, ctx)
                await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
                if "error" not in result:
                    _called_tools.add(tool_name)
                    if isinstance(result, dict):
                        _tool_results.append((tool_name, result))
                if "error" in result:
                    messages.append({"role": "user", "content": f"TOOL FAILED: {json.dumps(result)}"})
                else:
                    messages.append({"role": "user", "content": f"Tool result ({tool_name}):\n{_format_tool_result(tool_name, result)}"})

            else:
                messages.append({"role": "user", "content": "Unknown action. Use: tool, delegate, computer_use, or done."})

        logger.warning("%s hit MAX_ITERATIONS (%d) — forcing synthesis from gathered data", self.name, MAX_ITERATIONS)
        # Force one final synthesis call using everything gathered so far
        try:
            gathered = "\n\n".join(
                f"[{name}]: {json.dumps(res)[:1500]}" for name, res in _tool_results
            ) or "No tool results gathered."
            # Send ONLY system prompt + gathered data — NOT full history (avoids token explosion)
            synthesis_messages = [
                messages[0],  # system prompt
                {"role": "user", "content": (
                    f"GOAL: {ctx.goal}\n\n"
                    f"Research data gathered:\n{gathered[:8000]}\n\n"
                    "Synthesize into a final structured response. "
                    "Respond with JSON: {\"action\": \"done\", \"output\": {\"summary\": \"...\", \"findings\": [...], \"sources\": [...]}}"
                )},
            ]
            raw = await asyncio.to_thread(self._call_llm, synthesis_messages)
            parsed = self._parse_json(raw)
            if parsed and parsed.get("action") == "done":
                output = parsed.get("output", {})
                output["status"] = "partial"
                # Enrich with tool results before emitting (same as normal done path)
                output = self._normalize_done_output(output, _tool_results)
                await self._emit(ctx, "agent_done", output=output)
                # Auto-write to obsidian so downstream agents can read it
                if "obsidian_log" in self.tools and ctx.founder_id and ctx.session_id:
                    try:
                        summary = output.get("summary", "") or json.dumps(output)[:500]
                        await asyncio.to_thread(
                            self.tools["obsidian_log"],
                            agent=self.name,
                            session_id=ctx.session_id,
                            summary=summary,
                            output=output,
                            founder_id=ctx.founder_id,
                        )
                        logger.info("[%s] auto-logged synthesis to obsidian", self.name)
                    except Exception as oe:
                        logger.warning("[%s] obsidian auto-log failed: %s", self.name, oe)
                return output
        except Exception as e:
            logger.warning("%s forced synthesis failed: %s", self.name, e)
        return {"status": "max_iterations_reached", "agent": self.name}

    def _missing_required_output(self, output: dict[str, Any], attempted_tools: set[str] | None = None) -> list[str]:
        """Require key preview artifacts per role before accepting done."""
        if self.name in ("legal", "legal_docs"):
            docs = output.get("documents")
            if not isinstance(docs, list) or not docs:
                return ["documents[]"]
            first = docs[0] if isinstance(docs[0], dict) else {}
            if not (first.get("path") or first.get("text")):
                return ["documents[0].path|text"]
            return []
        if self.name == "sales":
            missing: list[str] = []
            if not isinstance(output.get("leads"), list) or not output.get("leads"):
                missing.append("leads[]")
            if not isinstance(output.get("sequence"), list) or not output.get("sequence"):
                missing.append("sequence[]")
            if not isinstance(output.get("crm_contacts"), list) or not output.get("crm_contacts"):
                missing.append("crm_contacts[]")
            return missing
        if self.name == "design":
            missing: list[str] = []
            if not output.get("design_spec"):
                missing.append("design_spec")
            if not isinstance(output.get("wireframes"), list) or not output.get("wireframes"):
                missing.append("wireframes[]")
            if not output.get("logo_brief"):
                missing.append("logo_brief")
            return missing
        if self.name == "sales_enablement":
            missing: list[str] = []
            # Reject placeholder PDF paths — real generate_pdf returns actual file paths
            for key in ("pitch_deck_pdf", "one_pager_pdf", "case_studies_pdf", "battlecards_pdf"):
                val = output.get(key, "")
                if not val or "/path/to/" in str(val) or not str(val).endswith(".pdf"):
                    missing.append(key)
            if not isinstance(output.get("pitch_deck_outline"), list) or len(output.get("pitch_deck_outline", [])) < 12:
                missing.append("pitch_deck_outline (12 slides required)")
            if not isinstance(output.get("battlecards"), list) or len(output.get("battlecards", [])) < 3:
                missing.append("battlecards (3 required)")
            return missing
        if self.name == "marketing":
            missing: list[str] = []
            if not output.get("reel_package"):
                missing.append("reel_package")
            if not output.get("tiktok_package"):
                missing.append("tiktok_package")
            if not output.get("meta_ad"):
                missing.append("meta_ad")
            ad_images = output.get("ad_images")
            # Only require ad_images if generate_ad_image hasn't been attempted yet.
            # If it was attempted (even if it failed), allow done to proceed — the error
            # is already surfaced in the tool result and the agent shouldn't be blocked forever.
            image_attempted = attempted_tools and "generate_ad_image" in attempted_tools
            if not isinstance(ad_images, list) or not ad_images:
                if not image_attempted:
                    missing.append("ad_images[]")
            return missing
        return []

    async def _execute_tool(self, tool_name: str, args: dict, ctx: AgentContext) -> Any:
        fn = self.tools.get(tool_name)
        if fn is None:
            return {"error": f"Unknown tool: {tool_name}"}
        import time as _time
        saferun_action = None
        try:
            from backend.core.events import publish
            from backend.safety import build_saferun_action
            saferun_action = build_saferun_action(tool_name, args, self.name)
            if saferun_action:
                await publish(ctx.session_id, {
                    "type": "saferun_action",
                    "action": saferun_action,
                })
        except Exception as e:
            logger.warning("[%s] SafeRun planning failed for %s: %s", self.name, tool_name, e)
        if saferun_action and saferun_action.get("approval_required") and not ctx.bypass_approvals:
            gate_key = saferun_action.get("approval_gate")
            try:
                from backend.core.events import approval_decision_wait, publish
                from backend.approval_workflows import create_approval_request
                approval_request = create_approval_request(
                    ctx.session_id,
                    str(gate_key),
                    title=str(gate_key).replace("_", " ").title(),
                    reason=saferun_action.get("reason", ""),
                    action_id=saferun_action.get("id", ""),
                    tool=tool_name,
                    agent=self.name,
                    risk_level=saferun_action.get("risk_level", "medium"),
                )
                await publish(ctx.session_id, {
                    "type": "approval_request",
                    "request": approval_request,
                })
                await publish(ctx.session_id, {
                    "type": "saferun_result",
                    "action_id": saferun_action["id"],
                    "tool": tool_name,
                    "agent": self.name,
                    "status": "waiting_approval",
                    "result_preview": f"Waiting for founder approval gate: {gate_key}",
                    "approval_gate": gate_key,
                })
                decision = await approval_decision_wait(ctx.session_id, str(gate_key), timeout=300.0)
                if not decision:
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error",
                        "result_preview": f"Timed out waiting for approval gate: {gate_key}",
                        "approval_gate": gate_key,
                    })
                    return {"error": f"SafeRun blocked {tool_name}: approval timed out for gate {gate_key}"}
                if decision.get("decision") != "approved":
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "skipped",
                        "result_preview": f"Founder skipped approval gate: {gate_key}",
                        "approval_gate": gate_key,
                    })
                    return {"error": f"SafeRun skipped {tool_name}: founder skipped approval gate {gate_key}"}
                await publish(ctx.session_id, {
                    "type": "saferun_result",
                    "action_id": saferun_action["id"],
                    "tool": tool_name,
                    "agent": self.name,
                    "status": "approved",
                    "result_preview": f"Founder approved gate: {gate_key}",
                    "approval_gate": gate_key,
                })
            except Exception as e:
                logger.warning("[%s] SafeRun approval wait failed for %s: %s", self.name, tool_name, e)
                return {"error": f"SafeRun approval check failed for {tool_name}: {e}"}
        args_preview = {k: (str(v)[:120] + "…" if isinstance(v, str) and len(str(v)) > 120 else v) for k, v in args.items()}
        logger.debug("[%s] → %s  args=%s", self.name, tool_name, args_preview)
        t0 = _time.monotonic()
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.to_thread(fn, **args)
            elapsed = _time.monotonic() - t0
            result_preview = str(result)[:200] if result is not None else "None"
            logger.debug("[%s] ← %s  %.1fs  result=%.200s", self.name, tool_name, elapsed, result_preview)
            if saferun_action:
                try:
                    from backend.core.events import publish
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error" if isinstance(result, dict) and result.get("error") else "executed",
                        "result_preview": result_preview,
                        "elapsed_seconds": round(elapsed, 2),
                    })
                except Exception as e:
                    logger.warning("[%s] SafeRun result emit failed for %s: %s", self.name, tool_name, e)
            return result
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.error("[%s] ✗ %s  %.1fs  %s: %s", self.name, tool_name, elapsed, type(e).__name__, e)
            if saferun_action:
                try:
                    from backend.core.events import publish
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error",
                        "result_preview": str(e)[:240],
                        "elapsed_seconds": round(elapsed, 2),
                    })
                except Exception as emit_error:
                    logger.warning("[%s] SafeRun error emit failed for %s: %s", self.name, tool_name, emit_error)
            return {"error": str(e)}

    def _normalize_done_output(
        self,
        output: dict[str, Any],
        tool_results: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Enrich agent done payload with stable preview-friendly fields."""
        out = dict(output)
        if self.name == "marketing":
            images = []
            for tool_name, result in tool_results:
                if tool_name != "generate_ad_image":
                    continue
                url = result.get("url") or result.get("image_url")
                b64 = result.get("base64")
                if url or b64:
                    images.append({"url": url, "base64": b64, "prompt": result.get("prompt", "")})
            if images:
                out.setdefault("ad_images", images)
        elif self.name == "sales":
            leads = out.get("leads")
            sequences = out.get("sequences")
            crm_contacts = out.get("crm_contacts")
            if not isinstance(leads, list):
                leads = []
            if not isinstance(sequences, list):
                sequences = []
            if not isinstance(crm_contacts, list):
                crm_contacts = []
            for tool_name, result in tool_results:
                if tool_name == "find_leads" and isinstance(result.get("leads"), list):
                    leads.extend(result["leads"])
                elif tool_name == "build_outreach_sequence" and isinstance(result.get("sequence"), list):
                    sequences.append({"lead": result.get("lead", {}), "steps": result["sequence"]})
                elif tool_name == "build_crm_contact":
                    crm_contacts.append(result)
            if leads:
                out["leads"] = leads
            if sequences:
                out["sequences"] = sequences
                if "sequence" not in out and sequences[0].get("steps"):
                    out["sequence"] = sequences[0]["steps"]
            if crm_contacts:
                out["crm_contacts"] = crm_contacts
        elif self.name == "design":
            if "design_spec" not in out or not out.get("design_spec"):
                for tool_name, result in tool_results:
                    if tool_name == "generate_design_spec":
                        out["design_spec"] = result
                        break
            wireframes = out.get("wireframes") if isinstance(out.get("wireframes"), list) else []
            for tool_name, result in tool_results:
                if tool_name == "generate_wireframe":
                    wireframes.append(result)
                if tool_name == "generate_logo_brief" and not out.get("logo_brief"):
                    out["logo_brief"] = result
            if wireframes:
                out["wireframes"] = wireframes
        elif self.name in ("legal", "legal_docs"):
            docs = out.get("documents") if isinstance(out.get("documents"), list) else []
            current_doc: dict[str, Any] | None = None
            for tool_name, result in tool_results:
                if tool_name == "format_legal_document":
                    current_doc = {
                        "doc_type": result.get("doc_type"),
                        "title": result.get("doc_type", "document"),
                        "text": result.get("formatted_text", ""),
                    }
                elif tool_name == "generate_pdf":
                    if current_doc is None:
                        current_doc = {"doc_type": "document", "title": "document"}
                    current_doc["path"] = result.get("path") or result.get("filename")
                    docs.append(current_doc)
                    current_doc = None
            if docs:
                out["documents"] = docs
        return out

    async def _delegate(self, agent_name: str, task: str, ctx: AgentContext) -> Any:
        agent = self.sub_agents.get(agent_name)
        if agent is None:
            return {"error": f"Unknown sub-agent: {agent_name}"}
        sub_ctx = AgentContext(
            goal=task,
            founder_id=ctx.founder_id,
            session_id=ctx.session_id,
            shared=ctx.shared,
        )
        return await agent.run(sub_ctx)

    async def receive(self, msg: Message) -> None:
        await self._inbox.put(msg)

    async def send(self, bus: "AgentBus", recipient: str, content: str) -> None:
        await bus.route(Message(sender=self.name, recipient=recipient, content=content))

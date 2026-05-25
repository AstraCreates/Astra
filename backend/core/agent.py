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
    ):
        self.name = name
        self.role = role
        self.tools = tools or {}
        self.sub_agents = {a.name: a for a in (sub_agents or [])}
        self.use_computer = use_computer
        self.model = model or settings.agent_model_name
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._llm: Optional[openai.OpenAI] = None

    def _get_llm(self) -> openai.OpenAI:
        if self._llm is None:
            self._llm = openai.OpenAI(
                base_url=settings.agent_model_base_url,
                api_key=settings.agent_model_api_key,
            )
        return self._llm

    def _call_llm(self, messages: list[dict]) -> str:
        resp = self._get_llm().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
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
            "  navigate   {url}\n"
            "  find_elements  {}  → lists buttons/inputs/links on page\n"
            "  click      {selector} or {x, y}\n"
            "  type       {selector, text}\n"
            "  key        {key}  e.g. Enter, Tab\n"
            "  scroll     {delta_y}\n"
            "  get_text   {selector}  → read specific element text\n"
            "  wait       {ms}\n"
            "After each action you receive: result + current URL + page text.\n"
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
        MAX_ITERATIONS = 20
        # Track consecutive failures per tool to break infinite retry loops
        _tool_fail_counts: dict[str, int] = {}
        # One-shot tools: hard-blocked after first success
        _ONE_SHOT_TOOLS = {"format_legal_document", "generate_landing_page_html", "generate_pdf", "vercel_deploy"}
        _one_shot_done: set[str] = set()

        while i < MAX_ITERATIONS:
            i += 1
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
            messages.append({"role": "assistant", "content": raw})

            if action == "done":
                output = parsed.get("output", {})
                await self._emit(ctx, "agent_done", result=output)
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
                await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                result = await self._execute_tool(tool_name, args, ctx)
                await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
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
                    content = f"Tool result: {json.dumps(result)}"
                    if i >= 5:
                        content += f"\n\n[Iteration {i}/{MAX_ITERATIONS}] You have gathered enough data. Call obsidian_log then done now unless you have a specific reason to do one more tool call."
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

            else:
                messages.append({"role": "user", "content": "Unknown action. Use: tool, delegate, computer_use, or done."})

        logger.warning("%s hit MAX_ITERATIONS (%d) — returning partial result", self.name, MAX_ITERATIONS)
        return {"status": "max_iterations_reached", "agent": self.name}

    async def _execute_tool(self, tool_name: str, args: dict, ctx: AgentContext) -> Any:
        fn = self.tools.get(tool_name)
        if fn is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.to_thread(fn, **args)
            return result
        except Exception as e:
            logger.error("%s tool %s failed: %s", self.name, tool_name, e)
            return {"error": str(e)}

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

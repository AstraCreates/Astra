"""
Agent implementation backed by hermes-agent (NousResearch).
Drop-in replacement for backend/core/agent.py's Agent class.

Uses AIAgent.run_conversation() for the LLM loop + tool dispatch,
with our custom tools registered in a per-run isolated Hermes toolset.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.config import settings
from backend.core.tool_schema import build_tool_schema

logger = logging.getLogger(__name__)


# ── shared dataclasses (same interface as old agent.py) ────────────────────

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
    shared: dict = field(default_factory=dict)


# ── sync wrappers for async tools ──────────────────────────────────────────

def _make_sync(fn: Callable) -> Callable:
    """Wrap an async function so Hermes can call it synchronously."""
    if not asyncio.iscoroutinefunction(fn):
        return fn

    def sync_wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an event loop (FastAPI).  Hermes runs tools
                # from a thread-pool thread that has its own loop.  Use that.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, fn(*args, **kwargs))
                    return future.result()
            return loop.run_until_complete(fn(*args, **kwargs))
        except RuntimeError:
            return asyncio.run(fn(*args, **kwargs))

    sync_wrapper.__doc__ = fn.__doc__
    sync_wrapper.__name__ = fn.__name__
    return sync_wrapper


# ── HermesAgent ────────────────────────────────────────────────────────────

class HermesAgent:
    """
    Specialist agent that uses hermes-agent's AIAgent loop.
    Interface-compatible with the old Agent class.
    """

    def __init__(
        self,
        name: str,
        role: str,
        tools: dict[str, Callable] = None,
        sub_agents: list = None,
        use_computer: bool = False,
        model: str = None,
        model_base_url: str = None,
        model_api_key: str = None,
        hermes_toolsets: list[str] = None,
    ):
        self.name = name
        self.role = role
        self._tools: dict[str, Callable] = tools or {}
        self.sub_agents: dict[str, "HermesAgent"] = {
            a.name: a for a in (sub_agents or [])
        }
        self.use_computer = use_computer
        self.hermes_toolsets: list[str] = hermes_toolsets or []
        self.model = model or settings.agent_model_name
        self._model_base_url = model_base_url or settings.agent_model_base_url
        self._model_api_key = model_api_key or settings.agent_model_api_key
        self._inbox: asyncio.Queue = asyncio.Queue()

    # ── event helpers ──────────────────────────────────────────────────────

    async def _emit(self, ctx: AgentContext, event_type: str, **kwargs) -> None:
        from backend.core.events import publish
        await publish(ctx.session_id, {"type": event_type, "agent": self.name, **kwargs})

    # ── tool registration ──────────────────────────────────────────────────

    def _register_toolset(
        self,
        toolset_name: str,
        result_holder: list,
        event_loop,
    ) -> list[str]:
        """Register our tools with Hermes registry under *toolset_name*."""
        from tools.registry import registry

        registered: list[str] = []

        for tool_name, fn in self._tools.items():
            sync_fn = _make_sync(fn)
            schema = build_tool_schema(tool_name, sync_fn)
            try:
                registry.register(
                    name=tool_name,
                    toolset=toolset_name,
                    schema=schema,
                    handler=sync_fn,
                    is_async=False,
                    override=True,
                )
                registered.append(tool_name)
            except Exception as exc:
                logger.warning("Tool registration skipped for %s: %s", tool_name, exc)

        # Capture tool results as they stream in
        def _result_capture(output: str = "{}") -> str:
            try:
                parsed = json.loads(output) if isinstance(output, str) else output
            except Exception:
                parsed = {"response": str(output)}
            result_holder.append(parsed)
            asyncio.run_coroutine_threadsafe(
                self._emit(ctx, "agent_step_result", result=parsed),
                event_loop,
            )
            return "Noted."

        _result_capture.__doc__ = "Record an intermediate or final result."

        return registered

    def _deregister(self, tool_names: list[str]) -> None:
        from tools.registry import registry
        for name in tool_names:
            try:
                registry.deregister(name)
            except Exception:
                pass

    # ── main run ──────────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext) -> dict[str, Any]:
        from run_agent import AIAgent

        await self._emit(ctx, "agent_start")

        run_id = uuid.uuid4().hex[:8]
        toolset_name = f"astra-{self.name}-{run_id}"
        result_holder: list = []
        event_loop = asyncio.get_event_loop()

        registered = self._register_toolset(toolset_name, result_holder, event_loop)

        # Callbacks bridge sync Hermes → async SSE
        def on_tool_start(tool_name: str, args_preview: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self._emit(
                    ctx, "agent_action",
                    action="tool", tool=tool_name, args=args_preview,
                ),
                event_loop,
            )

        def on_tool_complete(tool_name: str, result_preview: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self._emit(
                    ctx, "agent_action_result",
                    tool=tool_name, result=result_preview,
                ),
                event_loop,
            )

        def on_step(text: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self._emit(ctx, "agent_thinking", text=text[:500]),
                event_loop,
            )

        system_prompt = f"You are {self.name}, {self.role}"

        user_message = (
            f"GOAL: {ctx.goal}\n"
            f"FOUNDER_ID: {ctx.founder_id}\n"
            f"SESSION: {ctx.session_id}\n"
            f"SHARED CONTEXT:\n{json.dumps(ctx.shared, indent=2)}"
        )

        try:
            all_toolsets = [toolset_name] + self.hermes_toolsets

            agent = AIAgent(
                base_url=self._model_base_url,
                api_key=self._model_api_key,
                model=self.model,
                enabled_toolsets=all_toolsets,
                tool_start_callback=on_tool_start,
                tool_complete_callback=on_tool_complete,
                step_callback=on_step,
                ephemeral_system_prompt=system_prompt,
                quiet_mode=True,
                skip_memory=True,
                skip_context_files=True,
            )

            raw = await asyncio.to_thread(
                agent.run_conversation,
                user_message,
                system_message=system_prompt,
            )

            # Extract structured output
            if result_holder:
                output = result_holder[-1]
            else:
                # Fall back: try to parse last assistant message as JSON
                response_text = (
                    raw.get("response", "") if isinstance(raw, dict) else str(raw)
                )
                try:
                    start = response_text.rfind("{")
                    end = response_text.rfind("}") + 1
                    output = json.loads(response_text[start:end]) if start >= 0 else {}
                except Exception:
                    output = {"response": response_text[:2000]}

            await self._emit(ctx, "agent_done", result=output)
            return output

        except Exception as exc:
            logger.error("HermesAgent %s failed: %s", self.name, exc, exc_info=True)
            err = {"error": str(exc), "agent": self.name}
            await self._emit(ctx, "agent_done", result=err)
            return err

        finally:
            self._deregister(registered)

    # ── P2P messaging (kept for bus compatibility) ─────────────────────────

    async def receive(self, msg: Message) -> None:
        await self._inbox.put(msg)

    async def send(self, bus: Any, recipient: str, content: str) -> None:
        await bus.route(Message(sender=self.name, recipient=recipient, content=content))

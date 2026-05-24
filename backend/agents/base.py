import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

import openai

from backend.config import settings
from backend.memory.vector_store import vector_store
from backend.tools.registry import TOOL_REGISTRY, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


@dataclass
class AgentTask:
    task_id: str
    goal_id: str
    founder_id: str
    agent: str
    instruction: str
    context_bundle: dict
    constraints: dict
    tools_available: list


@dataclass
class AgentResult:
    task_id: str
    agent: str
    status: str  # "done" | "blocked" | "approval_required"
    output: dict
    confidence: float
    reasoning: str
    approval_action: Optional[str] = None
    approval_consequence: Optional[str] = None
    blocked_reason: Optional[str] = None
    blocked_needs: Optional[str] = None
    cost_usd: float = 0.0


def _tool_schema(tool_names: list[str]) -> str:
    """Describe available tools and their signatures for the prompt."""
    descriptions = {
        "web_search": 'web_search(query: str, max_results: int=8) — search the web',
        "news_search": 'news_search(query: str, max_results: int=5) — search recent news',
        "patent_search": 'patent_search(query: str, assignee: str=None, max_results: int=10) — search USPTO patents',
        "vercel_deploy": 'vercel_deploy(project_slug: str, html: str, css: str="", js: str="") — deploy site to Vercel',
        "generate_landing_page_html": 'generate_landing_page_html(page_title, headline, subheadline, value_props: list, cta_text, cta_url, company_name="") — generate HTML',
        "github_create_repo": 'github_create_repo(repo_name, description, stack: dict, mvp_features: list, private=False) — scaffold + push GitHub repo',
        "generate_reel_package": 'generate_reel_package(company_name, headline, value_prop, target_audience, tone="professional") — Instagram Reel script + caption + hashtags',
        "generate_tiktok_package": 'generate_tiktok_package(company_name, hook, problem, solution) — TikTok video script',
        "generate_meta_ad": 'generate_meta_ad(company_name, headline, body, cta, target_audience_description, budget_usd_per_day=10.0) — Meta ad copy + targeting',
        "send_email_campaign": 'send_email_campaign(to_email, from_name, from_email, subject, body_html, body_text="") — send via SendGrid',
        "build_email_html": 'build_email_html(subject, body_paragraphs: list, cta_text="", cta_url="") — render HTML email',
        "generate_pdf": 'generate_pdf(title, sections: list[{heading, body}], output_dir="/tmp/astra_docs") — create PDF document',
        "doc_generator": 'doc_generator(doc_type, content: dict) — generate formatted document',
    }
    lines = []
    for name in tool_names:
        if name in descriptions:
            lines.append(f"  - {descriptions[name]}")
        elif name in TOOL_REGISTRY:
            lines.append(f"  - {name}(...)")
    return "\n".join(lines) if lines else "  (none)"


class AstraAgent:
    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        model: str,
        tools: list[str],
        memory_namespaces: list[str],
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools
        self.memory_namespaces = memory_namespaces
        self._client: Optional[openai.OpenAI] = None

    def _get_client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI(
                base_url=settings.agent_model_base_url,
                api_key=settings.agent_model_api_key,
            )
        return self._client

    def _build_prompt(self, task: AgentTask, memory_docs: list[dict]) -> str:
        memory_text = "\n\n".join(
            f"[{doc.get('doc_type', 'doc')}] {doc.get('summary', '')}"
            for doc in memory_docs
        )
        tool_schema = _tool_schema(task.tools_available)
        return (
            f"GOAL: {task.instruction}\n\n"
            f"COMPANY CONTEXT:\n{json.dumps(task.context_bundle, indent=2)}\n\n"
            f"RELEVANT MEMORY:\n{memory_text or '(none)'}\n\n"
            f"CONSTRAINTS:\n{json.dumps(task.constraints, indent=2)}\n\n"
            f"AVAILABLE TOOLS:\n{tool_schema}\n\n"
            "You may call tools to gather real data before producing your final answer.\n"
            "To call a tool, respond with JSON:\n"
            '{"status": "tool_call", "tool": "<name>", "tool_input": {<args>}, "reasoning": "why"}\n\n'
            "When done with all tool calls, respond with your final answer:\n"
            "{\n"
            '  "status": "done",\n'
            '  "output": {},\n'
            '  "confidence": 0.0,\n'
            '  "reasoning": "...",\n'
            '  "approval_action": null,\n'
            '  "approval_consequence": null,\n'
            '  "blocked_reason": null,\n'
            '  "blocked_needs": null\n'
            "}\n"
            "IMPORTANT: Only set status='approval_required' if your system prompt explicitly instructs it for an irreversible action. "
            "Do NOT return approval_required for research, content generation, or analysis tasks."
        )

    def _call_model(self, messages: list[dict]) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=32768,
        )
        msg = response.choices[0].message
        content = msg.content or ""
        if not content.strip():
            content = getattr(msg, "reasoning_content", "") or ""
        return content

    def _extract_json(self, raw: str) -> dict:
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def run(self, task: AgentTask) -> AgentResult:
        memory_docs = await vector_store.retrieve(
            founder_id=task.founder_id,
            namespaces=self.memory_namespaces,
            query=task.instruction,
            k=5,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_prompt(task, memory_docs)},
        ]

        tool_results_accumulated: list[dict] = []

        for iteration in range(MAX_TOOL_ITERATIONS + 1):
            raw = await asyncio.to_thread(self._call_model, messages)
            parsed = self._extract_json(raw)

            if not parsed:
                logger.error("Agent %s iteration %d: invalid JSON: %s", self.agent_id, iteration, raw[:200])
                break

            status = parsed.get("status", "done")

            if status == "tool_call":
                tool_name = parsed.get("tool", "")
                tool_input = parsed.get("tool_input", {})
                tool_reasoning = parsed.get("reasoning", "")

                logger.info("Agent %s calling tool %s with %s", self.agent_id, tool_name, tool_input)

                tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_input)
                tool_results_accumulated.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": tool_result,
                })

                # Feed tool result back into conversation
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Tool '{tool_name}' result:\n{json.dumps(tool_result, indent=2)}\n\n"
                        "Continue. Call another tool or produce your final JSON answer."
                    ),
                })
                continue

            # Final answer
            if tool_results_accumulated:
                parsed.setdefault("output", {})
                parsed["output"]["_tools_used"] = [t["tool"] for t in tool_results_accumulated]

            return AgentResult(
                task_id=task.task_id,
                agent=self.agent_id,
                status=status,
                output=parsed.get("output", {}),
                confidence=parsed.get("confidence", 0.0),
                reasoning=parsed.get("reasoning", ""),
                approval_action=parsed.get("approval_action"),
                approval_consequence=parsed.get("approval_consequence"),
                blocked_reason=parsed.get("blocked_reason"),
                blocked_needs=parsed.get("blocked_needs"),
            )

        # Max iterations hit — return what we have
        logger.warning("Agent %s hit max tool iterations", self.agent_id)
        return AgentResult(
            task_id=task.task_id,
            agent=self.agent_id,
            status="blocked",
            output={"_tools_used": [t["tool"] for t in tool_results_accumulated]},
            confidence=0.0,
            reasoning="Exceeded max tool iterations without producing final answer",
            blocked_reason="max_iterations",
            blocked_needs="reduce tool calls or increase MAX_TOOL_ITERATIONS",
        )

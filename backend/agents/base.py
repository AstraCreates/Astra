import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

import openai

from backend.config import settings
from backend.memory.vector_store import vector_store

logger = logging.getLogger(__name__)


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
        return (
            f"GOAL: {task.instruction}\n\n"
            f"COMPANY CONTEXT:\n{json.dumps(task.context_bundle, indent=2)}\n\n"
            f"RELEVANT MEMORY:\n{memory_text or '(none)'}\n\n"
            f"CONSTRAINTS:\n{json.dumps(task.constraints, indent=2)}\n\n"
            f"AVAILABLE TOOLS: {', '.join(task.tools_available) or '(none)'}\n\n"
            "Respond ONLY with valid JSON:\n"
            "{\n"
            '  "status": "done" | "blocked" | "approval_required",\n'
            '  "output": {},\n'
            '  "confidence": 0.0,\n'
            '  "reasoning": "...",\n'
            '  "approval_action": "...",\n'
            '  "approval_consequence": "...",\n'
            '  "blocked_reason": "...",\n'
            '  "blocked_needs": "..."\n'
            "}"
        )

    def _call_model(self, messages: list[dict]) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=4096,
        )
        msg = response.choices[0].message
        content = msg.content or ""
        if not content.strip():
            content = getattr(msg, "reasoning_content", "") or ""
        return content

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

        raw = await asyncio.to_thread(self._call_model, messages)

        # extract JSON from mixed reasoning+JSON content
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end + 1]

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Agent %s returned invalid JSON: %s", self.agent_id, raw[:200])
            parsed = {
                "status": "blocked",
                "output": {},
                "confidence": 0.0,
                "reasoning": "Model returned non-JSON response",
                "blocked_reason": "invalid_json",
                "blocked_needs": "retry or model swap",
            }

        return AgentResult(
            task_id=task.task_id,
            agent=self.agent_id,
            status=parsed.get("status", "blocked"),
            output=parsed.get("output", {}),
            confidence=parsed.get("confidence", 0.0),
            reasoning=parsed.get("reasoning", ""),
            approval_action=parsed.get("approval_action"),
            approval_consequence=parsed.get("approval_consequence"),
            blocked_reason=parsed.get("blocked_reason"),
            blocked_needs=parsed.get("blocked_needs"),
        )

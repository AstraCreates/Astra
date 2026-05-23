import asyncio
import json
import logging

import openai

from backend.config import settings

logger = logging.getLogger(__name__)

_PARSE_PROMPT = """\
You are an AI goal parser. Extract structured information from this founder's goal.

Founder input: {raw_instruction}

Respond ONLY with valid JSON, no markdown, no explanation:
{
  "instruction": "clean 1-sentence description of the goal",
  "entities": {
    "company_name": "if mentioned, else null",
    "icp": "ideal customer profile if mentioned, else null",
    "problem": "problem being solved",
    "pricing_hypothesis": "pricing if mentioned, else null"
  },
  "constraints": {},
  "priority_agents": ["legal"]
}
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=settings.agent_model_base_url,
            api_key=settings.agent_model_api_key,
        )
    return _client


async def parse_goal(goal_id: str, founder_id: str, raw_instruction: str) -> dict:
    def _call():
        client = _get_client()
        prompt = _PARSE_PROMPT.replace("{raw_instruction}", raw_instruction)
        response = client.chat.completions.create(
            model=settings.agent_model_name,
            messages=[
                {"role": "system", "content": "You are a JSON-only goal parser. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        msg = response.choices[0].message
        content = msg.content or ""
        if not content.strip():
            content = getattr(msg, "reasoning_content", "") or ""
        return content

    raw = await asyncio.to_thread(_call)

    # extract JSON object from response (handles reasoning text, code fences, etc.)
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]

    try:
        parsed = json.loads(raw)
        parsed.setdefault("entities", {})
        parsed.setdefault("constraints", {})
        parsed.setdefault("priority_agents", [])
        return parsed
    except json.JSONDecodeError:
        logger.warning("Goal parser returned invalid JSON for goal %s: %s", goal_id, raw[:200])
        return {
            "instruction": raw_instruction,
            "entities": {},
            "constraints": {},
            "priority_agents": [],
        }

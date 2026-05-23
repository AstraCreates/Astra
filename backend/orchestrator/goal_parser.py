import asyncio
import json
import logging

import google.generativeai as genai

from backend.config import settings

logger = logging.getLogger(__name__)

_PARSE_PROMPT = """\
You are an AI goal parser. Extract structured information from this founder's goal.

Founder input: {raw_instruction}

Respond ONLY with valid JSON:
{{
  "instruction": "clean 1-sentence description of the goal",
  "entities": {{
    "company_name": "if mentioned, else null",
    "icp": "ideal customer profile if mentioned, else null",
    "problem": "problem being solved",
    "pricing_hypothesis": "pricing if mentioned, else null"
  }},
  "constraints": {{}},
  "priority_agents": ["list of agents to prioritize: legal, research, web, marketing, technical, ops"]
}}
"""


async def parse_goal(goal_id: str, founder_id: str, raw_instruction: str) -> dict:
    def _call():
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = _PARSE_PROMPT.format(raw_instruction=raw_instruction)
        response = model.generate_content(prompt)
        return response.text

    raw = await asyncio.to_thread(_call)

    try:
        parsed = json.loads(raw)
        parsed.setdefault("entities", {})
        parsed.setdefault("constraints", {})
        parsed.setdefault("priority_agents", [])
        return parsed
    except json.JSONDecodeError:
        logger.warning("Goal parser returned invalid JSON for goal %s", goal_id)
        return {
            "instruction": raw_instruction,
            "entities": {},
            "constraints": {},
            "priority_agents": [],
        }

"""
Vision model client — wraps a local multimodal LLM (or remote fallback).
Provides screenshot → description and screenshot → action decision.
"""
import base64
import logging
from pathlib import Path

import openai

from backend.config import settings

logger = logging.getLogger(__name__)

_VISION_MODEL = "llava"  # any local vision model via OpenAI-compat endpoint


def get_vision_client() -> openai.OpenAI:
    return openai.OpenAI(
        base_url=settings.agent_model_base_url,
        api_key=settings.agent_model_api_key,
    )


def describe_screenshot(screenshot_b64: str, context: str = "") -> str:
    """Send screenshot to vision model, get plain-text description."""
    client = get_vision_client()
    resp = client.chat.completions.create(
        model=_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Describe what you see on screen. Context: {context}" if context else "Describe what you see on screen.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                    },
                ],
            }
        ],
        max_tokens=512,
    )
    return resp.choices[0].message.content or ""


def screenshot_to_action(screenshot_b64: str, goal: str, history: list[dict]) -> dict:
    """Vision model decides next browser action given current screenshot + goal."""
    client = get_vision_client()
    resp = client.chat.completions.create(
        model=_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"GOAL: {goal}\n"
                            f"HISTORY (last 3): {history[-3:]}\n\n"
                            "Look at the screenshot. Respond with JSON only:\n"
                            '{"action": "navigate|click|type|scroll|key|done", '
                            '"reasoning": "...", ...action params...}'
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                    },
                ],
            }
        ],
        max_tokens=512,
    )
    import json, re
    raw = resp.choices[0].message.content or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("```").strip()
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return {"action": "done", "result": {"error": "unparseable vision response"}}

"""
Vision model client — wraps a local multimodal LLM (or remote fallback).
Provides screenshot → description and screenshot → action decision.
"""
import base64
import logging
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

def _vision_model() -> str:
    from backend.config import settings
    return settings.browser_use_model or "google/gemini-2.5-pro"


def get_vision_client():
    from backend.core.llm_client import get_or_client
    from backend.core.key_rotator import get_openrouter_key
    key = get_openrouter_key() or settings.openrouter_api_key
    return get_or_client(settings.openrouter_base_url, key)


def describe_screenshot(screenshot_b64: str, context: str = "") -> str:
    """Send screenshot to vision model, get plain-text description."""
    client = get_vision_client()
    resp = client.chat.completions.create(
        model=_vision_model(),
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
        max_tokens=2048,
        extra_body={"provider": {"allow_fallbacks": True}},
    )
    return (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""


def screenshot_to_action(screenshot_b64: str, goal: str, history: list[dict]) -> dict:
    """Vision model decides next browser action given current screenshot + goal."""
    client = get_vision_client()
    resp = client.chat.completions.create(
        model=_vision_model(),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"GOAL: {goal}\n"
                            f"HISTORY (last 6): {history[-6:]}\n\n"
                            "Look at the screenshot. Decide the single best next action.\n"
                            "Respond with JSON only — no markdown, no explanation:\n"
                            '{"action": "navigate|click|type|scroll|key|screenshot|done", '
                            '"reasoning": "one sentence", ...action params...}\n\n'
                            "navigate: {url}\n"
                            "click: {selector} or {x, y}\n"
                            "type: {selector, text}\n"
                            "scroll: {delta_x, delta_y}\n"
                            "key: {key} (e.g. Enter, Tab, Escape)\n"
                            "screenshot: {} — capture current state\n"
                            "done: {result: {success, message, extracted}}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                    },
                ],
            }
        ],
        max_tokens=2048,
        extra_body={"provider": {"allow_fallbacks": True}},
    )
    import json, re
    raw = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("```").strip()
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return {"action": "done", "result": {"error": "unparseable vision response"}}

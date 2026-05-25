"""
Sync LLM helper for content-generation tools.
Uses the same local model endpoint as the agents.
"""
import re
from backend.config import settings


def generate(prompt: str, max_tokens: int | None = None, json_mode: bool = False) -> str:
    """Call the local LLM and return raw text content. max_tokens=None means no limit (API default)."""
    import openai
    client = openai.OpenAI(
        base_url=settings.agent_model_base_url,
        api_key=settings.agent_model_api_key,
    )
    kwargs = dict(
        model=settings.agent_model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    # Strip DeepSeek-R1 <think> blocks
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content

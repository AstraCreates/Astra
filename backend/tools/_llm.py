"""
Sync LLM helper for content-generation tools.

Models:
  "fast"    → Llama-3.3-70B  (default, general purpose)
  "large"   → gpt-oss-120b   (small input, high output — docs, copy, HTML)
  "image"   → Janus-Pro-7B   (image generation, returns base64 PNG)
"""
import re
from backend.config import settings

_FAST_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_LARGE_MODEL = "openai/gpt-oss-120b"
_IMAGE_MODEL = "black-forest-labs/FLUX-2-pro"
_PROMPT_MODEL = "openai/gpt-oss-120b"
_DI_BASE = "https://api.deepinfra.com/v1/openai"
_DI_IMAGE_BASE = "https://api.deepinfra.com/v1/inference"


def _api_key() -> str:
    return settings.deepinfra_api_key or settings.planner_model_api_key or settings.agent_model_api_key


def generate(prompt: str, max_tokens: int | None = None, json_mode: bool = False, model: str = "large") -> str:
    """Call an LLM for content generation. Returns raw text.
    model="fast"  → Llama-3.3-70B (general)
    model="large" → gpt-oss-120b (high-output docs/copy/HTML)
    """
    import openai
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    selected = _LARGE_MODEL if model == "large" else _FAST_MODEL
    kwargs: dict = dict(
        model=selected,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs, timeout=120.0)
    content = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


def generate_image(description: str, width: int = 1024, height: int = 1024) -> dict:
    """Generate an ad image using Janus-Pro-7B.
    Uses Llama-3.3-70B to write an optimized image prompt, then calls Janus.
    Returns: {prompt, url, base64, model}
    """
    import openai, requests

    # Step 1: Llama writes the Janus prompt
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    prompt_resp = client.chat.completions.create(
        model=_PROMPT_MODEL,
        messages=[{"role": "user", "content": (
            f"Write a detailed, vivid image generation prompt for FLUX-2-pro to create a high-quality ad image.\n"
            f"Ad description: {description}\n"
            f"Output ONLY the image prompt — no explanation, no quotes. "
            f"Be specific about style, lighting, composition, colors, and mood. "
            f"Optimized for a marketing/advertising use case."
        )}],
        max_tokens=300,
        temperature=0.8,
        timeout=30.0,
    )
    image_prompt = (prompt_resp.choices[0].message.content or description).strip()

    # Step 2: Janus generates the image
    try:
        headers = {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}
        resp = requests.post(
            f"{_DI_IMAGE_BASE}/{_IMAGE_MODEL}",
            headers=headers,
            json={"prompt": image_prompt, "width": width, "height": height, "num_images": 1},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # FLUX-2-pro returns image_url; schnell/dev return images array with base64
        url = data.get("image_url")
        images = data.get("images") or data.get("output") or []
        img = images[0] if images else None
        b64 = None
        if img:
            b64 = img.get("image") if isinstance(img, dict) else img
            if not url and isinstance(img, dict):
                url = img.get("url")
        return {
            "prompt": image_prompt,
            "url": url,
            "base64": b64,
            "model": _IMAGE_MODEL,
            "width": width,
            "height": height,
        }
    except Exception as e:
        return {"prompt": image_prompt, "error": str(e), "model": _IMAGE_MODEL}

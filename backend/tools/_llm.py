"""
Sync LLM helper for content-generation tools.

Models:
  "fast"    → DeepSeek-V4-Flash   (default, general purpose)
  "large"   → DeepSeek-V4-Flash   (docs, copy)
  "instruct" → Qwen3-235B      (strict rule-following: HTML, design, sales)
  "image"   → FLUX-2-pro          (image generation)
"""
import re
from backend.config import settings

_FAST_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_LARGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_INSTRUCT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
_IMAGE_MODEL = "black-forest-labs/FLUX-2-pro"
_PROMPT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
_DI_BASE = "https://api.deepinfra.com/v1/openai"


def _api_key() -> str:
    return settings.deepinfra_api_key or settings.planner_model_api_key or settings.agent_model_api_key


def generate(prompt: str, max_tokens: int | None = None, json_mode: bool = False, model: str = "large") -> str:
    """Call an LLM for content generation. Returns raw text.
    model="fast"     → DeepSeek-V4-Flash (general)
    model="large"    → gpt-oss-120b (high-output docs/copy)
    model="instruct" → Qwen3-235B (strict rule-following: HTML, design constraints)
    """
    import openai
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    if model == "large":
        selected = _LARGE_MODEL
    elif model == "instruct":
        selected = _INSTRUCT_MODEL
    else:
        selected = _FAST_MODEL
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


_IMAGE_COST = 0.03          # FLUX-2-pro cost per image in USD
_IMAGE_MONTHLY_BUDGET = 1.50  # per founder per month


def _check_image_budget(founder_id: str) -> tuple[bool, float]:
    """Returns (allowed, remaining_budget). Uses Redis for tracking."""
    try:
        import redis, calendar, datetime
        from backend.config import settings
        r = redis.from_url(settings.redis_url, decode_responses=True)
        now = datetime.datetime.utcnow()
        key = f"img_spend:{founder_id}:{now.year}:{now.month}"
        spent = float(r.get(key) or 0)
        remaining = _IMAGE_MONTHLY_BUDGET - spent
        return remaining >= _IMAGE_COST, remaining
    except Exception:
        return True, _IMAGE_MONTHLY_BUDGET  # fail open if Redis down


def _record_image_spend(founder_id: str) -> None:
    try:
        import redis, datetime
        from backend.config import settings
        r = redis.from_url(settings.redis_url, decode_responses=True)
        now = datetime.datetime.utcnow()
        key = f"img_spend:{founder_id}:{now.year}:{now.month}"
        r.incrbyfloat(key, _IMAGE_COST)
        # expire after 35 days
        if not r.ttl(key) or r.ttl(key) < 0:
            r.expire(key, 35 * 86400)
    except Exception:
        pass


def _save_image_to_vault(url: str | None, b64: str | None, prompt: str, founder_id: str, session_id: str) -> str | None:
    """Download/decode image and write to vault, embed in marketing note. Returns local path."""
    try:
        import base64 as _b64, datetime, requests
        from backend.config import settings
        from pathlib import Path
        vault = Path(settings.obsidian_vault).expanduser()
        img_dir = vault / "founders" / founder_id / "sessions" / session_id / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        img_path = img_dir / f"ad_{ts}.png"
        if b64:
            raw = b64.split(",", 1)[-1] if "," in b64 else b64
            img_path.write_bytes(_b64.b64decode(raw))
        elif url:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            img_path.write_bytes(resp.content)
        else:
            return None
        # Append embed to marketing.md
        note_path = vault / "founders" / founder_id / "sessions" / session_id / "marketing.md"
        with open(note_path, "a") as f:
            f.write(f"\n\n## Ad Image\n**Prompt:** {prompt}\n![[images/ad_{ts}.png]]\n")
        logger.info("Saved ad image to %s", img_path)
        return str(img_path)
    except Exception as e:
        logger.warning("Image vault save failed: %s", e)
        return None


def generate_image(description: str, width: int = 1024, height: int = 1024, founder_id: str = "", session_id: str = "") -> dict:
    """Generate an ad image using FLUX-2-pro via OpenAI-compatible images/generations endpoint.
    Uses gpt-oss-120b to write an optimized prompt, then calls FLUX. Returns b64_json.
    """
    import openai

    # Check monthly budget
    if founder_id:
        allowed, remaining = _check_image_budget(founder_id)
        if not allowed:
            return {"error": f"Monthly image budget exhausted (${_IMAGE_MONTHLY_BUDGET:.2f}/month). Resets next month.", "model": _IMAGE_MODEL}

    # Step 1: gpt-oss-120b writes the FLUX image prompt
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    prompt_resp = client.chat.completions.create(
        model=_PROMPT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a creative director at a top-tier advertising agency. "
                "Your job is to write image generation prompts for FLUX-2-pro diffusion model.\n\n"
                "FLUX responds best to SHORT, DENSE prompts — 40 to 80 words maximum. "
                "Long prompts degrade quality. Be precise, not verbose.\n\n"
                "Great FLUX ad prompts have:\n"
                "  • A single strong visual anchor (one person, one product, one moment)\n"
                "  • Specific lighting in 3-5 words ('soft morning window light', 'dramatic side rim')\n"
                "  • Emotional tone in 2-3 words ('quiet confidence', 'raw joy')\n"
                "  • Large open area of negative space for text — say exactly where (top third, left half)\n"
                "  • End with: 'editorial advertising photography, 35mm, magazine quality'\n\n"
                "DO NOT include: brand names, logos, text, words, watermarks, charts, multiple people unless essential.\n"
                "DO NOT use: 'photorealistic', 'ultra HD', 'masterpiece', 'beautiful' — these are filler.\n"
                "Output ONLY the prompt. No explanation. No quotes. No markdown."
            )},
            {"role": "user", "content": (
                f"Ad concept and brand context:\n{description}\n\n"
                "Write the FLUX-2-pro image prompt now. Keep it under 80 words."
            )},
        ],
        max_tokens=150,
        temperature=0.75,
        timeout=30.0,
    )
    image_prompt = (prompt_resp.choices[0].message.content or description).strip()

    # Step 2: FLUX generates image via OpenAI-compatible images/generations endpoint
    try:
        img_client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
        size = f"{width}x{height}"
        img_resp = img_client.images.generate(
            model=_IMAGE_MODEL,
            prompt=image_prompt,
            size=size,
            n=1,
            response_format="b64_json",
            timeout=120.0,
        )
        b64 = img_resp.data[0].b64_json if img_resp.data else None
        local_path = None
        if founder_id and b64:
            _record_image_spend(founder_id)
            if session_id:
                local_path = _save_image_to_vault(None, b64, image_prompt, founder_id, session_id)
        return {
            "prompt": image_prompt,
            "url": None,
            "base64": b64,
            "model": _IMAGE_MODEL,
            "width": width,
            "height": height,
            "local_path": local_path,
        }
    except Exception as e:
        return {"prompt": image_prompt, "error": str(e), "model": _IMAGE_MODEL}

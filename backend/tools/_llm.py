"""
Sync LLM helper for content-generation tools.

Models:
  "fast"      → DeepSeek-V4-Flash        (default, general purpose)
  "large"     → DeepSeek-V4-Flash        (docs, copy)
  "instruct"  → Llama-4-Scout-17B        (strict rule-following)
  "nemotron"  → DeepSeek-V4-Flash  (HTML/design generation)
  "image"     → FLUX-2-pro               (image generation)
"""
import logging
import re
from backend.config import settings

logger = logging.getLogger(__name__)

_FAST_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_LARGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_INSTRUCT_MODEL = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
_NEMOTRON_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_IMAGE_MODEL = "black-forest-labs/FLUX-2-pro"
_PROMPT_MODEL = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
_DI_BASE = "https://api.deepinfra.com/v1/openai"


def _api_key() -> str:
    return settings.deepinfra_api_key or settings.planner_model_api_key or settings.agent_model_api_key


def generate(prompt: str, max_tokens: int | None = None, json_mode: bool = False, model: str = "large", temperature: float = 0.7) -> str:
    """Call an LLM for content generation. Returns raw text.
    model="fast"     → DeepSeek-V4-Flash (general)
    model="large"    → gpt-oss-120b (high-output docs/copy)
    model="instruct" → Qwen3-235B (strict rule-following: HTML, design constraints)
    model="nemotron" → NVIDIA-Nemotron-3-Super-120B (HTML/design generation)
    """
    import openai
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    if model == "large":
        selected = _LARGE_MODEL
    elif model == "instruct":
        selected = _INSTRUCT_MODEL
    elif model == "nemotron":
        selected = _NEMOTRON_MODEL
    else:
        selected = _FAST_MODEL
    kwargs: dict = dict(
        model=selected,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs, timeout=300.0)
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

    # Step 1: Write an optimized FLUX prompt from the concept description
    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    prompt_resp = client.chat.completions.create(
        model=_PROMPT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a world-class art director who writes FLUX diffusion model prompts for premium brand advertising.\n\n"
                "FLUX PROMPT RULES — follow exactly:\n"
                "1. 50-70 words maximum. Every word must earn its place.\n"
                "2. Start with the SUBJECT: one specific person or object, described precisely (age, clothing, posture, expression).\n"
                "3. SETTING: one concrete environment (not 'studio' — say 'sunlit Copenhagen coffee shop', 'Tokyo rooftop at dusk').\n"
                "4. LIGHTING: 3-5 words, cinematic and specific ('low golden backlight', 'overcast diffused daylight', 'single tungsten key light').\n"
                "5. COMPOSITION: camera angle + negative space location for copy ('wide shot, large empty sky in top half', 'tight portrait, left third clear').\n"
                "6. MOOD: 2-3 words of emotional tone ('understated ambition', 'quiet focus', 'joyful momentum').\n"
                "7. END with exactly: 'shot on Leica, editorial advertising photography, magazine spread quality'\n\n"
                "HARD BANS — never include these:\n"
                "- No text, words, letters, logos, or watermarks in the scene\n"
                "- No 'photorealistic', 'hyperrealistic', 'ultra HD', 'masterpiece', '8K'\n"
                "- No vague moods ('beautiful', 'stunning', 'amazing')\n"
                "- No generic settings ('modern office', 'white background', 'studio')\n"
                "- No brand names\n\n"
                "Output ONLY the prompt text. No explanation, no quotes, no markdown, no prefix."
            )},
            {"role": "user", "content": (
                f"Brand/product concept:\n{description}\n\n"
                "Write the FLUX prompt now. Be specific and cinematic."
            )},
        ],
        max_tokens=120,
        temperature=0.6,
        timeout=30.0,
    )
    image_prompt = (prompt_resp.choices[0].message.content or description).strip()
    # Strip any accidental quotes or prefixes the model adds
    import re as _re
    image_prompt = _re.sub(r'^["\'`]|["\'`]$', '', image_prompt).strip()
    image_prompt = _re.sub(r'^(prompt|image|here is|here\'s)[:\s]+', '', image_prompt, flags=_re.IGNORECASE).strip()
    logger.info("FLUX prompt: %s", image_prompt)

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


def generate_logo(
    brand_name: str,
    style: str = "wordmark",
    colors: str = "",
    vibe: str = "",
    founder_id: str = "",
    session_id: str = "",
) -> dict:
    """Generate a logo.
    style: 'wordmark' (SVG text mark — crisp, no FLUX hallucinations) or 'icon' (FLUX abstract geometric mark).
    colors: brand hex codes or description.
    vibe: brand personality (minimal, bold, playful, luxury, tech).
    Returns {base64, style, brand_name} — base64 is PNG or SVG.
    """
    if style == "wordmark":
        # Use programmatic SVG — FLUX cannot reliably render text
        from backend.tools.logo_generator import generate_wordmark_svg
        return generate_wordmark_svg(brand_name=brand_name, colors=colors, vibe=vibe)

    # Icon: FLUX abstract geometric mark (no text)
    import openai

    if founder_id:
        allowed, _ = _check_image_budget(founder_id)
        if not allowed:
            return {"error": "Monthly image budget exhausted.", "style": style}

    client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
    system = (
        "You write FLUX prompts for app icon logos — a standalone abstract symbol, NO text whatsoever.\n\n"
        "Rules:\n"
        "- Pure white background, centered\n"
        "- ONE bold geometric shape or abstract mark (circle, interlocking rings, angular form, etc.)\n"
        "- Represents the brand concept abstractly — NOT literally (no handshakes, no people)\n"
        "- Specify exact colors using the brand palette\n"
        "- Scalable — looks good at 32×32px\n"
        "- End with: 'app icon, flat vector illustration, white background, no text, no letters'\n"
        "- 25-40 words. Output ONLY the prompt."
    )
    user = f"Brand: {brand_name}\nColors: {colors or 'deep navy and electric blue'}\nVibe: {vibe or 'modern tech startup'}\nWrite the FLUX icon prompt."

    resp = client.chat.completions.create(
        model=_PROMPT_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=70,
        temperature=0.5,
        timeout=20.0,
    )
    icon_prompt = (resp.choices[0].message.content or "").strip().strip('"\'')
    logger.info("Icon prompt: %s", icon_prompt)

    try:
        img_client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
        img_resp = img_client.images.generate(
            model=_IMAGE_MODEL,
            prompt=icon_prompt,
            size="1024x1024",
            n=1,
            response_format="b64_json",
            timeout=120.0,
        )
        b64 = img_resp.data[0].b64_json if img_resp.data else None
        if founder_id and b64:
            _record_image_spend(founder_id)
            if session_id:
                _save_image_to_vault(None, b64, icon_prompt, founder_id, session_id)
        return {"base64": b64, "prompt": icon_prompt, "style": "icon", "brand_name": brand_name}
    except Exception as e:
        return {"error": str(e), "style": "icon", "brand_name": brand_name}


def composite_logo_on_image(
    background_base64: str,
    logo_base64: str,
    position: str = "bottom-right",
    scale: float = 0.15,
) -> dict:
    """Composite a logo onto an ad image using PIL.
    position: 'bottom-right', 'bottom-left', 'top-right', 'top-left', 'bottom-center'
    scale: logo size as fraction of image width (0.10-0.25 recommended)
    Returns {base64} of the composited image.
    """
    try:
        import base64 as _b64
        from PIL import Image
        import io

        def _decode(b64str: str) -> Image.Image:
            raw = b64str.split(",", 1)[-1] if "," in b64str else b64str
            return Image.open(io.BytesIO(_b64.b64decode(raw))).convert("RGBA")

        bg = _decode(background_base64)
        logo = _decode(logo_base64)

        # Resize logo
        logo_w = int(bg.width * scale)
        logo_h = int(logo.height * (logo_w / logo.width))
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

        # Remove white background from logo (make it transparent)
        data = logo.getdata()
        new_data = []
        for r, g, b, a in data:
            if r > 240 and g > 240 and b > 240:
                new_data.append((r, g, b, 0))
            else:
                new_data.append((r, g, b, a))
        logo.putdata(new_data)

        margin = int(bg.width * 0.03)
        positions = {
            "bottom-right": (bg.width - logo_w - margin, bg.height - logo_h - margin),
            "bottom-left":  (margin, bg.height - logo_h - margin),
            "top-right":    (bg.width - logo_w - margin, margin),
            "top-left":     (margin, margin),
            "bottom-center": ((bg.width - logo_w) // 2, bg.height - logo_h - margin),
        }
        pos = positions.get(position, positions["bottom-right"])

        composite = bg.copy()
        composite.paste(logo, pos, logo)

        buf = io.BytesIO()
        composite.convert("RGB").save(buf, format="PNG")
        result_b64 = _b64.b64encode(buf.getvalue()).decode()
        return {"base64": result_b64, "position": position}
    except ImportError:
        return {"error": "PIL not installed — run: pip install Pillow", "base64": background_base64}
    except Exception as e:
        logger.warning("composite_logo_on_image failed: %s", e)
        return {"error": str(e), "base64": background_base64}

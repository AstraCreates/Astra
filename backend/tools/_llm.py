"""
Sync LLM helper for content-generation tools.

Models:
  "fast"      → MiMo-v2.5             (default, general purpose)
  "large"     → DeepSeek V4 Flash     (docs, copy)
  "instruct"  → DeepSeek V4 Flash     (strict rule-following)
  "nemotron"  → DeepSeek V4 Flash     (HTML/design generation)
  "image"     → Gemini 2.5 Flash Image (image generation via OpenRouter)
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import re
import time
from backend.config import settings

logger = logging.getLogger(__name__)

_FAST_MODEL = settings.or_light_model           # xiaomi/mimo-v2.5
_LARGE_MODEL = settings.or_highoutput_model     # deepseek/deepseek-v4-flash
_INSTRUCT_MODEL = settings.or_highoutput_model  # deepseek/deepseek-v4-flash
_NEMOTRON_MODEL = settings.or_highoutput_model  # deepseek/deepseek-v4-flash
_PROMPT_MODEL = settings.or_light_model         # xiaomi/mimo-v2.5
_OR_BASE = settings.openrouter_base_url
_GEMINI_IMAGE_MODEL = "google/gemini-2.5-flash-image"


def _or_api_key() -> str:
    from backend.core.key_rotator import get_openrouter_key
    return get_openrouter_key() or settings.openrouter_api_key or settings.planner_model_api_key


# ── Response cache ───────────────────────────────────────────────────────────────
# Redis-backed cache for generate() calls. Identical (model, prompt, params)
# within the TTL returns the cached response without hitting the LLM. Huge win
# for repeated content generation (e.g. the same doc regenerated across runs).
import os as _os
_CACHE_TTL = int(_os.environ.get("ASTRA_LLM_CACHE_TTL", "3600"))  # 1h default

# Module-level pooled Redis client — avoid a fresh connection per cache get/set.
_redis_client = None
_redis_retry_after = 0.0
_REDIS_RETRY_INTERVAL_SECONDS = 30.0


def _redis():
    global _redis_client, _redis_retry_after
    if _redis_client not in (None, False):
        return _redis_client
    now = time.monotonic()
    if _redis_client is False and now < _redis_retry_after:
        return None
    try:
        import redis
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        _redis_retry_after = 0.0
    except Exception:
        _redis_client = False
        _redis_retry_after = now + _REDIS_RETRY_INTERVAL_SECONDS
    return _redis_client or None


def _cache_namespace() -> str:
    try:
        frame = inspect.currentframe()
        caller = frame.f_back.f_back if frame and frame.f_back else None
        module = caller.f_globals.get("__name__", "") if caller else ""
        func = caller.f_code.co_name if caller else ""
        return f"{module}:{func}"
    except Exception:
        return "unknown"


def _cache_key(
    model: str,
    prompt: str,
    max_tokens: int | None,
    json_mode: bool,
    temperature: float,
    namespace: str,
) -> str:
    raw = f"{namespace}|{model}|{prompt}|{max_tokens}|{json_mode}|{temperature}"
    return "llm:gen:" + hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    r = _redis()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(key, _CACHE_TTL, value)
    except Exception:
        pass


def generate(prompt: str, max_tokens: int | None = None, json_mode: bool = False, model: str = "large", temperature: float = 0.7) -> str:
    """Call an LLM for content generation. Returns raw text.
    model="fast"     → MiMo-v2.5 (general)
    model="large"    → DeepSeek V4 Flash (high-output docs/copy)
    model="instruct" → DeepSeek V4 Flash (strict rule-following: HTML, design constraints)
    model="nemotron" → DeepSeek V4 Flash (HTML/design generation)
    """
    from backend.core.llm_client import get_or_client
    from backend.core.llm_cache import openrouter_extra_body

    if model == "large":
        selected = _LARGE_MODEL
    elif model == "instruct":
        selected = _INSTRUCT_MODEL
    elif model == "nemotron":
        selected = _NEMOTRON_MODEL
    else:
        selected = _FAST_MODEL

    # Response cache — skip the LLM call entirely on cache hit.
    cache_namespace = _cache_namespace()
    ckey = _cache_key(selected, prompt, max_tokens, json_mode, temperature, cache_namespace)
    cached = _cache_get(ckey)
    if cached is not None:
        return cached

    # json mode: our build/agent models have NO OpenRouter provider that supports
    # response_format — requesting it 404s/400s. Ask for JSON in the prompt instead;
    # callers parse leniently.
    content_prompt = prompt
    if json_mode:
        content_prompt = prompt + "\n\nRespond with ONLY a single valid JSON object. No prose, no markdown fences."
    kwargs: dict = dict(
        model=selected,
        messages=[{"role": "user", "content": content_prompt}],
        temperature=temperature,
    )
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    # Disable chain-of-thought reasoning AND let OpenRouter fall back across providers.
    # Without reasoning:{effort:none}, hy3-preview/mimo spend the entire max_tokens budget
    # on the <think> channel and return EMPTY content — which silently broke plan_next_goal
    # (no next goal proposed) and every other generate()-based content tool.
    kwargs["extra_body"] = openrouter_extra_body(selected)
    client = get_or_client(_OR_BASE, _or_api_key())
    resp = client.chat.completions.create(**kwargs, timeout=300.0)
    if not getattr(resp, "choices", None):
        return ""
    content = resp.choices[0].message.content or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if content:
        _cache_set(ckey, content)
    return content


_IMAGE_COST = 0.03          # Gemini image cost per generation in USD (approx)
# Per founder per month. Override with ASTRA_IMAGE_MONTHLY_BUDGET; set to 0 (or
# negative) for UNLIMITED — useful during development.
_IMAGE_MONTHLY_BUDGET = float(_os.environ.get("ASTRA_IMAGE_MONTHLY_BUDGET", "1.50"))


def _check_image_budget(founder_id: str) -> tuple[bool, float]:
    """Returns (allowed, remaining_budget). Uses Redis for tracking."""
    if _IMAGE_MONTHLY_BUDGET <= 0:
        return True, float("inf")  # unlimited (dev mode)
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
    """Generate an ad image using Gemini 2.5 Flash Image via OpenRouter.
    Uses MiMo to write an optimized prompt, then calls Gemini. Returns b64_json.
    """
    # Check monthly budget
    if founder_id:
        allowed, remaining = _check_image_budget(founder_id)
        if not allowed:
            return {"error": f"Monthly image budget exhausted (${_IMAGE_MONTHLY_BUDGET:.2f}/month). Resets next month.", "model": _GEMINI_IMAGE_MODEL}

    # Step 1: Write an optimized image prompt from the concept description
    from backend.core.llm_client import get_or_client
    from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
    client = get_or_client(_OR_BASE, _or_api_key())

    _IMG_SYSTEM = (
        "You are a world-class art director who writes diffusion model prompts for premium brand advertising.\n\n"
        "PROMPT RULES — follow exactly:\n"
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
    )
    _IMG_USER = f"Brand/product concept:\n{description}\n\nWrite the image prompt now. Be specific and cinematic."
    prompt_resp = client.chat.completions.create(
        model=_PROMPT_MODEL,
        messages=cacheable_messages([
            {"role": "system", "content": _IMG_SYSTEM},
            {"role": "user", "content": _IMG_USER},
        ], breakpoints=(0,)),  # cache stable system prompt only
        max_tokens=120,
        temperature=0.6,
        timeout=30.0,
        extra_body=openrouter_extra_body(_PROMPT_MODEL),
    )
    image_prompt = ((prompt_resp.choices[0].message.content if getattr(prompt_resp, "choices", None) else "") or description).strip()
    # Strip any accidental quotes or prefixes the model adds
    import re as _re
    image_prompt = _re.sub(r'^["\'`]|["\'`]$', '', image_prompt).strip()
    image_prompt = _re.sub(r'^(prompt|image|here is|here\'s)[:\s]+', '', image_prompt, flags=_re.IGNORECASE).strip()
    logger.info("Image prompt: %s", image_prompt)

    # Step 2: Gemini generates image via OpenRouter
    result = _gemini_image(image_prompt, founder_id, session_id)
    if "error" in result:
        return {"prompt": image_prompt, "error": result["error"], "model": _GEMINI_IMAGE_MODEL}
    return {
        "prompt": image_prompt,
        "url": None,
        "base64": result["base64"],
        "model": _GEMINI_IMAGE_MODEL,
        "width": width,
        "height": height,
        "local_path": result.get("local_path"),
    }


def _gemini_image(prompt: str, founder_id: str = "", session_id: str = "") -> dict:
    """Call Gemini image model via OpenRouter. Returns {base64, prompt} or {error}."""
    import re as _re
    if founder_id:
        allowed, _ = _check_image_budget(founder_id)
        if not allowed:
            return {"error": "Monthly image budget exhausted."}
    try:
        from backend.core.llm_client import get_or_client
        client = get_or_client(_OR_BASE, _or_api_key())
        resp = client.chat.completions.create(
            model=_GEMINI_IMAGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"modalities": ["image", "text"]},
            timeout=120.0,
        )
        b64 = None
        raw_msg = resp.model_dump().get("choices", [{}])[0].get("message", {})
        for img in (raw_msg.get("images") or []):
            url = (img.get("image_url") or {}).get("url", "") if isinstance(img, dict) else ""
            if url.startswith("data:"):
                b64 = url.split(",", 1)[-1]
                break
        if not b64:
            content = (resp.choices[0].message.content or "") if resp.choices else ""
            m = _re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)', content)
            if m:
                b64 = m.group(1)
        if founder_id and b64:
            _record_image_spend(founder_id)
            if session_id:
                _save_image_to_vault(None, b64, prompt[:120], founder_id, session_id)
        return {"base64": b64, "prompt": prompt}
    except Exception as e:
        return {"error": str(e), "prompt": prompt}


def generate_brand_board(
    brand_name: str,
    colors: str = "",
    vibe: str = "",
    tagline: str = "",
    founder_id: str = "",
    session_id: str = "",
) -> dict:
    """Generate a brand identity board using Gemini — multiple graphic compositions in a grid.
    Shows brand name in bold typographic treatments, geometric elements, color palette applied.
    Returns {base64, prompt, brand_name}.
    """
    primary_color = (colors.split()[0] if colors else "#0f172a")
    accent_color = (colors.split()[-1] if colors and len(colors.split()) > 1 else "#2563eb")

    prompt = (
        f"Create a brand identity mood board for '{brand_name}' in a clean grid layout. "
        f"Show 6 different graphic design compositions arranged in a 3x2 grid, each using the brand name and these colors: {colors or 'deep navy and electric blue'}. "
        f"Include: (1) Large bold oversized typography on solid color background, "
        f"(2) Brand name with abstract geometric line art, "
        f"(3) Horizontal banner with brand name and tagline '{tagline or 'Built for founders'}', "
        f"(4) Dark background with brand name in contrasting color, "
        f"(5) Square composition with geometric pattern and brand name, "
        f"(6) Minimal composition showing the brand mark with color swatches. "
        f"Visual style: {vibe or 'bold, modern, startup'}. "
        f"NO photographs, NO people, NO gradients unless subtle. "
        f"Pure graphic design — flat colors, geometric shapes, strong typography. "
        f"The brand name must be clearly legible in every panel. "
        f"Make it look like a premium brand identity presentation from a top design agency."
    )
    result = _gemini_image(prompt, founder_id, session_id)
    result["brand_name"] = brand_name
    return result


def generate_logo(
    brand_name: str,
    style: str = "wordmark",
    colors: str = "",
    vibe: str = "",
    founder_id: str = "",
    session_id: str = "",
) -> dict:
    """Generate a logo using Gemini. Both wordmark and icon use the SAME geometric motif so they match.
    style: 'wordmark' (name + icon side by side) or 'icon' (symbol only).
    Returns {base64, prompt, style, brand_name}.
    """
    # Extract a dark primary and bright accent from the color string for explicit contrast
    import re as _recol
    hexes = _recol.findall(r'#[0-9A-Fa-f]{6}', colors or '')
    primary_col = hexes[0] if hexes else '#0f172a'
    accent_col = hexes[1] if len(hexes) > 1 else '#2563eb'

    if style == "wordmark":
        prompt = (
            f"Design a professional wordmark logo for '{brand_name}'. "
            f"CRITICAL: The symbol and text MUST be in {primary_col} (dark) and {accent_col} (accent) — NOT white, NOT light. "
            f"Background: light grey #f8f8f8. "
            f"Layout: small bold geometric icon on the LEFT in {accent_col}, brand name '{brand_name}' in bold sans-serif on the RIGHT in {primary_col}. "
            f"The icon is a simple abstract shape (angular bracket, interlocking rings, bold geometric mark) — not a letter. "
            f"Style: {vibe or 'modern tech startup'}. Clean, no gradients, no shadows. "
            f"The text '{brand_name}' must be dark and clearly legible. Professional startup logo."
        )
    else:
        prompt = (
            f"Design a standalone icon/symbol for '{brand_name}'. "
            f"CRITICAL: The symbol MUST be in {accent_col} or {primary_col} — NOT white, NOT light colored. "
            f"Background: light grey #f8f8f8. "
            f"ONE bold abstract geometric shape — same visual motif as the wordmark icon. No text, no letters. "
            f"Style: {vibe or 'modern tech startup'}. Flat, no gradients, no shadows. "
            f"Large, centered, with generous padding. Must be clearly visible and dark against the background."
        )

    logger.info("Gemini logo (%s): %s", style, prompt[:120])
    result = _gemini_image(prompt, founder_id, session_id)
    result["style"] = style
    result["brand_name"] = brand_name
    return result


def composite_logo_on_image(
    background_base64: str = "",
    logo_base64: str = "",
    position: str = "bottom-right",
    scale: float = 0.15,
    # Common model alias names for the two required args
    image_base64: str = "",
    image: str = "",
    ad_image: str = "",
    background: str = "",
    logo: str = "",
    logo_wordmark: str = "",
    logo_image: str = "",
) -> dict:
    """Composite a logo onto an ad image using PIL.
    background_base64: base64 of the ad/background image (also accepted as image_base64, ad_image, image, background)
    logo_base64: base64 of the logo (also accepted as logo, logo_wordmark, logo_image)
    position: 'bottom-right', 'bottom-left', 'top-right', 'top-left', 'bottom-center'
    scale: logo size as fraction of image width (0.10-0.25 recommended)
    Returns {base64} of the composited image.
    """
    background_base64 = background_base64 or image_base64 or ad_image or image or background
    logo_base64 = logo_base64 or logo or logo_wordmark or logo_image
    if not background_base64:
        return {"error": "composite_logo_on_image requires background_base64 (the ad image). Pass the base64 from generate_ad_image output."}
    if not logo_base64:
        return {"error": "composite_logo_on_image requires logo_base64 (the logo). Read it from obsidian_read(agent='design') output field logo_wordmark."}
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

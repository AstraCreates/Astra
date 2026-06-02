"""SVG + PNG logo generator for wordmarks and icons.

Wordmark: programmatic SVG with brand name in a distinctive font.
Icon: FLUX-generated abstract geometric mark.
"""
import base64
import hashlib
import logging
import re

logger = logging.getLogger(__name__)

# Google Fonts that render well at small sizes and look premium
_FONT_STACK = {
    "minimal":  ("Syne", "800", "0.02em"),
    "bold":     ("Space Grotesk", "700", "0.0em"),
    "luxury":   ("Cormorant Garamond", "600", "0.08em"),
    "playful":  ("Plus Jakarta Sans", "800", "-0.01em"),
    "tech":     ("IBM Plex Mono", "700", "0.04em"),
    "editorial":("Libre Baskerville", "700", "0.01em"),
}
_DEFAULT_FONT = ("Syne", "800", "0.02em")


def _pick_font(vibe: str) -> tuple:
    vibe_l = (vibe or "").lower()
    for key, val in _FONT_STACK.items():
        if key in vibe_l:
            return val
    seed = int(hashlib.md5((vibe or "x").encode()).hexdigest(), 16)
    return list(_FONT_STACK.values())[seed % len(_FONT_STACK)]


def _parse_colors(colors: str, vibe: str) -> tuple[str, str]:
    """Extract primary and accent hex from a color string."""
    hexes = re.findall(r"#[0-9A-Fa-f]{6}", colors or "")
    if len(hexes) >= 2:
        return hexes[0], hexes[1]
    if len(hexes) == 1:
        return hexes[0], "#0099FF"
    # Fallback palette based on vibe
    vibe_l = (vibe or "").lower()
    palettes = {
        "luxury":   ("#1a0a2e", "#d4af37"),
        "tech":     ("#0a0f1e", "#00d4ff"),
        "playful":  ("#1a1a2e", "#ff6b6b"),
        "minimal":  ("#111111", "#2563eb"),
        "bold":     ("#0d0d0d", "#f97316"),
    }
    for key, pal in palettes.items():
        if key in vibe_l:
            return pal
    return ("#0f172a", "#2563eb")


def generate_wordmark_svg(
    brand_name: str,
    colors: str = "",
    vibe: str = "",
) -> dict:
    """Generate a wordmark logo as SVG + PNG base64.
    Returns {svg: str, base64: str, font: str, primary_color: str, accent_color: str}
    """
    try:
        primary, accent = _parse_colors(colors, vibe)
        font_name, font_weight, letter_spacing = _pick_font(vibe)
        font_url = f"https://fonts.googleapis.com/css2?family={font_name.replace(' ', '+')}:wght@{font_weight}&display=swap"

        # Icon: simple geometric mark (first letter styled)
        first = brand_name[0].upper() if brand_name else "A"
        icon_size = 32
        text_x = icon_size // 2
        text_y = icon_size // 2 + 10

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="320" height="64" viewBox="0 0 320 64">
  <defs>
    <style>@import url('{font_url}');</style>
  </defs>
  <!-- Icon mark -->
  <rect x="4" y="8" width="{icon_size}" height="{icon_size}" rx="8" fill="{primary}"/>
  <text x="{text_x}" y="{text_y}" font-family="'{font_name}', sans-serif" font-weight="{font_weight}" font-size="18" fill="{accent}" text-anchor="middle">{first}</text>
  <!-- Wordmark -->
  <text x="48" y="40" font-family="'{font_name}', sans-serif" font-weight="{font_weight}" font-size="28" fill="{primary}" letter-spacing="{letter_spacing}">{brand_name}</text>
</svg>"""

        # Convert SVG to PNG via cairosvg if available, else return SVG as b64
        try:
            import cairosvg
            png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=640, output_height=128)
            b64 = base64.b64encode(png_bytes).decode()
        except ImportError:
            # Fallback: encode SVG as base64 data URI (browsers can render it)
            b64 = base64.b64encode(svg.encode()).decode()
            logger.info("cairosvg not available — returning SVG base64")

        return {
            "svg": svg,
            "base64": b64,
            "format": "png" if "cairosvg" in str(type(b64)) else "svg",
            "font": font_name,
            "primary_color": primary,
            "accent_color": accent,
            "brand_name": brand_name,
            "style": "wordmark",
        }
    except Exception as e:
        logger.error("generate_wordmark_svg failed: %s", e)
        return {"error": str(e), "style": "wordmark"}

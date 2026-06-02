"""SVG wordmark logo generator.

Uses system fonts only — no external imports, valid XML, renders everywhere.
"""
import base64
import hashlib
import logging
import re
import xml.sax.saxutils as _xml

logger = logging.getLogger(__name__)

# System font stacks that look premium and are universally available
_FONT_STACKS = {
    "minimal":   ("system-ui, -apple-system, 'Helvetica Neue', sans-serif", "700", "0.06em"),
    "bold":      ("'Arial Black', 'Impact', sans-serif", "900", "0.0em"),
    "luxury":    ("Georgia, 'Times New Roman', serif", "700", "0.08em"),
    "playful":   ("'Trebuchet MS', 'Lucida Sans', sans-serif", "800", "-0.01em"),
    "tech":      ("'Courier New', 'Lucida Console', monospace", "700", "0.04em"),
    "editorial": ("Georgia, 'Palatino Linotype', serif", "700", "0.02em"),
}


def _pick_font(vibe: str) -> tuple:
    vibe_l = (vibe or "").lower()
    for key, val in _FONT_STACKS.items():
        if key in vibe_l:
            return val
    seed = int(hashlib.md5((vibe or "x").encode()).hexdigest(), 16)
    return list(_FONT_STACKS.values())[seed % len(_FONT_STACKS)]


def _parse_colors(colors: str, vibe: str) -> tuple[str, str]:
    hexes = re.findall(r"#[0-9A-Fa-f]{6}", colors or "")
    if len(hexes) >= 2:
        return hexes[0], hexes[1]
    if len(hexes) == 1:
        return hexes[0], "#0099FF"
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
    """Generate a wordmark SVG logo. Returns {svg, base64, style}."""
    try:
        primary, accent = _parse_colors(colors, vibe)
        font_stack, font_weight, letter_spacing = _pick_font(vibe)

        # Escape brand name for XML
        safe_name = _xml.escape(brand_name or "Brand")
        first = _xml.escape((brand_name[0] if brand_name else "A").upper())

        # Icon square with first letter
        icon_size = 40
        icon_r = 10  # corner radius

        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="72" viewBox="0 0 360 72">\n'
            f'  <rect width="360" height="72" fill="#ffffff"/>\n'
            f'  <rect x="6" y="16" width="{icon_size}" height="{icon_size}" rx="{icon_r}" fill="{primary}"/>\n'
            f'  <text x="{6 + icon_size // 2}" y="{16 + icon_size // 2 + 7}" '
            f'font-family="{font_stack}" font-weight="{font_weight}" font-size="20" '
            f'fill="{accent}" text-anchor="middle">{first}</text>\n'
            f'  <text x="58" y="47" font-family="{font_stack}" font-weight="{font_weight}" '
            f'font-size="30" fill="{primary}" letter-spacing="{letter_spacing}">{safe_name}</text>\n'
            '</svg>'
        )

        b64 = base64.b64encode(svg.encode("utf-8")).decode()

        return {
            "svg": svg,
            "base64": b64,
            "format": "svg",
            "primary_color": primary,
            "accent_color": accent,
            "brand_name": brand_name,
            "style": "wordmark",
        }
    except Exception as e:
        logger.error("generate_wordmark_svg failed: %s", e)
        return {"error": str(e), "style": "wordmark"}

"""Per-session creative variation helpers.

Identical founder prompts should still produce distinct brand directions across
different sessions. These helpers derive a stable creative brief from the
session ID so all agents in one run stay coherent while separate runs vary.
"""

from __future__ import annotations

import hashlib
from typing import Any


_ARCHETYPES = [
    {
        "name": "Crisp Operator",
        "brand_vibe": "professional",
        "name_style": "short operational compound, crisp consonants",
        "visual_style": "clean enterprise UI, precise grids, confident whitespace",
        "palette_hint": "deep navy, cobalt, cool slate, restrained green accent",
        "typography_hint": "Inter plus IBM Plex Sans, compact headings",
    },
    {
        "name": "Warm Catalyst",
        "brand_vibe": "friendly",
        "name_style": "approachable invented word, soft vowels",
        "visual_style": "warm SaaS, rounded surfaces, optimistic illustrations",
        "palette_hint": "violet, coral, honey, warm off-white",
        "typography_hint": "Manrope plus Source Sans 3, generous line height",
    },
    {
        "name": "Signal Lab",
        "brand_vibe": "innovative",
        "name_style": "technical, signal/data metaphor, futuristic but pronounceable",
        "visual_style": "dark analytical interface, luminous accents, data motifs",
        "palette_hint": "ink black, indigo, cyan, electric teal",
        "typography_hint": "Space Grotesk plus JetBrains Mono",
    },
    {
        "name": "Calm System",
        "brand_vibe": "calm",
        "name_style": "clear nature/system metaphor, trustworthy and quiet",
        "visual_style": "airy product experience, soft gradients, low-noise hierarchy",
        "palette_hint": "sky blue, mint, sand, soft white",
        "typography_hint": "Geist plus Lora accent, relaxed spacing",
    },
    {
        "name": "Bold Frontier",
        "brand_vibe": "bold",
        "name_style": "punchy one-word name, energetic and memorable",
        "visual_style": "high-contrast launch brand, oversized type, sharp hero moments",
        "palette_hint": "near-black, flame orange, vivid magenta, acid green",
        "typography_hint": "Satoshi plus Archivo Black, strong display weight",
    },
    {
        "name": "Premium Studio",
        "brand_vibe": "luxury",
        "name_style": "elevated concise name, editorial or atelier feel",
        "visual_style": "premium editorial layout, refined motion, polished surfaces",
        "palette_hint": "charcoal, ivory, muted gold, burgundy",
        "typography_hint": "Canela-style serif plus Neue Haas-style sans",
    },
]

_MOTIFS = [
    "orbit",
    "ledger",
    "forge",
    "prism",
    "keystone",
    "lattice",
    "compass",
    "switchboard",
    "signal",
    "atlas",
    "beam",
    "harbor",
]


def _pick(items: list[Any], digest: str, offset: int = 0) -> Any:
    idx = int(digest[offset : offset + 8], 16) % len(items)
    return items[idx]


def build_creative_brief(session_id: str, goal: str = "") -> dict[str, Any]:
    """Return a stable creative brief for one session."""
    raw = f"{session_id}|{goal}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    archetype = dict(_pick(_ARCHETYPES, digest, 0))
    motif = _pick(_MOTIFS, digest, 8)
    variant = digest[:10]
    return {
        "creative_seed": variant,
        "archetype": archetype["name"],
        "brand_vibe": archetype["brand_vibe"],
        "name_style": archetype["name_style"],
        "visual_style": archetype["visual_style"],
        "palette_hint": archetype["palette_hint"],
        "typography_hint": archetype["typography_hint"],
        "motif": motif,
        "name_instruction": (
            f"Use the {archetype['name']} direction. Prefer a {archetype['name_style']} "
            f"with a subtle {motif} association. Avoid generic names and avoid reusing "
            f"names from other sessions. Creative seed: {variant}."
        ),
        "design_instruction": (
            f"Use the {archetype['name']} direction: {archetype['visual_style']}. "
            f"Palette hint: {archetype['palette_hint']}. Typography hint: "
            f"{archetype['typography_hint']}. Motif: {motif}. Creative seed: {variant}."
        ),
    }

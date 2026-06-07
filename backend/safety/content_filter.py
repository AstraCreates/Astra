"""Initial-prompt validation: minimum length + disallowed-content screen.

Applied to the founder goal at /goal submission before any agent runs. Keeps the
platform from spending a run on too-thin prompts and refuses to build clearly
disallowed products. Deterministic (regex) so it is fast and predictable; tune the
word floor with ASTRA_MIN_GOAL_WORDS.
"""
from __future__ import annotations

import os
import re

# Minimum words a founder goal must contain. A real product brief is rarely under
# this; very short prompts produce weak, generic runs. Override via env.
MIN_GOAL_WORDS = int(os.environ.get("ASTRA_MIN_GOAL_WORDS", "5"))

# Disallowed-content patterns. Each entry: (category, compiled regex). Phrased to
# target clearly harmful product intent while avoiding obvious false positives
# (e.g. "security research", "weapons-grade coffee"). Word boundaries used.
_BANNED: list[tuple[str, re.Pattern]] = [
    ("child sexual abuse",
     re.compile(r"\b(child|minor|underage|cp|csam|pre[- ]?teen|loli)\b.{0,30}\b(porn|sex|nude|explicit|abuse|exploit)", re.I)),
    ("child sexual abuse",
     re.compile(r"\b(csam|child\s+porn|child\s+sexual)\b", re.I)),
    ("weapons / explosives",
     re.compile(r"\b(build|make|manufactur\w*|3d[- ]?print|sell|traffic\w*)\b.{0,40}\b(bomb|explosive|ied|grenade|firearm|ghost\s+gun|silencer|bioweapon|nerve\s+agent|chemical\s+weapon|dirty\s+bomb)", re.I)),
    ("weapons / explosives",
     re.compile(r"\b(bioweapon|nerve\s+agent|chemical\s+weapon|dirty\s+bomb|pipe\s+bomb)\b", re.I)),
    ("illegal drugs",
     re.compile(r"\b(synthesi\w*|manufactur\w*|cook|produce|make|sell|traffic\w*|distribut\w*)\b.{0,30}\b(meth\w*|fentanyl|heroin|cocaine|mdma|cartel|illegal\s+drugs?)", re.I)),
    ("illegal drugs",
     re.compile(r"\b(meth|methamphetamine|fentanyl|heroin|cocaine|mdma)\b.{0,30}\b(synthesi\w*|manufactur\w*|cook|produc\w*|recipe|lab|guide|how[- ]?to)\b", re.I)),
    ("terrorism / mass violence",
     re.compile(r"\b(terror\w*|mass\s+shooting|genocide|ethnic\s+cleansing|assassinat\w*)\b", re.I)),
    ("human trafficking",
     re.compile(r"\b(human|sex|child)\s+trafficking\b", re.I)),
    ("malware / cyber-harm",
     re.compile(r"\b(build|create|write|sell|deploy)\b.{0,30}\b(ransomware|malware|spyware|keylogger|botnet|phishing\s+kit|credential\s+stealer)", re.I)),
    ("self-harm",
     re.compile(r"\b(encourage|promote|how\s+to|help\s+(?:me|users?))\b.{0,30}\b(suicide|self[- ]?harm)", re.I)),
]


def screen_goal(text: str) -> tuple[bool, str]:
    """Validate a founder goal. Returns (ok, reason). reason is empty when ok."""
    raw = (text or "").strip()
    if not raw:
        return False, "Goal is empty. Describe what you want to build."

    words = re.findall(r"\b[\w'-]+\b", raw)
    if len(words) < MIN_GOAL_WORDS:
        return False, (
            f"Goal too short — use at least {MIN_GOAL_WORDS} words. "
            f"Describe the product, who it's for, and the problem it solves."
        )

    for category, pattern in _BANNED:
        if pattern.search(raw):
            return False, (
                f"This request can't be built — it appears to involve {category}, "
                f"which is outside what Astra can help with."
            )

    return True, ""

"""Deterministic per-founder feature rollout controls."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

@dataclass(frozen=True)
class RuntimeFeature:
    enabled: bool
    percentage: int


def _bucket(founder_id: str, feature: str) -> int:
    digest = hashlib.sha256(f"{feature}:{founder_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def enabled(feature: str, founder_id: str = "") -> bool:
    from backend.config import settings
    from backend.runtime.circuit_breaker import is_disabled
    if is_disabled(feature):
        return False
    global_enabled = bool(getattr(settings, f"astra_{feature}", False))
    if not global_enabled:
        return False
    percentage = max(0, min(100, int(getattr(settings, f"astra_{feature}_rollout_percent", 100))))
    return percentage >= 100 or _bucket(founder_id or "anonymous", feature) < percentage

"""Process-local emergency rollback switches for staged runtime features."""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_disabled: dict[str, dict] = {}


def disable(feature: str, reason: str) -> None:
    with _lock:
        _disabled[feature] = {"reason": reason, "disabled_at": time.time()}


def enable(feature: str) -> None:
    with _lock:
        _disabled.pop(feature, None)


def is_disabled(feature: str) -> bool:
    with _lock:
        return feature in _disabled


def status() -> dict[str, dict]:
    with _lock:
        return dict(_disabled)

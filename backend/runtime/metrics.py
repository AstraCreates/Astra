"""In-process counters for agent runtime rollout monitoring."""
from __future__ import annotations

import threading
from collections import Counter
from typing import Any

_lock = threading.Lock()
_counters: Counter[str] = Counter()


def increment(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] += value


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_counters)


def prometheus_lines() -> list[str]:
    return [
        f"astra_agent_runtime_{name} {value}"
        for name, value in sorted(snapshot().items())
    ]

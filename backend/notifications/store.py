"""Per-founder push subscription storage."""
from __future__ import annotations
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_mu = threading.Lock()


def _get_lock(founder_id: str) -> threading.Lock:
    with _locks_mu:
        if founder_id not in _locks:
            _locks[founder_id] = threading.Lock()
        return _locks[founder_id]


def _dir() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    d = Path(vault) / "push_subscriptions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_id(raw: str) -> str:
    return "".join(c for c in raw if c.isalnum() or c in ("_", "-", "."))[:120] or "unknown"


def _path(founder_id: str) -> Path:
    return _dir() / f"{_safe_id(founder_id)}.json"


def save_subscription(founder_id: str, subscription: dict) -> None:
    """Upsert a push subscription (keyed by endpoint)."""
    lock = _get_lock(founder_id)
    with lock:
        p = _path(founder_id)
        try:
            subs = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            subs = []
        endpoint = subscription.get("endpoint", "")
        subs = [s for s in subs if s.get("endpoint") != endpoint]
        subs.append(subscription)
        subs = subs[-5:]  # keep last 5 (multiple devices/browsers)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(subs, indent=2))
        tmp.replace(p)


def get_subscriptions(founder_id: str) -> list[dict]:
    p = _path(founder_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()) or []
    except Exception:
        return []


def remove_subscription(founder_id: str, endpoint: str) -> None:
    lock = _get_lock(founder_id)
    with lock:
        p = _path(founder_id)
        try:
            subs = json.loads(p.read_text()) if p.exists() else []
            subs = [s for s in subs if s.get("endpoint") != endpoint]
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(subs, indent=2))
            tmp.replace(p)
        except Exception:
            pass

"""Public share tokens for the proof page.

Maps an unguessable token -> (founder_id, company_id) so a public, unauthenticated
proof page can render a company's verification receipts (and re-verify live) without
exposing internal ids. One token per company; rotating issues a fresh token.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _path() -> Path:
    root = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "share"
    root.mkdir(parents=True, exist_ok=True)
    return root / "tokens.json"


def _load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(p)


def create_share(founder_id: str, company_id: str | None = None) -> str:
    """Issue (or rotate) a share token for a company. Returns the token."""
    resolved = company_id or founder_id
    token = secrets.token_urlsafe(16)
    with _lock:
        data = _load()
        # Drop any prior token for this company (one active token per company).
        data = {t: v for t, v in data.items()
                if not (v.get("founder_id") == founder_id and v.get("company_id") == resolved)}
        data[token] = {
            "founder_id": founder_id,
            "company_id": resolved,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save(data)
    return token


def resolve_share(token: str) -> Optional[dict[str, Any]]:
    """Resolve a token to {founder_id, company_id}, or None if unknown."""
    if not token:
        return None
    with _lock:
        return _load().get(token)

"""Founder-level continuous company operating goal storage."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _root() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/data/astra_docs")) / "missions" / "company_goals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _goal_path(founder_id: str) -> Path:
    safe = "".join(ch for ch in founder_id if ch.isalnum() or ch in {"_", "-", "."})[:120] or "founder"
    return _root() / f"{safe}.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_company_goal(founder_id: str) -> dict[str, Any] | None:
    with _lock:
        path = _goal_path(founder_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("company_goal: failed to read %s: %s", path, exc)
            return None


def upsert_company_goal(
    founder_id: str,
    *,
    north_star: str,
    company_goal: str,
    source_session_id: str,
    status: str = "operating",
    kpis: list[dict[str, Any]] | None = None,
    notion_database_id: str | None = None,
    notion_url: str | None = None,
) -> dict[str, Any]:
    with _lock:
        path = _goal_path(founder_id)
        if path.exists():
            try:
                current = json.loads(path.read_text())
            except Exception:
                current = {"founder_id": founder_id, "created_at": _now_iso()}
        else:
            current = {"founder_id": founder_id, "created_at": _now_iso()}
        current.update(
            {
                "founder_id": founder_id,
                "north_star": north_star,
                "company_goal": company_goal,
                "source_session_id": source_session_id,
                "status": status,
                "kpis": list(kpis or []),
                "updated_at": _now_iso(),
            }
        )
        if notion_database_id is not None:
            current["notion_database_id"] = notion_database_id
        if notion_url is not None:
            current["notion_url"] = notion_url
        path.write_text(json.dumps(current, indent=2, sort_keys=True))
        return current

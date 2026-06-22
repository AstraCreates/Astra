"""Modular dashboard — agents call these to add/remove tiles on the founder's dashboard."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_FOUNDER_ID_RE = re.compile(r"^[A-Za-z0-9_@.-]{1,128}$")

from backend.config import settings

# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(founder_id: str) -> threading.Lock:
    lk = _locks.get(founder_id)
    if lk is None:
        with _locks_guard:
            lk = _locks.get(founder_id)
            if lk is None:
                lk = threading.Lock()
                _locks[founder_id] = lk
    return lk


def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", settings.obsidian_vault)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_path(founder_id: str) -> Path:
    if not _FOUNDER_ID_RE.match(founder_id):
        raise ValueError(f"invalid founder_id: {founder_id!r}")
    d = _vault() / "dashboard"
    d.mkdir(parents=True, exist_ok=True)
    p = (d / f"{founder_id}.json").resolve()
    if d.resolve() not in p.parents:
        raise ValueError("path escape detected")
    return p


def _load(founder_id: str) -> list[dict]:
    p = _store_path(founder_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save(founder_id: str, elements: list[dict]) -> None:
    p = _store_path(founder_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(elements, indent=2))
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

_VALID_TYPES = {
    "metric", "chart", "table", "button", "monitor",
    "progress", "markdown", "list", "status_board", "embed",
}
_VALID_SIZES = {"small", "medium", "big", "xl"}


def dashboard_add_element(
    founder_id: str,
    title: str,
    type: str,
    size: str,
    config: dict,
    section: str = "",
    order: int = -1,
    refresh_interval: int = 0,
    agent: str = "",
    session_id: str = "",
    data_source: Optional[dict] = None,
) -> dict:
    """Add a tile to the founder's dashboard canvas.

    type: metric|chart|table|button|monitor|progress|markdown|list|status_board|embed
    size: small (25%)|medium (50%)|big (50% tall)|xl (full width)

    config schemas by type:
      metric:       {value, unit, label, trend?, trend_up?, color?}
      chart:        {chart_type:"line"|"bar"|"area"|"pie", data:[{x,y},...], x_label?, y_label?, colors?}
      table:        {columns:str[], rows:str[][], max_rows?}
      button:       {label, action:"new_goal"|"open_url", payload, variant?, icon?}
      monitor:      {session_id?, poll_url?, status_map?, fields?}
      progress:     {value, max, label, color?, show_percent?}
      markdown:     {content}
      list:         {items:str[], style:"bullet"|"numbered"|"checklist", checked?}
      status_board: {indicators:[{label, status:"ok"|"warn"|"error"|"pending", detail?, url?},...]}
      embed:        {url, height?}

    data_source (optional, for live external data):
      {tool: str, params: dict, field_map: {tool_result_key: config_key}}
      When refresh_interval > 0, frontend calls /dashboard/{founder_id}/elements/{id}/refresh
      which invokes the tool and overlays mapped values onto config.
    """
    if not founder_id:
        return {"ok": False, "error": "founder_id required"}
    t = type.lower().strip()
    s = size.lower().strip()
    if t not in _VALID_TYPES:
        t = "markdown"
    if s not in _VALID_SIZES:
        s = "medium"

    element: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "founder_id": founder_id,
        "title": title or "",
        "type": t,
        "size": s,
        "config": config or {},
        "section": section or "",
        "order": order,
        "refresh_interval": max(0, int(refresh_interval)),
        "agent": agent or "",
        "session_id": session_id or "",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if data_source:
        element["data_source"] = data_source

    with _lock(founder_id):
        elements = _load(founder_id)
        # Replace existing tile from same agent+section+title (dedup across re-runs).
        # This prevents stale tiles accumulating every run.
        def _is_stale(e: dict) -> bool:
            return (
                e.get("agent") == agent
                and e.get("section", "") == (section or "")
                and e.get("title", "").strip().lower() == title.strip().lower()
            )
        elements = [e for e in elements if not _is_stale(e)]
        # Also cap total tiles to 20 — oldest non-pinned tiles drop off
        MAX_TILES = 20
        if len(elements) >= MAX_TILES:
            elements = elements[-(MAX_TILES - 1):]
        if order < 0 or order >= len(elements):
            elements.append(element)
        else:
            elements.insert(order, element)
        _save(founder_id, elements)

    return {"id": element["id"], "ok": True}


def dashboard_remove_element(founder_id: str, element_id: str) -> dict:
    """Remove a tile by ID from the founder's dashboard."""
    if not founder_id or not element_id:
        return {"ok": False, "error": "founder_id and element_id required"}
    with _lock(founder_id):
        elements = _load(founder_id)
        before = len(elements)
        elements = [e for e in elements if e.get("id") != element_id]
        _save(founder_id, elements)
    return {"ok": True, "removed": before - len(elements)}


def dashboard_clear(founder_id: str, section: str = "") -> dict:
    """Remove all tiles (or all tiles in a section) from the founder's dashboard."""
    if not founder_id:
        return {"ok": False, "error": "founder_id required"}
    with _lock(founder_id):
        elements = _load(founder_id)
        before = len(elements)
        if section:
            elements = [e for e in elements if e.get("section", "") != section]
        else:
            elements = []
        _save(founder_id, elements)
    return {"ok": True, "removed": before - len(elements)}


def dashboard_get(founder_id: str) -> dict:
    """Return all dashboard tiles for a founder."""
    if not founder_id:
        return {"ok": False, "error": "founder_id required", "elements": []}
    with _lock(founder_id):
        elements = _load(founder_id)
    return {"ok": True, "elements": elements, "count": len(elements)}

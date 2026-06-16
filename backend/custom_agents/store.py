"""Durable per-founder store for custom agent specs.

Storage layout (mirrors skills/store.py):
  $OBSIDIAN_VAULT/custom_agents/{founder_id}/index.json
    {
      "<agent_id>": {
        "id": "custom_<founder>_<slug>",
        "founder_id": "...",
        "name": "My SEO Watcher",
        "slug": "my-seo-watcher",
        "role": "<the founder's prompt — becomes the Agent role>",
        "tool_keys": ["web_search", "generate_pdf", ...],
        "model": "small" | "highoutput" | "<explicit model id>",
        "use_computer": false,
        "schedule": {                       # null = manual only
          "every_days": 3,
          "enabled": true,
          "last_run_at": "...",
          "next_run_at": "..."
        },
        "created_at": "...",
        "updated_at": "..."
      }
    }

Thread-safe via a single process-level Lock.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ── Paths ────────────────────────────────────────────────────────────────────

def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dir(founder_id: str) -> Path:
    d = _vault() / "custom_agents" / founder_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(founder_id: str) -> Path:
    return _dir(founder_id) / "index.json"


def _load_index(founder_id: str) -> dict[str, Any]:
    p = _index_path(founder_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_index(founder_id: str, index: dict[str, Any]) -> None:
    _index_path(founder_id).write_text(json.dumps(index, indent=2, sort_keys=True))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or uuid.uuid4().hex[:8]


def make_agent_id(founder_id: str, name: str) -> str:
    """Globally-unique, founder-namespaced agent id usable as an orchestrator key."""
    return f"custom_{founder_id}_{_slugify(name)}"


# ── Schedule helpers ──────────────────────────────────────────────────────────

def _normalize_schedule(schedule: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schedule:
        return None
    try:
        every_days = int(schedule.get("every_days") or 0)
    except (TypeError, ValueError):
        every_days = 0
    if every_days <= 0:
        return None
    enabled = bool(schedule.get("enabled", True))
    last_run_at = schedule.get("last_run_at")
    run_at_hour, run_at_minute = _parse_run_at(schedule)
    # next_run: now + interval if never run, else last + interval. If a
    # time-of-day was given, the next run lands on that clock time (UTC)
    # rather than "whenever the scheduler happens to tick."
    next_run_at = schedule.get("next_run_at") or _next_run_at(
        time.time(), 0 if run_at_hour is not None else every_days, run_at_hour, run_at_minute
    )
    return {
        "every_days": every_days,
        "enabled": enabled,
        "run_at_hour": run_at_hour,
        "run_at_minute": run_at_minute,
        "last_run_at": last_run_at,
        "next_run_at": next_run_at,
    }


def _parse_run_at(schedule: dict[str, Any]) -> tuple[int | None, int | None]:
    """Pull out an optional UTC time-of-day (hour, minute) the schedule should fire at."""
    hour = schedule.get("run_at_hour")
    minute = schedule.get("run_at_minute")
    if hour is None or minute is None:
        return None, None
    try:
        hour = int(hour)
        minute = int(minute)
    except (TypeError, ValueError):
        return None, None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, None
    return hour, minute


def _now_plus_days(days: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + days * 86400))


def _next_run_at(base_epoch: float, days_offset: int, hour: int | None, minute: int | None) -> str:
    """Next run timestamp, `days_offset` days from `base_epoch`'s date.

    With no hour/minute pinned, this is just base + days_offset (old
    behavior). With a pinned time-of-day, the result lands on that clock
    time (UTC); if that would be in the past relative to base_epoch (only
    possible when days_offset==0), it rolls forward one day.
    """
    if hour is None or minute is None:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_epoch + days_offset * 86400))
    base = time.gmtime(base_epoch)
    target = calendar.timegm((base.tm_year, base.tm_mon, base.tm_mday, hour, minute, 0, 0, 0, 0))
    target += days_offset * 86400
    if target <= base_epoch:
        target += 86400
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(target))


# ── Public CRUD ───────────────────────────────────────────────────────────────

def create_agent(
    founder_id: str,
    *,
    name: str,
    role: str,
    tool_keys: list[str] | None = None,
    model: str = "highoutput",
    use_computer: bool = False,
    schedule: dict[str, Any] | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Create + persist a custom agent spec. Returns the spec dict."""
    agent_id = make_agent_id(founder_id, name)
    spec: dict[str, Any] = {
        "id": agent_id,
        "founder_id": founder_id,
        "company_id": company_id or founder_id,
        "name": name,
        "slug": _slugify(name),
        "role": role,
        "tool_keys": list(tool_keys or []),
        "model": model or "highoutput",
        "use_computer": bool(use_computer),
        "schedule": _normalize_schedule(schedule),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        index = _load_index(founder_id)
        existing = index.get(agent_id)
        if existing and existing.get("name") != name:
            # ID collision with a differently-named (renamed) agent — use a unique suffix
            # to avoid silently destroying the renamed agent's data.
            agent_id = f"{agent_id}_{uuid.uuid4().hex[:6]}"
            spec["id"] = agent_id
        elif existing:
            # True same-name re-creation: preserve the original created_at.
            spec["created_at"] = existing.get("created_at", spec["created_at"])
        index[agent_id] = spec
        _save_index(founder_id, index)
    logger.info("custom_agent created: %s (founder=%s)", agent_id, founder_id)
    return spec


def get_agent(founder_id: str, agent_id: str) -> dict[str, Any] | None:
    with _lock:
        return _load_index(founder_id).get(agent_id)


def list_agents(founder_id: str) -> list[dict[str, Any]]:
    with _lock:
        index = _load_index(founder_id)
    agents = list(index.values())
    agents.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return agents


def update_agent(
    founder_id: str,
    agent_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    tool_keys: list[str] | None = None,
    model: str | None = None,
    use_computer: bool | None = None,
    schedule: dict[str, Any] | None = None,
    _schedule_explicit: bool = False,
) -> dict[str, Any] | None:
    """Patch mutable fields. Pass _schedule_explicit=True to allow clearing schedule with None."""
    with _lock:
        index = _load_index(founder_id)
        spec = index.get(agent_id)
        if spec is None:
            return None
        if name is not None:
            spec["name"] = name
            spec["slug"] = _slugify(name)
        if role is not None:
            spec["role"] = role
        if tool_keys is not None:
            spec["tool_keys"] = list(tool_keys)
        if model is not None:
            spec["model"] = model
        if use_computer is not None:
            spec["use_computer"] = bool(use_computer)
        if schedule is not None or _schedule_explicit:
            spec["schedule"] = _normalize_schedule(schedule)
        spec["updated_at"] = _now()
        index[agent_id] = spec
        _save_index(founder_id, index)
    return spec


def delete_agent(founder_id: str, agent_id: str) -> bool:
    with _lock:
        index = _load_index(founder_id)
        if agent_id not in index:
            return False
        del index[agent_id]
        _save_index(founder_id, index)
    logger.info("custom_agent deleted: %s (founder=%s)", agent_id, founder_id)
    return True


def mark_ran(founder_id: str, agent_id: str) -> dict[str, Any] | None:
    """Stamp a scheduled agent as run now and roll next_run_at forward."""
    with _lock:
        index = _load_index(founder_id)
        spec = index.get(agent_id)
        if spec is None:
            return None
        sched = spec.get("schedule")
        if sched:
            sched["last_run_at"] = _now()
            sched["next_run_at"] = _next_run_at(
                time.time(),
                int(sched.get("every_days") or 1),
                sched.get("run_at_hour"),
                sched.get("run_at_minute"),
            )
            spec["schedule"] = sched
            spec["updated_at"] = _now()
            index[agent_id] = spec
            _save_index(founder_id, index)
    return spec


# ── Cross-founder index (for the scheduler) ───────────────────────────────────

def _founder_ids() -> list[str]:
    root = _vault() / "custom_agents"
    if not root.exists():
        return []
    return [p.name for p in root.iterdir() if p.is_dir()]


def all_scheduled_agents() -> list[dict[str, Any]]:
    """Every custom agent (across founders) that has an enabled schedule."""
    out: list[dict[str, Any]] = []
    for founder_id in _founder_ids():
        for spec in list_agents(founder_id):
            sched = spec.get("schedule")
            if sched and sched.get("enabled"):
                out.append(spec)
    return out


def is_due(spec: dict[str, Any], now_epoch: float | None = None) -> bool:
    """True if a scheduled agent's next_run_at is in the past."""
    sched = spec.get("schedule") or {}
    if not sched.get("enabled"):
        return False
    next_run = sched.get("next_run_at")
    if not next_run:
        return True
    try:
        nxt = calendar.timegm(time.strptime(next_run, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return True
    return (now_epoch or time.time()) >= nxt

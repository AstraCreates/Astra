from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.core.session_store import session_dir
from backend.tools.web_tasks.models import WebTaskSnapshot

_TASK_SESSIONS: dict[str, dict] = {}


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def web_task_dir(session_id: str, task_id: str) -> Path:
    return session_dir(session_id or task_id) / "web_tasks" / task_id


def snapshot_path(session_id: str, task_id: str) -> Path:
    return web_task_dir(session_id, task_id) / "snapshot.json"


def save_snapshot(snapshot: WebTaskSnapshot) -> None:
    snapshot.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_atomic(
        snapshot_path(snapshot.request.session_id, snapshot.task_id),
        json.dumps(snapshot.to_dict(), indent=2, sort_keys=True),
    )


def load_snapshot(session_id: str, task_id: str) -> WebTaskSnapshot | None:
    path = snapshot_path(session_id, task_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return WebTaskSnapshot.from_dict(payload)


def save_screenshot(session_id: str, task_id: str, name: str, payload: bytes) -> str:
    path = web_task_dir(session_id, task_id) / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path)


def create_task_session(task_id: str) -> dict:
    session = _TASK_SESSIONS.get(task_id)
    if session is None:
        session = {
            "status": "running",
            "event_queue": asyncio.Queue(),
            "task": None,
            "last_result": None,
        }
        _TASK_SESSIONS[task_id] = session
    return session


def get_task_session(task_id: str) -> dict | None:
    return _TASK_SESSIONS.get(task_id)


def set_task_status(task_id: str, status: str, result: dict | None = None) -> dict | None:
    session = get_task_session(task_id)
    if not session:
        return None
    session["status"] = status
    if result is not None:
        session["last_result"] = result
    return session


async def emit_task_event(task_id: str, event: dict) -> None:
    session = create_task_session(task_id)
    await session["event_queue"].put(event)


async def close_task_session(task_id: str, result: dict | None = None) -> None:
    session = get_task_session(task_id)
    if not session:
        return
    if result is not None:
        session["last_result"] = result
    session["status"] = "done"
    await session["event_queue"].put(None)


def clear_task_session(task_id: str) -> None:
    _TASK_SESSIONS.pop(task_id, None)

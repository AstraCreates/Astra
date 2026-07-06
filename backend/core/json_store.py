"""Shared primitives for small JSON-backed stores."""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()

T = TypeVar("T")


def json_file_lock(path: str | Path) -> threading.RLock:
    """Return a process-local RLock for a JSON file path."""
    key = os.path.abspath(os.fspath(path))
    lock = _locks.get(key)
    if lock is None:
        with _locks_guard:
            lock = _locks.get(key)
            if lock is None:
                lock = threading.RLock()
                _locks[key] = lock
    return lock


def read_json(path: str | Path, default: T | Callable[[], T]) -> Any:
    """Read JSON, quarantining corrupt files and returning ``default``."""
    p = Path(path)
    with json_file_lock(p):
        if not p.exists():
            return _default_value(default)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            quarantine_path = quarantine_corrupt_json(p)
            logger.warning("Quarantined corrupt JSON store %s -> %s: %s", p, quarantine_path, exc)
            return _default_value(default)


def write_json_atomic(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    separators: tuple[str, str] | None = None,
) -> None:
    """Write JSON via a temp file in the same directory, then ``os.replace``."""
    p = Path(path)
    with json_file_lock(p):
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=indent, sort_keys=sort_keys, separators=separators)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
            _fsync_dir(p.parent)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise


def update_json(
    path: str | Path,
    default: T | Callable[[], T],
    updater: Callable[[Any], Any],
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    separators: tuple[str, str] | None = None,
) -> Any:
    """Read, mutate, and atomically write a JSON document under one file lock."""
    p = Path(path)
    with json_file_lock(p):
        data = read_json(p, default)
        updated = updater(data)
        write_json_atomic(p, updated, indent=indent, sort_keys=sort_keys, separators=separators)
        return updated


def quarantine_corrupt_json(path: str | Path) -> Path:
    """Move a corrupt JSON file aside so callers do not silently wipe it."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for _ in range(10):
        candidate = p.with_name(f"{p.name}.corrupt-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        try:
            os.replace(p, candidate)
            return candidate
        except FileNotFoundError:
            return candidate
        except FileExistsError:
            continue
    candidate = p.with_name(f"{p.name}.corrupt-{stamp}-{os.getpid()}-{uuid.uuid4().hex}")
    os.replace(p, candidate)
    return candidate


def _default_value(default: T | Callable[[], T]) -> T:
    if callable(default):
        return default()
    return copy.deepcopy(default)


def _fsync_dir(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

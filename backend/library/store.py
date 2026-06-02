"""Library store — durable per-founder file storage.

Files are stored at:
  $OBSIDIAN_VAULT/library/{founder_id}/
    index.json         — list of file metadata (no content)
    {file_id}.json     — full file record including content

Canonical files (is_canonical=True) are auto-injected into agent system prompts.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ── Paths ──────────────────────────────────────────────────────────────────────

def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _library_dir(founder_id: str) -> Path:
    d = _vault() / "library" / founder_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(founder_id: str) -> Path:
    return _library_dir(founder_id) / "index.json"


def _file_path(founder_id: str, file_id: str) -> Path:
    return _library_dir(founder_id) / f"{file_id}.json"


# ── Index helpers ──────────────────────────────────────────────────────────────

def _load_index(founder_id: str) -> list[dict[str, Any]]:
    p = _index_path(founder_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_index(founder_id: str, index: list[dict[str, Any]]) -> None:
    _index_path(founder_id).write_text(json.dumps(index, indent=2, sort_keys=True))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── CRUD ───────────────────────────────────────────────────────────────────────

def create_file(
    founder_id: str,
    department: str,
    filename: str,
    content: str,
    is_canonical: bool = False,
) -> dict[str, Any]:
    """Create a new library file. Returns the full file record."""
    file_id = uuid.uuid4().hex[:16]
    now = _now()
    size_bytes = len(content.encode("utf-8"))
    record: dict[str, Any] = {
        "id": file_id,
        "founder_id": founder_id,
        "department": department,
        "filename": filename,
        "content": content,
        "is_canonical": is_canonical,
        "created_at": now,
        "updated_at": now,
        "size_bytes": size_bytes,
    }
    meta = {k: v for k, v in record.items() if k != "content"}
    with _lock:
        _file_path(founder_id, file_id).write_text(json.dumps(record, indent=2))
        index = _load_index(founder_id)
        index.append(meta)
        _save_index(founder_id, index)
    logger.info("library.create_file founder=%s file_id=%s filename=%s", founder_id, file_id, filename)
    return record


def get_file(founder_id: str, file_id: str) -> dict[str, Any] | None:
    """Return full file record (including content) or None."""
    p = _file_path(founder_id, file_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_files(founder_id: str, department: str | None = None) -> list[dict[str, Any]]:
    """Return metadata list (no content) for a founder, optionally filtered by department."""
    with _lock:
        index = _load_index(founder_id)
    if department:
        index = [f for f in index if f.get("department") == department]
    index.sort(key=lambda f: f.get("updated_at", ""), reverse=True)
    return index


def update_file(
    founder_id: str,
    file_id: str,
    *,
    content: str | None = None,
    filename: str | None = None,
    department: str | None = None,
    is_canonical: bool | None = None,
) -> dict[str, Any] | None:
    """Update file fields. Returns updated record or None if not found."""
    p = _file_path(founder_id, file_id)
    if not p.exists():
        return None
    with _lock:
        try:
            record = json.loads(p.read_text())
        except Exception:
            return None
        if content is not None:
            record["content"] = content
            record["size_bytes"] = len(content.encode("utf-8"))
        if filename is not None:
            record["filename"] = filename
        if department is not None:
            record["department"] = department
        if is_canonical is not None:
            record["is_canonical"] = is_canonical
        record["updated_at"] = _now()
        p.write_text(json.dumps(record, indent=2))
        # Update index entry
        index = _load_index(founder_id)
        meta = {k: v for k, v in record.items() if k != "content"}
        new_index = [meta if f["id"] == file_id else f for f in index]
        _save_index(founder_id, new_index)
    return record


def delete_file(founder_id: str, file_id: str) -> bool:
    """Delete a file. Returns True if deleted, False if not found."""
    p = _file_path(founder_id, file_id)
    if not p.exists():
        return False
    with _lock:
        try:
            p.unlink()
        except Exception:
            return False
        index = _load_index(founder_id)
        new_index = [f for f in index if f["id"] != file_id]
        _save_index(founder_id, new_index)
    logger.info("library.delete_file founder=%s file_id=%s", founder_id, file_id)
    return True


def get_canonical_files(founder_id: str) -> list[dict[str, Any]]:
    """Return full content for all canonical files of a founder (max 5)."""
    index = list_files(founder_id)
    canonical_meta = [f for f in index if f.get("is_canonical")]
    results: list[dict[str, Any]] = []
    for meta in canonical_meta[:5]:
        record = get_file(founder_id, meta["id"])
        if record:
            results.append(record)
    return results

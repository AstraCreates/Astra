"""Library store — durable per-founder file storage.

Files are stored at:
  $OBSIDIAN_VAULT/library/{founder_id}/
    index.json         — list of file metadata (no content)
    {file_id}.json     — full file record including content

Canonical files (is_canonical=True) are auto-injected into agent system prompts.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.core.json_store import read_json, write_json_atomic

logger = logging.getLogger(__name__)

_lock = threading.RLock()


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
    data = read_json(_index_path(founder_id), [])
    return data if isinstance(data, list) else []


def _save_index(founder_id: str, index: list[dict[str, Any]]) -> None:
    write_json_atomic(_index_path(founder_id), index, sort_keys=True)


def _load_record(founder_id: str, file_id: str) -> dict[str, Any] | None:
    data = read_json(_file_path(founder_id, file_id), None)
    return data if isinstance(data, dict) else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _meta_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k != "content"}


def _rebuild_index(founder_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in _library_dir(founder_id).glob("*.json"):
        if candidate.name == "index.json":
            continue
        data = read_json(candidate, None)
        if isinstance(data, dict) and data.get("id"):
            records.append(_meta_from_record(data))
    records.sort(key=lambda f: f.get("updated_at", ""), reverse=True)
    return records


# ── CRUD ───────────────────────────────────────────────────────────────────────

def _sync_brain_on_create(founder_id: str, file_id: str, department: str, filename: str, content: str) -> str:
    """Best-effort: mirror a new Library file into the founder's Company Brain.
    Returns the brain record id to store on the file (empty string if sync failed
    or there's no real content to index)."""
    if not content.strip():
        return ""
    try:
        from backend.tools.company_brain import add_company_brain_record
        result = add_company_brain_record(
            founder_id, source="library", title=filename, content=content, kind="document",
            metadata={"library_file_id": file_id, "department": department},
        )
        if result.get("ok"):
            return str(result["record"]["id"])
    except Exception:
        logger.warning("library.create_file brain sync failed founder=%s file_id=%s", founder_id, file_id, exc_info=True)
    return ""


def create_file(
    founder_id: str,
    department: str,
    filename: str,
    content: str,
    is_canonical: bool = False,
    source_path: str = "",
    source_tag: str = "",
    source_session_id: str = "",
) -> dict[str, Any]:
    """Create a new library file. Returns the full file record.

    source_path:       absolute path to a PDF/file on disk (renders as embedded
                       preview in the UI instead of a text editor).
    source_tag:        human label for what generated this (e.g. agent name).
    source_session_id: the run/session ID that produced this file.
    """
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
    if source_path:
        record["source_path"] = source_path
    if source_tag:
        record["source_tag"] = source_tag
    if source_session_id:
        record["source_session_id"] = source_session_id
    brain_record_id = _sync_brain_on_create(founder_id, file_id, department, filename, content)
    if brain_record_id:
        record["brain_record_id"] = brain_record_id
    meta = _meta_from_record(record)
    with _lock:
        write_json_atomic(_file_path(founder_id, file_id), record)
        index = _load_index(founder_id)
        index.append(meta)
        _save_index(founder_id, index)
    logger.info("library.create_file founder=%s file_id=%s filename=%s", founder_id, file_id, filename)
    return record


def get_file(founder_id: str, file_id: str) -> dict[str, Any] | None:
    """Return full file record (including content) or None."""
    return _load_record(founder_id, file_id)


def list_files(founder_id: str, department: str | None = None) -> list[dict[str, Any]]:
    """Return metadata list (no content) for a founder, optionally filtered by department."""
    with _lock:
        rebuilt = _rebuild_index(founder_id)
        index = rebuilt or _load_index(founder_id)
        if rebuilt and rebuilt != index:
            _save_index(founder_id, rebuilt)
            index = rebuilt
    if department:
        index = [f for f in index if f.get("department") == department]
    index.sort(key=lambda f: f.get("updated_at", ""), reverse=True)
    return index


def _sync_brain_on_update(founder_id: str, record: dict[str, Any]) -> str:
    """Best-effort: push updated content into the linked Company Brain record.
    Returns the (possibly new) brain record id to store on the file."""
    content = record.get("content") or ""
    if not content.strip():
        return str(record.get("brain_record_id") or "")
    try:
        from backend.tools.company_brain import add_company_brain_record, revise_company_brain_record
        existing_id = record.get("brain_record_id")
        if existing_id:
            result = revise_company_brain_record(founder_id, record_id=str(existing_id), title=record["filename"], content=content)
        else:
            result = add_company_brain_record(
                founder_id, source="library", title=record["filename"], content=content, kind="document",
                metadata={"library_file_id": record["id"], "department": record.get("department", "")},
            )
        if result.get("ok"):
            return str(result["record"]["id"])
    except Exception:
        logger.warning("library.update_file brain sync failed founder=%s file_id=%s", founder_id, record.get("id"), exc_info=True)
    return str(record.get("brain_record_id") or "")


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
        record = _load_record(founder_id, file_id)
        if record is None:
            return None
        content_changed = content is not None and content != record.get("content")
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
        if content_changed:
            brain_record_id = _sync_brain_on_update(founder_id, record)
            if brain_record_id:
                record["brain_record_id"] = brain_record_id
        write_json_atomic(p, record)
        # Update index entry
        index = _load_index(founder_id)
        meta = _meta_from_record(record)
        new_index = [meta if f["id"] == file_id else f for f in index]
        _save_index(founder_id, new_index)
    return record


def delete_file(founder_id: str, file_id: str) -> bool:
    """Delete a file. Returns True if deleted, False if not found."""
    p = _file_path(founder_id, file_id)
    if not p.exists():
        return False
    with _lock:
        record = _load_record(founder_id, file_id)
        try:
            p.unlink()
        except Exception:
            return False
        index = _load_index(founder_id)
        new_index = [f for f in index if f["id"] != file_id]
        _save_index(founder_id, new_index)
    if record and record.get("brain_record_id"):
        try:
            from backend.tools.company_brain import remove_library_file_from_brain
            remove_library_file_from_brain(founder_id, file_id)
        except Exception:
            logger.warning("library.delete_file brain sync failed founder=%s file_id=%s", founder_id, file_id, exc_info=True)
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

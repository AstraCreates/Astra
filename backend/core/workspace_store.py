"""Persistent workspace and chapter store.

Directory layout under $OBSIDIAN_VAULT/workspaces/:
  index.json                           — all workspaces indexed (fast list)
  {workspace_id}/
    meta.json                          — workspace metadata + chapter_ids list
    vault.json                         — versioned artifacts (latest + history)
    chapters/
      {chapter_id}.json                — chapter metadata (session link, status)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_global_lock = threading.Lock()
_ws_locks: dict[str, threading.Lock] = {}


# ── Paths ───────────────────────────────────────────────────────────────────

def _vault_root() -> Path:
    root = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")) / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ws_dir(workspace_id: str) -> Path:
    return _vault_root() / workspace_id


def _index_path() -> Path:
    return _vault_root() / "index.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ws_lock(workspace_id: str) -> threading.Lock:
    with _global_lock:
        if workspace_id not in _ws_locks:
            _ws_locks[workspace_id] = threading.Lock()
        return _ws_locks[workspace_id]


def _load_index() -> dict:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_index(data: dict) -> None:
    _index_path().write_text(json.dumps(data, indent=2))


def _with_company_id(record: dict) -> dict:
    """Expose the promoted company identifier while keeping workspace compatibility."""
    normalized = dict(record)
    workspace_id = str(normalized.get("workspace_id") or "")
    normalized.setdefault("company_id", workspace_id or str(normalized.get("founder_id") or ""))
    return normalized


# ── Workspace CRUD ──────────────────────────────────────────────────────────

def create_workspace(
    founder_id: str,
    name: str,
    goal: str,
    stack_id: str = "idea_to_revenue",
    company_name: str = "",
) -> dict:
    workspace_id = f"ws_{uuid.uuid4().hex[:16]}"
    now = _now()
    meta = {
        "workspace_id": workspace_id,
        "company_id": workspace_id,
        "founder_id": founder_id,
        "name": name or goal[:60],
        "goal": goal,
        "company_name": company_name or name or "",
        "stack_id": stack_id,
        "status": "active",
        "created_at": now,
        "last_active": now,
        "chapter_ids": [],
    }
    ws = _ws_dir(workspace_id)
    with _ws_lock(workspace_id):
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "chapters").mkdir(exist_ok=True)
        (ws / "meta.json").write_text(json.dumps(meta, indent=2))
        (ws / "vault.json").write_text(json.dumps({}, indent=2))
    with _global_lock:
        idx = _load_index()
        idx[workspace_id] = {
            "workspace_id": workspace_id,
            "company_id": workspace_id,
            "founder_id": founder_id,
            "name": meta["name"],
            "company_name": meta["company_name"],
            "stack_id": stack_id,
            "status": "active",
            "created_at": now,
            "last_active": now,
            "chapter_count": 0,
        }
        _save_index(idx)
    logger.info("Created workspace %s for founder %s", workspace_id, founder_id)
    return meta


def get_workspace(workspace_id: str) -> Optional[dict]:
    p = _ws_dir(workspace_id) / "meta.json"
    if not p.exists():
        return None
    try:
        return _with_company_id(json.loads(p.read_text()))
    except Exception:
        return None


def list_workspaces(founder_id: str) -> list[dict]:
    with _global_lock:
        idx = _load_index()
    items = [_with_company_id(v) for v in idx.values() if v.get("founder_id") == founder_id]
    items.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return items


def find_workspace_by_name(founder_id: str, company_name: str) -> Optional[dict]:
    """Return the most-recently-active non-archived workspace whose name matches."""
    needle = company_name.strip().lower()
    if not needle:
        return None
    for ws in list_workspaces(founder_id):
        if ws.get("status") == "archived":
            continue
        candidate = (ws.get("company_name") or ws.get("name") or "").strip().lower()
        if candidate == needle:
            return ws
    return None


def update_workspace_meta(workspace_id: str, **fields) -> Optional[dict]:
    now = _now()
    with _ws_lock(workspace_id):
        p = _ws_dir(workspace_id) / "meta.json"
        if not p.exists():
            return None
        meta = json.loads(p.read_text())
        meta.update(fields)
        meta["company_id"] = workspace_id
        meta["last_active"] = now
        p.write_text(json.dumps(meta, indent=2))
    with _global_lock:
        idx = _load_index()
        if workspace_id in idx:
            idx[workspace_id]["company_id"] = workspace_id
            for k in fields:
                if k in idx[workspace_id]:
                    idx[workspace_id][k] = fields[k]
            idx[workspace_id]["last_active"] = now
            _save_index(idx)
    return _with_company_id(meta)


def archive_workspace(workspace_id: str) -> Optional[dict]:
    return update_workspace_meta(workspace_id, status="archived", archived_at=_now())


def duplicate_workspace(workspace_id: str, name: str = "") -> Optional[dict]:
    source = get_workspace(workspace_id)
    if not source:
        return None
    duplicate = create_workspace(
        founder_id=str(source.get("founder_id") or ""),
        name=name.strip() or f"{source.get('name') or 'Company'} copy",
        goal=str(source.get("goal") or ""),
        stack_id=str(source.get("stack_id") or "idea_to_revenue"),
        company_name=str(source.get("company_name") or ""),
    )
    return update_workspace_meta(
        duplicate["workspace_id"],
        duplicated_from_company_id=workspace_id,
    )


def export_workspace_zip(workspace_id: str) -> Optional[bytes]:
    company = get_workspace(workspace_id)
    if not company:
        return None

    try:
        from backend.core.session_store import list_sessions
        sessions = list_sessions(
            founder_id=str(company.get("founder_id") or ""),
            company_id=workspace_id,
            limit=10000,
        )
    except Exception:
        sessions = []

    files = {
        "company.json": company,
        "chapters.json": list_chapters(workspace_id),
        "vault.json": get_vault(workspace_id),
        "sessions.json": sessions,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in files.items():
            archive.writestr(filename, json.dumps(payload, indent=2, sort_keys=True))
    return output.getvalue()


# ── Chapter CRUD ────────────────────────────────────────────────────────────

def create_chapter(
    workspace_id: str,
    session_id: str,
    name: str = "",
    phase_scope: Optional[str] = None,
) -> dict:
    chapter_id = f"ch_{uuid.uuid4().hex[:12]}"
    now = _now()
    if not name:
        ws = get_workspace(workspace_id)
        count = len((ws or {}).get("chapter_ids", [])) + 1
        name = f"Chapter {count}"
    chapter = {
        "chapter_id": chapter_id,
        "workspace_id": workspace_id,
        "company_id": workspace_id,
        "session_id": session_id,
        "name": name,
        "phase_scope": phase_scope,
        "status": "running",
        "artifact_count": 0,
        "created_at": now,
        "completed_at": None,
    }
    with _ws_lock(workspace_id):
        ch_path = _ws_dir(workspace_id) / "chapters" / f"{chapter_id}.json"
        ch_path.write_text(json.dumps(chapter, indent=2))
        meta_p = _ws_dir(workspace_id) / "meta.json"
        if meta_p.exists():
            meta = json.loads(meta_p.read_text())
            meta.setdefault("chapter_ids", []).append(chapter_id)
            meta["last_active"] = now
            meta_p.write_text(json.dumps(meta, indent=2))
    with _global_lock:
        idx = _load_index()
        if workspace_id in idx:
            idx[workspace_id]["last_active"] = now
            idx[workspace_id]["chapter_count"] = idx[workspace_id].get("chapter_count", 0) + 1
            _save_index(idx)
    logger.info("Created chapter %s in workspace %s (session %s)", chapter_id, workspace_id, session_id)
    return chapter


def get_chapter(workspace_id: str, chapter_id: str) -> Optional[dict]:
    p = _ws_dir(workspace_id) / "chapters" / f"{chapter_id}.json"
    if not p.exists():
        return None
    try:
        return _with_company_id(json.loads(p.read_text()))
    except Exception:
        return None


def list_chapters(workspace_id: str) -> list[dict]:
    ws = get_workspace(workspace_id)
    if not ws:
        return []
    result = []
    for ch_id in ws.get("chapter_ids", []):
        ch = get_chapter(workspace_id, ch_id)
        if ch:
            result.append(ch)
    return result


def update_chapter(workspace_id: str, chapter_id: str, **fields) -> None:
    with _ws_lock(workspace_id):
        p = _ws_dir(workspace_id) / "chapters" / f"{chapter_id}.json"
        if not p.exists():
            return
        ch = json.loads(p.read_text())
        ch.update(fields)
        if fields.get("status") in ("done", "error", "killed") and not ch.get("completed_at"):
            ch["completed_at"] = _now()
        p.write_text(json.dumps(ch, indent=2))
    if fields.get("company_name"):
        update_workspace_meta(workspace_id, company_name=fields["company_name"])


def find_chapter_by_session(session_id: str) -> Optional[tuple[str, str]]:
    """Return (workspace_id, chapter_id) for the given session_id, or None."""
    root = _vault_root()
    if not root.exists():
        return None
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir():
            continue
        ch_dir = ws_dir / "chapters"
        if not ch_dir.exists():
            continue
        for ch_file in ch_dir.glob("*.json"):
            try:
                ch = json.loads(ch_file.read_text())
                if ch.get("session_id") == session_id:
                    return ch["workspace_id"], ch["chapter_id"]
            except Exception:
                pass
    return None


# ── Workspace Vault (versioned artifacts) ───────────────────────────────────

def upsert_vault_artifact(
    workspace_id: str,
    chapter_id: str,
    session_id: str,
    key: str,
    title: str,
    agent: str,
    preview: str = "",
    content: str = "",
) -> None:
    """Insert or update an artifact in the workspace vault, keeping history."""
    if not key or not workspace_id:
        return
    now = _now()
    with _ws_lock(workspace_id):
        p = _ws_dir(workspace_id) / "vault.json"
        try:
            vault = json.loads(p.read_text()) if p.exists() else {}
        except Exception:
            vault = {}
        entry = vault.get(key, {"key": key, "title": title, "history": []})
        if "current" in entry:
            entry.setdefault("history", []).append(entry["current"])
            if len(entry["history"]) > 20:
                entry["history"] = entry["history"][-20:]
        entry["current"] = {
            "chapter_id": chapter_id,
            "session_id": session_id,
            "agent": agent,
            "title": title,
            "preview": preview,
            "content": content,
            "updated_at": now,
        }
        entry["title"] = title
        vault[key] = entry
        p.write_text(json.dumps(vault, indent=2))
    # Update artifact count on the chapter
    try:
        p2 = _ws_dir(workspace_id) / "chapters" / f"{chapter_id}.json"
        if p2.exists():
            with _ws_lock(workspace_id):
                ch = json.loads(p2.read_text())
                vault_now = json.loads((_ws_dir(workspace_id) / "vault.json").read_text())
                ch["artifact_count"] = sum(1 for v in vault_now.values() if v.get("current", {}).get("chapter_id") == chapter_id)
                p2.write_text(json.dumps(ch, indent=2))
    except Exception:
        pass


def get_vault(workspace_id: str) -> dict:
    p = _ws_dir(workspace_id) / "vault.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

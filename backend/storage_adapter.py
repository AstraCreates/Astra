"""Optional durable storage mirror.

The current app remains local-first, but production deployments need critical
state mirrored out of process. This adapter mirrors documents to Supabase when
configured while preserving the existing `.astra` JSON stores as the fallback.

Expected Supabase table:

    astra_documents(
      collection text,
      key text,
      payload jsonb,
      updated_at timestamptz,
      primary key (collection, key)
    )
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from backend.core.pii_vault import scrub_dict


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:160] or "document"


def _local_root(collection: str) -> Path:
    root = Path(".astra/storage_mirror") / _safe(collection)
    root.mkdir(parents=True, exist_ok=True)
    return root


def mirror_document(collection: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Mirror one document to configured durable storage.

    Returns a status object; write failures are reported but not raised so core
    runtime flows do not fail when the optional storage backend is unavailable.
    """
    from backend.config import settings

    backend = (settings.astra_storage_backend or "local").lower().strip()
    if backend not in {"local", "supabase", "dual"}:
        backend = "local"
    result = {
        "ok": True,
        "collection": collection,
        "key": key,
        "backend": backend,
        "local": None,
        "supabase": None,
    }
    # Explicit SSN exclusion enforced at the data pipeline level
    document = {
        "collection": collection,
        "key": key,
        "payload": scrub_dict(payload),
        "updated_at": _now(),
    }

    if backend in {"local", "dual"}:
        result["local"] = _mirror_local(collection, key, document)
    if backend in {"supabase", "dual"}:
        result["supabase"] = _mirror_supabase(collection, key, document)
    result["ok"] = _result_ok(result)
    return result


def load_document(collection: str, key: str) -> dict[str, Any] | None:
    """Load one mirrored document from the configured source of truth."""
    from backend.config import settings

    backend = (settings.astra_storage_backend or "local").lower().strip()
    if backend == "supabase":
        return _load_supabase(collection, key)
    if backend == "dual":
        return _load_supabase(collection, key) or _load_local(collection, key)
    return _load_local(collection, key)


def list_document_keys(collection: str) -> list[str]:
    """List document keys for a collection from configured durable storage."""
    from backend.config import settings

    backend = (settings.astra_storage_backend or "local").lower().strip()
    keys: list[str] = []
    if backend in {"supabase", "dual"}:
        keys.extend(_list_supabase_keys(collection))
    if backend in {"local", "dual"}:
        keys.extend(_list_local_keys(collection))
    return sorted(dict.fromkeys(keys))


def storage_status() -> dict[str, Any]:
    from backend.config import settings

    backend = (settings.astra_storage_backend or "local").lower().strip()
    configured = bool(settings.supabase_url and settings.supabase_key)
    schema = schema_status() if backend in {"supabase", "dual"} and configured else {"checked": False}
    return {
        "backend": backend,
        "supabase_configured": configured,
        "local_mirror_documents": _local_count(),
        "schema": schema,
        "ok": backend == "local" or (configured and schema.get("ok", False)),
    }


def schema_status() -> dict[str, Any]:
    """Check whether the generic Supabase mirror table is usable."""
    try:
        _supabase_client().table("astra_documents").select("collection").limit(1).execute()
        return {"checked": True, "ok": True, "table": "astra_documents"}
    except Exception as exc:
        return {
            "checked": True,
            "ok": False,
            "table": "astra_documents",
            "error": str(exc),
            "migration": "Apply supabase/schema.sql to create astra_documents.",
        }


def _mirror_local(collection: str, key: str, document: dict[str, Any]) -> dict[str, Any]:
    try:
        path = _local_root(collection) / f"{_safe(key)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document, indent=2, sort_keys=True))
        tmp.replace(path)
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _load_local(collection: str, key: str) -> dict[str, Any] | None:
    path = _local_root(collection) / f"{_safe(key)}.json"
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text())
        return document.get("payload") if isinstance(document, dict) else None
    except Exception:
        return None


def _list_local_keys(collection: str) -> list[str]:
    root = _local_root(collection)
    keys: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            document = json.loads(path.read_text())
            key = document.get("key")
            if key:
                keys.append(str(key))
        except Exception:
            keys.append(path.stem)
    return keys


def _mirror_supabase(collection: str, key: str, document: dict[str, Any]) -> dict[str, Any]:
    try:
        from backend.config import settings
        if not settings.supabase_url or not settings.supabase_key:
            return {"ok": False, "error": "Supabase storage is not configured."}
        _supabase_client().table("astra_documents").upsert(
            document,
            on_conflict="collection,key",
        ).execute()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _load_supabase(collection: str, key: str) -> dict[str, Any] | None:
    try:
        from backend.config import settings
        if not settings.supabase_url or not settings.supabase_key:
            return None
        result = (
            _supabase_client()
            .table("astra_documents")
            .select("payload")
            .eq("collection", collection)
            .eq("key", key)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            return None
        payload = rows[0].get("payload") if isinstance(rows[0], dict) else None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _list_supabase_keys(collection: str) -> list[str]:
    try:
        from backend.config import settings
        if not settings.supabase_url or not settings.supabase_key:
            return []
        result = (
            _supabase_client()
            .table("astra_documents")
            .select("key")
            .eq("collection", collection)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return [str(row.get("key")) for row in rows if isinstance(row, dict) and row.get("key")]
    except Exception:
        return []


def _result_ok(result: dict[str, Any]) -> bool:
    checks = [value for key, value in result.items() if key in {"local", "supabase"} and value is not None]
    return bool(checks) and all(bool(check.get("ok")) for check in checks if isinstance(check, dict))


def _local_count() -> int:
    root = Path(".astra/storage_mirror")
    if not root.exists():
        return 0
    return len(list(root.glob("*/*.json")))


def _supabase_client():
    from backend.db.client import get_supabase
    return get_supabase()

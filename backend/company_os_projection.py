"""Rebuildable local projections for the local-first Company OS.

The Company OS event store is authoritative.  This module deliberately reads
only its materialized records and publishes disposable, content-addressed
filesystem projections that can be recreated at any time.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from backend import company_os
from backend.core.json_store import write_json_atomic

_SCHEMA_VERSION = 1
_ENTITY_COLLECTIONS = (
    "initiatives", "squads", "missions", "tasks", "task_attempts",
    "artifacts", "approvals", "conversation", "context_records", "policy_decisions",
)


def rebuild_company_projections(
    company_id: str,
    *,
    company_root: str | Path | None = None,
    projection_root: str | Path | None = None,
) -> dict[str, Any]:
    """Rebuild every disposable projection for one company from local records.

    The returned manifest is written last, so it acts as the single published
    generation marker after the individual files have been atomically replaced.
    """
    company = company_os.get_company_os(company_id, root=company_root)
    if company is None:
        raise KeyError(f"unknown company: {company_id}")

    target = _projection_root(projection_root) / company_id
    supabase_document = _supabase_document(company)
    graphiti_records = _graphiti_records(company)
    supabase_hash = _content_hash(supabase_document)
    graphiti_hash = _content_hash(graphiti_records)
    graphiti_index = _graphiti_index(graphiti_records)
    graphiti_index_hash = _content_hash(graphiti_index)

    write_json_atomic(target / "supabase.json", supabase_document, sort_keys=True)
    _write_jsonl_atomic(target / "graphiti.jsonl", graphiti_records)
    write_json_atomic(target / "graphiti-index.json", graphiti_index, sort_keys=True)
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "company_id": company_id,
        "source": "company_os_local",
        "source_content_hash": _content_hash(company),
        "projections": {
            "supabase": {"path": "supabase.json", "content_hash": supabase_hash},
            "graphiti": {"path": "graphiti.jsonl", "content_hash": graphiti_hash, "record_count": len(graphiti_records)},
            "graphiti_index": {"path": "graphiti-index.json", "content_hash": graphiti_index_hash},
        },
    }
    write_json_atomic(target / "manifest.json", manifest, sort_keys=True)
    return manifest


def rebuild_all_company_projections(
    *,
    company_root: str | Path | None = None,
    projection_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Rebuild projections for every locally stored Company OS company."""
    companies = company_os.list_company_os(root=company_root)
    return [
        rebuild_company_projections(
            company["company_id"], company_root=company_root, projection_root=projection_root
        )
        for company in sorted(companies, key=lambda item: item["company_id"])
    ]


def projection_content_hash(value: Any) -> str:
    """Return the stable content hash used by projection manifests."""
    return _content_hash(value)


def _supabase_document(company: dict[str, Any]) -> dict[str, Any]:
    """Shape a table-like JSON document without relying on a Supabase client."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "source": "company_os_local",
        "company": {key: company[key] for key in ("company_id", "founder_id", "name", "state", "created_at", "updated_at")},
        "tables": {collection: company.get(collection, []) for collection in _ENTITY_COLLECTIONS},
    }


def _graphiti_records(company: dict[str, Any]) -> list[dict[str, Any]]:
    """Create deterministic graph episodes from Company Brain and work records."""
    records: list[dict[str, Any]] = []
    for collection in _ENTITY_COLLECTIONS:
        for item in company.get(collection, []):
            identifier = _entity_id(collection, item)
            payload = {
                "episode_id": f"{collection}:{identifier}",
                "company_id": company["company_id"],
                "entity_type": collection,
                "entity_id": identifier,
                "text": _episode_text(collection, item),
                "metadata": item,
            }
            payload["content_hash"] = _content_hash(payload)
            records.append(payload)
    return sorted(records, key=lambda item: item["episode_id"])


def _graphiti_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_entity_type: dict[str, list[str]] = {}
    by_scope: dict[str, list[str]] = {}
    for record in records:
        by_entity_type.setdefault(record["entity_type"], []).append(record["episode_id"])
        scope = str(record["metadata"].get("scope") or "company")
        by_scope.setdefault(scope, []).append(record["episode_id"])
    return {"schema_version": _SCHEMA_VERSION, "by_entity_type": by_entity_type, "by_scope": by_scope}


def _entity_id(collection: str, item: dict[str, Any]) -> str:
    for key in ("initiative_id", "squad_id", "mission_id", "task_id", "attempt_id", "artifact_id", "approval_id", "message_id", "context_id"):
        if item.get(key):
            return str(item[key])
    # Policy decisions are append-only events without a dedicated entity ID.
    return _content_hash(item)[:24]


def _episode_text(collection: str, item: dict[str, Any]) -> str:
    if collection == "context_records":
        return f"{item.get('key', 'context')}: {json.dumps(item.get('value'), sort_keys=True, ensure_ascii=True)}"
    if collection == "conversation":
        return str(item.get("message") or "")
    return str(item.get("name") or item.get("title") or json.dumps(item, sort_keys=True, ensure_ascii=True))


def _projection_root(root: str | Path | None) -> Path:
    return Path(root) if root is not None else Path.cwd() / "workspace" / "company-projections"


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    """Publish JSONL through replace, matching the snapshot atomicity contract."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

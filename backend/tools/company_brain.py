"""Company brain store, sync adapters, and agent tools.

The first version is deliberately local-first: it normalizes connected-tool
metadata, prior agent vault notes, and manually added facts into one searchable
graph that agents can query. External source sync is best-effort and can be
expanded per provider without changing the API surface.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Any


SOURCE_CATALOG: dict[str, dict[str, str]] = {
    "discord": {"label": "Discord", "kind": "messages"},
    "slack": {"label": "Slack", "kind": "messages"},
    "github": {"label": "GitHub", "kind": "code"},
    "linear": {"label": "Linear", "kind": "work"},
    "notion": {"label": "Notion", "kind": "docs"},
    "google_drive": {"label": "Google Drive", "kind": "files"},
    "google_workspace": {"label": "Google Workspace", "kind": "docs"},
    "gmail": {"label": "Gmail", "kind": "email"},
    "obsidian": {"label": "Obsidian", "kind": "company_brain"},
    "confluence": {"label": "Confluence", "kind": "docs"},
    "zendesk": {"label": "Zendesk", "kind": "support"},
    "granola": {"label": "Granola", "kind": "meetings"},
}

CONNECTOR_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "github": {
        "credential_fields": ["token"],
        "oauth_apps": ["github"],
        "setup_url": "https://github.com/settings/tokens/new?description=Astra&scopes=repo,read:user",
        "setup_hint": "Save a GitHub personal access token with repo read access, or connect GitHub through Composio.",
        "importer": True,
    },
    "slack": {
        "credential_fields": ["bot_token"],
        "oauth_apps": [],
        "setup_url": "https://api.slack.com/apps",
        "setup_hint": "Save a Slack bot token with conversations:read and channels:read scopes.",
        "importer": True,
    },
    "discord": {
        "credential_fields": ["bot_token"],
        "oauth_apps": [],
        "setup_url": "https://discord.com/developers/applications",
        "setup_hint": "Save a Discord bot token with server/channel read permissions.",
        "importer": True,
    },
    "linear": {
        "credential_fields": ["token"],
        "oauth_apps": ["linear"],
        "setup_url": "https://linear.app/settings/api",
        "setup_hint": "Save a Linear API key, or connect Linear through Composio.",
        "importer": True,
    },
    "notion": {
        "credential_fields": ["token"],
        "oauth_apps": ["notion"],
        "setup_url": "https://www.notion.so/my-integrations",
        "setup_hint": "Save a Notion integration token and share pages with it, or connect Notion through Composio.",
        "importer": True,
    },
    "google_drive": {
        "credential_fields": ["access_token"],
        "oauth_apps": ["googledrive"],
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "setup_hint": "Save a Google OAuth access token with Drive read scope, or connect Google through Composio.",
        "importer": True,
    },
    "google_workspace": {
        "credential_fields": ["access_token"],
        "oauth_apps": ["googledrive"],
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "setup_hint": "Uses the Google Drive importer for Docs, Sheets, and Slides exports.",
        "importer": True,
    },
    "gmail": {
        "credential_fields": ["access_token"],
        "oauth_apps": ["gmail"],
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "setup_hint": "Save a Google OAuth access token with Gmail readonly scope, or connect Gmail through Composio.",
        "importer": True,
    },
    "obsidian": {
        "credential_fields": ["vault_path"],
        "oauth_apps": [],
        "setup_url": "obsidian://open",
        "setup_hint": "Save a local Obsidian vault path. Astra will import Markdown notes that the backend can read.",
        "importer": True,
    },
    "confluence": {
        "credential_fields": ["base_url", "email", "api_token"],
        "oauth_apps": [],
        "setup_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
        "setup_hint": "Save your Confluence base URL, account email, and Atlassian API token.",
        "importer": True,
    },
    "zendesk": {
        "credential_fields": ["subdomain", "email", "token"],
        "oauth_apps": [],
        "setup_url": "https://support.zendesk.com/hc/en-us/articles/4408889192858",
        "setup_hint": "Save Zendesk subdomain, agent email, and API token.",
        "importer": True,
    },
    "granola": {
        "credential_fields": [],
        "oauth_apps": [],
        "setup_url": "https://www.granola.ai/",
        "setup_hint": "Granola is modeled in the graph; direct import is planned.",
        "importer": False,
    },
}

DEFAULT_SOURCES = ["github", "notion", "linear", "gmail", "google_drive", "slack", "discord", "obsidian"]

STOP_WORDS = {
    "that", "with", "from", "this", "have", "will", "into", "your", "their",
    "about", "company", "brain", "context", "using", "agent", "agents",
    "there", "where", "which", "when", "then", "than", "they", "them",
    "what", "were", "been", "also", "only", "onto", "over", "under",
}


def _brain_root() -> Path:
    root = Path(".astra/company_brain")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_id(value: str, fallback: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:120] or fallback


def _brain_path(founder_id: str, company_id: str | None = None) -> Path:
    safe_founder = _safe_id(founder_id, "founder")
    resolved_company_id = company_id or founder_id
    if resolved_company_id == founder_id:
        return _brain_root() / f"{safe_founder}.json"
    company_dir = _brain_root() / safe_founder
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"{_safe_id(resolved_company_id, 'company')}.json"


def _storage_key(founder_id: str, company_id: str | None = None) -> str:
    resolved_company_id = company_id or founder_id
    return founder_id if resolved_company_id == founder_id else f"{founder_id}::{resolved_company_id}"


def list_company_brain_founders() -> list[str]:
    """Return founder ids that have a company-brain store on disk."""
    root = _brain_root()
    founders: list[str] = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
            founders.append(str(data.get("founder_id") or path.stem))
        except Exception:
            founders.append(path.stem)
    try:
        from backend.storage_adapter import list_document_keys
        founders.extend(list_document_keys("company_brains"))
    except Exception:
        pass
    return sorted(dict.fromkeys(founders))


def list_company_brain_instances() -> list[tuple[str, str]]:
    instances: list[tuple[str, str]] = []
    for path in sorted(_brain_root().rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        founder_id = str(data.get("founder_id") or "")
        company_id = str(data.get("company_id") or founder_id)
        if founder_id:
            instances.append((founder_id, company_id))
    return list(dict.fromkeys(instances))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_from_epoch(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _epoch_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def _empty_brain(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    resolved_company_id = company_id or founder_id
    return {
        "founder_id": founder_id,
        "company_id": resolved_company_id,
        "updated_at": _now(),
        "sources": {
            key: {
                "key": key,
                "label": meta["label"],
                "kind": meta["kind"],
                "status": "available",
                "record_count": 0,
                "last_synced_at": None,
                "notes": "",
                **CONNECTOR_REQUIREMENTS.get(key, {}),
            }
            for key, meta in SOURCE_CATALOG.items()
        },
        "records": [],
        "relationships": [],
        "proposals": [],
        "maintenance": {
            "last_checked_at": None,
            "stale_count": 0,
            "contradiction_count": 0,
            "missing_canonical_count": 0,
        },
        "sync": {
            "enabled": False,
            "interval_minutes": 60,
            "sources": DEFAULT_SOURCES,
            "last_run_at": None,
            "next_run_at": None,
            "last_status": "idle",
            "last_error": "",
            "history": [],
        },
        "access_control": {
            "owner_id": founder_id,
            "roles": {
                founder_id: "owner",
            },
            "role_permissions": {
                "owner": ["read", "write", "admin", "approve", "export"],
                "admin": ["read", "write", "approve", "export"],
                "operator": ["read", "write"],
                "viewer": ["read"],
            },
        },
    }


def _load(founder_id: str, company_id: str | None = None) -> dict[str, Any]:
    resolved_company_id = company_id or founder_id
    path = _brain_path(founder_id, resolved_company_id)
    if not path.exists() and resolved_company_id != founder_id:
        legacy_path = _brain_path(founder_id)
        try:
            legacy = json.loads(legacy_path.read_text()) if legacy_path.exists() else None
        except Exception:
            legacy = None
        if isinstance(legacy, dict) and legacy.get("company_id") == resolved_company_id:
            path.write_text(json.dumps(legacy, indent=2, sort_keys=True))
    if not path.exists():
        try:
            from backend.storage_adapter import load_document
            data = load_document(
                "company_brains",
                _storage_key(founder_id, resolved_company_id),
            )
        except Exception:
            data = None
        if not isinstance(data, dict):
            return _empty_brain(founder_id, resolved_company_id)
    else:
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = _empty_brain(founder_id, resolved_company_id)
    data.setdefault("founder_id", founder_id)
    data.setdefault("company_id", resolved_company_id)
    data.setdefault("sources", _empty_brain(founder_id, resolved_company_id)["sources"])
    data.setdefault("records", [])
    data.setdefault("relationships", [])
    data.setdefault("proposals", [])
    data.setdefault("maintenance", {
        "last_checked_at": None,
        "stale_count": 0,
        "contradiction_count": 0,
        "missing_canonical_count": 0,
    })
    data.setdefault("sync", {
        "enabled": False,
        "interval_minutes": 60,
        "sources": DEFAULT_SOURCES,
        "last_run_at": None,
        "next_run_at": None,
        "last_status": "idle",
        "last_error": "",
        "history": [],
    })
    data.setdefault(
        "access_control",
        _empty_brain(founder_id, resolved_company_id)["access_control"],
    )
    for record in data["records"]:
        metadata = record.setdefault("metadata", {})
        metadata.setdefault("company_id", data["company_id"])
        record.setdefault("company_id", metadata["company_id"])
    for key, meta in SOURCE_CATALOG.items():
        data["sources"].setdefault(key, {
            "key": key,
            "label": meta["label"],
            "kind": meta["kind"],
            "status": "available",
            "record_count": 0,
            "last_synced_at": None,
            "notes": "",
        })
        data["sources"][key].update(CONNECTOR_REQUIREMENTS.get(key, {}))
    return data


def _save(
    founder_id: str,
    data: dict[str, Any],
    company_id: str | None = None,
) -> dict[str, Any]:
    resolved_company_id = company_id or str(data.get("company_id") or founder_id)
    data["company_id"] = resolved_company_id
    data["updated_at"] = _now()
    path = _brain_path(founder_id, resolved_company_id)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document(
            "company_brains",
            _storage_key(founder_id, resolved_company_id),
            data,
        )
    except Exception:
        pass
    return data


def _proposal_id(kind: str, record_ids: list[str], title: str) -> str:
    raw = f"{kind}:{':'.join(sorted(record_ids))}:{title}"
    import hashlib
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _record_id(source: str, title: str, content: str) -> str:
    raw = f"{source}:{title}:{content[:600]}"
    import hashlib
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _record(
    *,
    source: str,
    title: str,
    content: str,
    kind: str | None = None,
    url: str = "",
    canonical: bool = False,
    stale_risk: str = "medium",
    metadata: dict[str, Any] | None = None,
    owner_id: str | None = None,
    visibility: str = "team",
    allowed_roles: list[str] | None = None,
    version: int = 1,
    previous_version_id: str | None = None,
) -> dict[str, Any]:
    content = re.sub(r"\s+", " ", content).strip()
    meta = metadata or {}
    status = meta.get("status", "active")
    domain = meta.get("domain") or _infer_domain(title, content)
    return {
        "id": _record_id(source, title, content),
        "version_id": _record_id(source, title, f"{content}:{version}:{previous_version_id or ''}"),
        "version": version,
        "previous_version_id": previous_version_id,
        "company_id": str(meta.get("company_id") or ""),
        "source": source,
        "kind": kind or SOURCE_CATALOG.get(source, {}).get("kind", "note"),
        "title": title.strip()[:180] or "Untitled",
        "url": url,
        "content": content[:8000],
        "canonical": canonical,
        "stale_risk": stale_risk,
        "status": status,
        "domain": domain,
        "supersedes": meta.get("supersedes", []),
        "owner_id": owner_id or meta.get("owner_id") or "",
        "visibility": visibility or meta.get("visibility") or "team",
        "allowed_roles": allowed_roles or meta.get("allowed_roles") or ["owner", "admin", "operator", "viewer"],
        "updated_at": _now(),
        "metadata": meta,
    }


def _upsert_records(data: dict[str, Any], records: list[dict[str, Any]]) -> int:
    existing = {r["id"]: r for r in data.get("records", []) if r.get("id")}
    changed = 0
    for rec in records:
        old = existing.get(rec["id"])
        if old != rec:
            existing[rec["id"]] = rec
            changed += 1
    data["records"] = sorted(existing.values(), key=lambda r: (r.get("source", ""), r.get("title", "")))
    return changed


def _viewer_role(data: dict[str, Any], viewer_id: str | None) -> str:
    access = data.get("access_control") or {}
    roles = access.get("roles") or {}
    if viewer_id and viewer_id in roles:
        return str(roles[viewer_id])
    if viewer_id and viewer_id == access.get("owner_id"):
        return "owner"
    return "owner" if not viewer_id else "viewer"


def _role_permissions(data: dict[str, Any], role: str) -> set[str]:
    access = data.get("access_control") or {}
    permissions = (access.get("role_permissions") or {}).get(role) or []
    return set(permissions)


def _can_read_record(record: dict[str, Any], role: str, viewer_id: str | None = None) -> bool:
    visibility = record.get("visibility") or "team"
    if visibility == "private" and record.get("owner_id") and record.get("owner_id") != viewer_id and role != "owner":
        return False
    allowed = set(record.get("allowed_roles") or ["owner", "admin", "operator", "viewer"])
    return role in allowed or role == "owner"


def _filter_readable_records(data: dict[str, Any], viewer_id: str | None = None) -> list[dict[str, Any]]:
    role = _viewer_role(data, viewer_id)
    if "read" not in _role_permissions(data, role) and role != "owner":
        return []
    return [record for record in data.get("records", []) if _can_read_record(record, role, viewer_id)]


def configure_company_brain_access(
    founder_id: str,
    roles: dict[str, str] | None = None,
    role_permissions: dict[str, list[str]] | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Configure team roles and permission grants for Company Brain access."""
    data = _load(founder_id, company_id)
    access = data.setdefault(
        "access_control",
        _empty_brain(founder_id, company_id)["access_control"],
    )
    access["owner_id"] = access.get("owner_id") or founder_id
    if roles:
        allowed_roles = {"owner", "admin", "operator", "viewer"}
        current = dict(access.get("roles") or {})
        for member_id, role in roles.items():
            if role in allowed_roles:
                current[str(member_id)] = role
        current[founder_id] = "owner"
        access["roles"] = current
    if role_permissions:
        current_permissions = dict(access.get("role_permissions") or {})
        for role, permissions in role_permissions.items():
            current_permissions[str(role)] = sorted(set(str(item) for item in permissions))
        access["role_permissions"] = current_permissions
    data["access_control"] = access
    _save(founder_id, data, company_id)
    return {"ok": True, "access_control": access}


def _keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
    return [w for w, _ in Counter(w for w in words if w not in STOP_WORDS).most_common(limit)]


def _infer_domain(title: str, content: str) -> str:
    text = f"{title} {content}".lower()
    domains = {
        "architecture": ["architecture", "infra", "backend", "frontend", "api", "database", "schema", "deploy", "auth"],
        "product": ["roadmap", "feature", "user", "customer", "pricing", "plan", "launch", "mvp"],
        "go_to_market": ["sales", "marketing", "campaign", "lead", "outreach", "positioning", "competitor"],
        "operations": ["runbook", "sop", "process", "hiring", "meeting", "decision", "owner"],
        "support": ["ticket", "bug", "incident", "customer", "zendesk", "help"],
    }
    scores = {
        domain: sum(text.count(token) for token in tokens)
        for domain, tokens in domains.items()
    }
    best, score = max(scores.items(), key=lambda item: item[1])
    if score > 0:
        return best
    kws = _keywords(text, 1)
    return kws[0] if kws else "general"


def _rebuild_relationships(data: dict[str, Any]) -> None:
    records = data.get("records", [])
    rels: dict[tuple[str, str], dict[str, Any]] = {}
    keyword_map: dict[str, list[str]] = {}
    for rec in records:
        kws = set(_keywords(f"{rec.get('title', '')} {rec.get('content', '')}", 12))
        keyword_map[rec["id"]] = list(kws)
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            if a.get("source") == b.get("source"):
                continue
            overlap = sorted(set(keyword_map.get(a["id"], [])) & set(keyword_map.get(b["id"], [])))
            if not overlap:
                continue
            key = tuple(sorted([a["id"], b["id"]]))
            rels[key] = {
                "from": key[0],
                "to": key[1],
                "type": "shared_context",
                "strength": min(1.0, round(len(overlap) / 5, 2)),
                "evidence": overlap[:5],
            }
    data["relationships"] = list(rels.values())


def get_company_brain_graph(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Return a company-scoped graph without reading the founder-wide GraphRAG index."""
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    records = [
        record
        for record in data.get("records", [])
        if record.get("status", "active") == "active"
    ]
    nodes = [
        {
            "id": str(record.get("id") or ""),
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "name": str(record.get("title") or "Untitled"),
            "type": str(record.get("kind") or record.get("domain") or "record"),
            "description": str(record.get("content") or "")[:500],
            "importance": 3 if record.get("canonical") else 1,
            "community_id": str(record.get("domain") or record.get("source") or "general"),
        }
        for record in records
        if record.get("id")
    ]
    valid_ids = {node["id"] for node in nodes}
    edges = [
        {
            "id": f"{rel.get('from')}:{rel.get('to')}:{index}",
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "source": str(rel.get("from") or ""),
            "target": str(rel.get("to") or ""),
            "relation": str(rel.get("type") or "related"),
            "weight": float(rel.get("strength") or 1),
        }
        for index, rel in enumerate(data.get("relationships", []))
        if rel.get("from") in valid_ids and rel.get("to") in valid_ids
    ]
    return {
        "ok": True,
        "founder_id": founder_id,
        "company_id": resolved_company_id,
        "nodes": nodes,
        "edges": edges,
    }


def rebuild_company_brain_graph(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Recompute the lightweight relationship graph for one company."""
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    _rebuild_relationships(data)
    _save(founder_id, data, resolved_company_id)
    graph = get_company_brain_graph(founder_id, resolved_company_id)
    return {
        "ok": True,
        "founder_id": founder_id,
        "company_id": resolved_company_id,
        "record_count": len(data.get("records", [])),
        "inserted_chunks": 0,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "community_count": len(
            {node.get("community_id") or "general" for node in graph["nodes"]}
        ),
        "snapshot_path": "",
    }


def _extract_conflict_markers(text: str) -> set[str]:
    markers: set[str] = set()
    lower = text.lower()
    patterns = [
        r"\b(next\.?js|react|vite|sveltekit|remix|fastapi|django|express|supabase|postgres|mysql|mongodb|sqlite|clerk|nextauth)\b",
        r"\b(free|freemium|enterprise|team|usage-based|seat-based|subscription)\b",
        r"\b(aws|gcp|azure|vercel|cloudflare|render|fly\.io)\b",
    ]
    for pattern in patterns:
        markers.update(re.findall(pattern, lower))
    return markers


def _record_conflict_scope(record: dict[str, Any]) -> str:
    meta = record.get("metadata") or {}
    for key in ("company_id", "project_id", "product_id", "stack_id", "workspace_id"):
        if meta.get(key):
            return f"{key}:{str(meta[key]).strip().lower()}"
    for key in ("company", "project", "product", "stack_name"):
        if meta.get(key):
            return f"{key}:{str(meta[key]).strip().lower()}"
    title = str(record.get("title") or "")
    match = re.match(r"^(?:Agent Department Manifest|Run Digest) - ([^-]+?)(?: - |$)", title, re.I)
    if match:
        return f"product:{match.group(1).strip().lower()}"
    if meta.get("session_id"):
        return f"session:{str(meta['session_id']).strip().lower()}"
    return ""


def _records_share_conflict_scope(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_scope = _record_conflict_scope(a)
    b_scope = _record_conflict_scope(b)
    if a_scope and b_scope:
        return a_scope == b_scope
    return not a_scope and not b_scope


def _record_conflict_eligible(record: dict[str, Any]) -> bool:
    kind = str(record.get("kind") or "").lower()
    source = str(record.get("source") or "").lower()
    if kind in {"agent_memory", "run_digest"}:
        return False
    if source == "astra_vault":
        return False
    return True


def _record_overlap(a: dict[str, Any], b: dict[str, Any]) -> set[str]:
    a_text = f"{a.get('title', '')} {a.get('content', '')}"
    b_text = f"{b.get('title', '')} {b.get('content', '')}"
    return set(_keywords(a_text, 16)) & set(_keywords(b_text, 16))


def _proposal(kind: str, title: str, records: list[dict[str, Any]], reason: str, suggested_update: str) -> dict[str, Any]:
    ids = [r["id"] for r in records if r.get("id")]
    return {
        "id": _proposal_id(kind, ids, title),
        "kind": kind,
        "title": title,
        "status": "open",
        "record_ids": ids,
        "reason": reason,
        "suggested_update": suggested_update,
        "created_at": _now(),
    }


MAINTENANCE_PROPOSAL_KINDS = {"missing_canonical", "contradiction", "stale_record"}


def _merge_proposals(data: dict[str, Any], proposals: list[dict[str, Any]]) -> None:
    existing = {p.get("id"): p for p in data.get("proposals", []) if p.get("id")}
    emitted_ids = {p["id"] for p in proposals if p.get("id")}
    for proposal in proposals:
        old = existing.get(proposal["id"])
        if old:
            proposal["created_at"] = old.get("created_at") or proposal["created_at"]
            if old.get("status") != "open":
                proposal["status"] = old["status"]
        existing[proposal["id"]] = proposal
    for proposal_id, old in list(existing.items()):
        if old.get("status") != "open":
            continue
        if old.get("kind") not in MAINTENANCE_PROPOSAL_KINDS:
            continue
        if proposal_id in emitted_ids:
            continue
        old["status"] = "dismissed"
        old["updated_at"] = _now()
        old["dismissed_reason"] = "maintenance_scan_obsolete"
    data["proposals"] = sorted(existing.values(), key=lambda p: (p.get("status") != "open", p.get("created_at", "")))


def _refresh_counts(data: dict[str, Any]) -> None:
    counts = Counter(r.get("source", "unknown") for r in data.get("records", []))
    for key, source in data.get("sources", {}).items():
        source["record_count"] = counts.get(key, 0)


def _append_sync_history(data: dict[str, Any], entry: dict[str, Any]) -> None:
    sync = data.setdefault("sync", {})
    history = list(sync.get("history") or [])
    history.insert(0, entry)
    sync["history"] = history[:25]


def _normalize_source_record(source: str, raw: dict[str, Any]) -> dict[str, Any]:
    title = str(
        raw.get("title")
        or raw.get("name")
        or raw.get("subject")
        or raw.get("message")
        or raw.get("id")
        or "Untitled"
    )
    content = str(
        raw.get("content")
        or raw.get("body")
        or raw.get("text")
        or raw.get("description")
        or raw.get("summary")
        or raw.get("message")
        or ""
    )
    url = str(raw.get("url") or raw.get("html_url") or raw.get("permalink") or raw.get("web_url") or "")
    kind = str(raw.get("kind") or SOURCE_CATALOG.get(source, {}).get("kind", "note"))
    canonical = bool(raw.get("canonical", False))
    stale_risk = str(raw.get("stale_risk") or ("low" if canonical else "medium"))
    metadata = dict(raw.get("metadata") or {})
    for key in ("external_id", "author", "owner", "repo", "server", "channel", "thread_ts", "state", "updated_at", "domain", "status", "owner_id", "visibility", "allowed_roles", "version", "previous_version_id"):
        if key in raw and key not in metadata:
            metadata[key] = raw[key]
    if not content:
        content = title
    return _record(
        source=source,
        title=title,
        content=content,
        kind=kind,
        url=url,
        canonical=canonical,
        stale_risk=stale_risk,
        metadata=metadata,
        owner_id=str(raw.get("owner_id") or metadata.get("owner_id") or ""),
        visibility=str(raw.get("visibility") or metadata.get("visibility") or "team"),
        allowed_roles=list(raw.get("allowed_roles") or metadata.get("allowed_roles") or ["owner", "admin", "operator", "viewer"]),
        version=int(raw.get("version") or metadata.get("version") or 1),
        previous_version_id=raw.get("previous_version_id") or metadata.get("previous_version_id"),
    )


def _vault_records(founder_id: str) -> list[dict[str, Any]]:
    try:
        from backend.tools.obsidian_logger import _sessions_root
    except Exception:
        return []
    root = _sessions_root(founder_id)
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for note_file in sorted(root.glob("*/*.md"))[-80:]:
        text = note_file.read_text(errors="replace")
        if not text.strip():
            continue
        title = f"{note_file.parent.name} / {note_file.stem}"
        records.append(_record(
            source="astra_vault",
            kind="agent_memory",
            title=title,
            content=text,
            url=str(note_file),
            canonical=note_file.stem == "index",
            stale_risk="low",
            metadata={"session_id": note_file.parent.name, "agent": note_file.stem},
        ))
    return records


def _source_status(founder_id: str, source: str) -> tuple[str, str]:
    try:
        from backend.provisioning.credentials_store import load_credentials
        direct = load_credentials(founder_id, source)
        if direct:
            return "connected", "Manual credentials saved."
        composio = load_credentials("__platform__", "composio")
        if composio and source in {"github", "gmail", "linear", "notion", "google_drive", "google_workspace"}:
            return "oauth_ready", "Composio configured; connect this account from Integrations."
    except Exception:
        pass
    if source in {"slack", "confluence", "zendesk", "granola"}:
        return "planned", "Connector modeled; OAuth adapter not yet wired."
    return "available", "Ready to connect."


def _connector_records(founder_id: str, sources: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sources:
        meta = SOURCE_CATALOG.get(source)
        if not meta:
            continue
        status, note = _source_status(founder_id, source)
        records.append(_record(
            source=source,
            title=f"{meta['label']} connector",
            content=(
                f"{meta['label']} is part of the company brain source graph. "
                f"Status: {status}. {note} This source contributes {meta['kind']} context "
                "to search, drift checks, and agent prompts once records are synced."
            ),
            kind="connector",
            canonical=True,
            stale_risk="low" if status in {"connected", "oauth_ready"} else "medium",
            metadata={"connector_status": status},
        ))
    return records


def sync_company_brain(
    founder_id: str,
    sources: list[str] | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Sync source metadata plus local Astra vault notes into the company brain."""
    selected = sources or DEFAULT_SOURCES
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    records = _connector_records(founder_id, selected)
    if resolved_company_id == founder_id:
        records += _vault_records(founder_id)
    for record in records:
        metadata = record.setdefault("metadata", {})
        metadata["company_id"] = resolved_company_id
        record["company_id"] = resolved_company_id
    changed = _upsert_records(data, records)
    for source in selected:
        if source in data["sources"]:
            status, note = _source_status(founder_id, source)
            data["sources"][source]["status"] = status
            data["sources"][source]["notes"] = note
            data["sources"][source]["last_synced_at"] = _now()
    if "astra_vault" not in data["sources"]:
        data["sources"]["astra_vault"] = {
            "key": "astra_vault",
            "label": "Astra Vault",
            "kind": "agent_memory",
            "status": "connected",
            "record_count": 0,
            "last_synced_at": _now(),
            "notes": "Prior agent runs and Obsidian notes.",
        }
    maintenance = _run_maintenance(data)
    _merge_proposals(data, maintenance["proposals"])
    _rebuild_relationships(data)
    _refresh_counts(data)
    _save(founder_id, data, resolved_company_id)
    return {
        "ok": True,
        "founder_id": founder_id,
        "company_id": resolved_company_id,
        "changed_records": changed,
        "record_count": len(data["records"]),
        "relationship_count": len(data["relationships"]),
        "proposal_count": len([p for p in data.get("proposals", []) if p.get("status") == "open"]),
        "sources": list(data["sources"].values()),
    }


def configure_company_brain_sync(
    founder_id: str,
    enabled: bool = True,
    sources: list[str] | None = None,
    interval_minutes: int = 60,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Persist continuous-sync settings for the company brain."""
    data = _load(founder_id, company_id)
    interval = max(5, min(int(interval_minutes or 60), 24 * 60))
    selected = sources or data.get("sync", {}).get("sources") or DEFAULT_SOURCES
    next_run = _iso_from_epoch(time.time() + interval * 60) if enabled else None
    data["sync"] = {
        **data.get("sync", {}),
        "enabled": bool(enabled),
        "interval_minutes": interval,
        "sources": selected,
        "next_run_at": next_run,
        "last_status": data.get("sync", {}).get("last_status", "idle"),
        "last_error": data.get("sync", {}).get("last_error", ""),
        "history": data.get("sync", {}).get("history", [])[:25],
    }
    _save(founder_id, data, company_id)
    return {"ok": True, "sync": data["sync"]}


def get_company_brain_sync_status(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Return persisted continuous-sync settings and recent run history."""
    data = _load(founder_id, company_id)
    try:
        from backend.connector_sync_ledger import get_connector_sync_status
        connector_sync = get_connector_sync_status(founder_id)
    except Exception:
        connector_sync = {"founder_id": founder_id, "sources": {}}
    return {"ok": True, "sync": data.get("sync", {}), "connector_sync": connector_sync}


def run_company_brain_sync(
    founder_id: str,
    force: bool = False,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Run provider import + vault sync if due or explicitly forced."""
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    sync = data.get("sync", {})
    now = time.time()
    next_run_epoch = _epoch_from_iso(sync.get("next_run_at"))
    if not force and (not sync.get("enabled") or (next_run_epoch and now < next_run_epoch)):
        return {"ok": True, "skipped": True, "sync": sync}

    sources = sync.get("sources") or DEFAULT_SOURCES
    interval = max(5, min(int(sync.get("interval_minutes") or 60), 24 * 60))
    started_at = _now()
    sync["last_status"] = "running"
    sync["last_error"] = ""
    data["sync"] = sync
    _save(founder_id, data, resolved_company_id)

    try:
        from backend.tools.company_brain_connectors import import_company_brain_sources
        if resolved_company_id == founder_id:
            import_result = import_company_brain_sources(
                founder_id,
                sources,
                limit=20,
            )
        else:
            import_result = import_company_brain_sources(
                founder_id,
                sources,
                limit=20,
                company_id=resolved_company_id,
            )
        metadata_result = sync_company_brain(
            founder_id,
            sources,
            company_id=resolved_company_id,
        )
        data = _load(founder_id, resolved_company_id)
        sync = data.get("sync", {})
        sync["enabled"] = bool(sync.get("enabled", True))
        sync["sources"] = sources
        sync["interval_minutes"] = interval
        sync["last_run_at"] = started_at
        sync["next_run_at"] = _iso_from_epoch(time.time() + interval * 60)
        sync["last_status"] = "ok" if import_result.get("ok") or metadata_result.get("ok") else "partial"
        sync["last_error"] = ""
        _append_sync_history(data, {
            "started_at": started_at,
            "finished_at": _now(),
            "status": sync["last_status"],
            "sources": sources,
            "imported_sources": import_result.get("imported_sources", []),
            "failed_sources": import_result.get("failed_sources", []),
            "record_count": metadata_result.get("record_count", len(data.get("records", []))),
            "proposal_count": metadata_result.get("proposal_count", 0),
        })
        data["sync"] = sync
        _save(founder_id, data, resolved_company_id)
        return {"ok": True, "skipped": False, "sync": sync, "import": import_result, "metadata": metadata_result}
    except Exception as exc:
        data = _load(founder_id, resolved_company_id)
        sync = data.get("sync", {})
        sync["last_run_at"] = started_at
        sync["next_run_at"] = _iso_from_epoch(time.time() + interval * 60)
        sync["last_status"] = "error"
        sync["last_error"] = str(exc)
        _append_sync_history(data, {
            "started_at": started_at,
            "finished_at": _now(),
            "status": "error",
            "sources": sources,
            "error": str(exc),
        })
        data["sync"] = sync
        _save(founder_id, data, resolved_company_id)
        return {"ok": False, "skipped": False, "sync": sync, "error": str(exc)}


def run_due_company_brain_syncs(limit: int = 25) -> dict[str, Any]:
    """Run due continuous-sync jobs for all local company brains."""
    results: list[dict[str, Any]] = []
    instances = list_company_brain_instances()[: max(1, limit)]
    for founder_id, company_id in instances:
        data = _load(founder_id, company_id)
        sync = data.get("sync", {})
        if not sync.get("enabled"):
            continue
        next_run = _epoch_from_iso(sync.get("next_run_at"))
        if next_run is not None and time.time() < next_run:
            continue
        results.append(run_company_brain_sync(founder_id, force=True, company_id=company_id))
    return {
        "ok": True,
        "checked_founders": len({founder_id for founder_id, _ in instances}),
        "checked_companies": len(instances),
        "ran": len(results),
        "results": results,
    }


def ingest_company_brain_records(
    founder_id: str,
    source: str,
    records: list[dict[str, Any]],
    company_id: str | None = None,
) -> dict[str, Any]:
    """Bulk-ingest normalized records from a connector, webhook, or importer."""
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    normalized = [_normalize_source_record(source, raw) for raw in records]
    for record in normalized:
        metadata = record.setdefault("metadata", {})
        metadata["company_id"] = resolved_company_id
        record["company_id"] = metadata["company_id"]
    changed = _upsert_records(data, normalized)
    if source not in data["sources"]:
        data["sources"][source] = {
            "key": source,
            "label": source.replace("_", " ").title(),
            "kind": SOURCE_CATALOG.get(source, {}).get("kind", "records"),
            "status": "connected",
            "record_count": 0,
            "last_synced_at": _now(),
            "notes": "Ingested via company brain API.",
        }
    data["sources"][source]["status"] = "connected"
    data["sources"][source]["last_synced_at"] = _now()
    data["sources"][source]["notes"] = "Records ingested via company brain API."
    maintenance = _run_maintenance(data)
    _merge_proposals(data, maintenance["proposals"])
    _rebuild_relationships(data)
    _refresh_counts(data)
    _save(founder_id, data, resolved_company_id)
    return {
        "ok": True,
        "source": source,
        "ingested": len(normalized),
        "changed_records": changed,
        "record_count": len(data["records"]),
        "proposal_count": len([p for p in data.get("proposals", []) if p.get("status") == "open"]),
    }


def add_company_brain_record(
    founder_id: str,
    source: str,
    title: str,
    content: str,
    kind: str = "note",
    url: str = "",
    canonical: bool = False,
    stale_risk: str = "medium",
    owner_id: str | None = None,
    visibility: str = "team",
    allowed_roles: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Add a normalized manual/source record to the company brain."""
    resolved_company_id = company_id or str((metadata or {}).get("company_id") or founder_id)
    data = _load(founder_id, resolved_company_id)
    meta = {
        "manual": True,
        "owner_id": owner_id or founder_id,
        "company_id": resolved_company_id,
        **(metadata or {}),
    }
    rec = _record(
        source=source,
        title=title,
        content=content,
        kind=kind,
        url=url,
        canonical=canonical,
        stale_risk=stale_risk,
        metadata=meta,
        owner_id=owner_id or founder_id,
        visibility=visibility,
        allowed_roles=allowed_roles,
    )
    _upsert_records(data, [rec])
    if source not in data["sources"]:
        data["sources"][source] = {
            "key": source,
            "label": source.replace("_", " ").title(),
            "kind": kind,
            "status": "connected",
            "record_count": 0,
            "last_synced_at": _now(),
            "notes": "Manually added source.",
        }
    maintenance = _run_maintenance(data)
    _merge_proposals(data, maintenance["proposals"])
    _rebuild_relationships(data)
    _refresh_counts(data)
    _save(founder_id, data, resolved_company_id)
    return {"ok": True, "record": rec}


def revise_company_brain_record(
    founder_id: str,
    record_id: str,
    title: str | None = None,
    content: str | None = None,
    canonical: bool | None = None,
    stale_risk: str | None = None,
    editor_id: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Create a new version of a brain record and deprecate the prior version."""
    data = _load(founder_id, company_id)
    role = _viewer_role(data, editor_id or founder_id)
    if role != "owner" and "write" not in _role_permissions(data, role):
        return {"ok": False, "error": "Editor does not have write permission."}

    old = next((record for record in data.get("records", []) if record.get("id") == record_id or record.get("version_id") == record_id), None)
    if not old:
        return {"ok": False, "error": f"Unknown record {record_id}"}

    previous_version = old.get("version_id") or old.get("id")
    old["status"] = "deprecated"
    old.setdefault("metadata", {})["deprecated_by"] = editor_id or founder_id
    old.setdefault("metadata", {})["deprecated_at"] = _now()
    new_version = int(old.get("version") or 1) + 1
    rec = _record(
        source=old.get("source", "manual"),
        title=title if title is not None else old.get("title", ""),
        content=content if content is not None else old.get("content", ""),
        kind=old.get("kind") or "note",
        url=old.get("url") or "",
        canonical=old.get("canonical") if canonical is None else canonical,
        stale_risk=stale_risk or old.get("stale_risk") or "medium",
        metadata={
            **(old.get("metadata") or {}),
            "revised_by": editor_id or founder_id,
            "previous_record_id": old.get("id"),
            "supersedes": [previous_version],
        },
        owner_id=old.get("owner_id") or founder_id,
        visibility=old.get("visibility") or "team",
        allowed_roles=list(old.get("allowed_roles") or ["owner", "admin", "operator", "viewer"]),
        version=new_version,
        previous_version_id=previous_version,
    )
    rec["supersedes"] = list(dict.fromkeys([*(old.get("supersedes") or []), previous_version]))
    _upsert_records(data, [rec])
    maintenance = _run_maintenance(data)
    _merge_proposals(data, maintenance["proposals"])
    _rebuild_relationships(data)
    _refresh_counts(data)
    _save(founder_id, data, company_id)
    return {"ok": True, "record": rec, "previous_record": old}


def get_company_brain(
    founder_id: str,
    viewer_id: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Return the full normalized company brain graph."""
    data = _load(founder_id, company_id)
    _refresh_counts(data)
    data = {**data, "records": _filter_readable_records(data, viewer_id)}
    return data


def _run_maintenance(data: dict[str, Any]) -> dict[str, Any]:
    records = [r for r in data.get("records", []) if r.get("status", "active") == "active"]
    proposals: list[dict[str, Any]] = []
    stale_count = 0
    contradiction_count = 0
    missing_canonical_count = 0

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_domain.setdefault(rec.get("domain") or "general", []).append(rec)

    for domain, domain_records in by_domain.items():
        canonical = [r for r in domain_records if r.get("canonical")]
        noncanonical = [r for r in domain_records if not r.get("canonical")]
        if len(domain_records) >= 3 and not canonical:
            missing_canonical_count += 1
            proposals.append(_proposal(
                "missing_canonical",
                f"Choose a canonical {domain} source",
                domain_records[:5],
                f"{len(domain_records)} active records discuss {domain}, but none is marked canonical.",
                "Pick or create one authoritative record so agents know which source wins during conflicts.",
            ))

        for canon in canonical:
            for rec in noncanonical:
                if not (_record_conflict_eligible(canon) and _record_conflict_eligible(rec)):
                    continue
                if not _records_share_conflict_scope(canon, rec):
                    continue
                overlap = _record_overlap(canon, rec)
                if len(overlap) < 2:
                    continue
                canon_markers = _extract_conflict_markers(canon.get("content", ""))
                rec_markers = _extract_conflict_markers(rec.get("content", ""))
                if canon_markers and rec_markers and canon_markers != rec_markers:
                    contradiction_count += 1
                    proposals.append(_proposal(
                        "contradiction",
                        f"Resolve {domain} conflict: {canon.get('title')} vs {rec.get('title')}",
                        [canon, rec],
                        f"Both records overlap on {', '.join(sorted(overlap)[:5])}, but mention different implementation or business choices.",
                        f"Review {rec.get('title')} against canonical source {canon.get('title')} and update or deprecate the stale record.",
                    ))
                elif rec.get("stale_risk") == "high":
                    stale_count += 1
                    proposals.append(_proposal(
                        "stale_record",
                        f"Refresh stale {domain} record: {rec.get('title')}",
                        [canon, rec],
                        f"{rec.get('title')} is marked high drift risk and overlaps canonical source {canon.get('title')}.",
                        "Regenerate this artifact from the canonical source or mark it deprecated.",
                    ))

    data["maintenance"] = {
        "last_checked_at": _now(),
        "stale_count": stale_count,
        "contradiction_count": contradiction_count,
        "missing_canonical_count": missing_canonical_count,
    }
    return {"ok": True, "maintenance": data["maintenance"], "proposals": proposals}


def maintain_company_brain(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Detect stale records, canonical gaps, and cross-source contradictions."""
    data = _load(founder_id, company_id)
    result = _run_maintenance(data)
    _merge_proposals(data, result["proposals"])
    _rebuild_relationships(data)
    _refresh_counts(data)
    _save(founder_id, data, company_id)
    return {
        "ok": True,
        "maintenance": data["maintenance"],
        "proposals": [p for p in data.get("proposals", []) if p.get("status") == "open"],
    }


def resolve_company_brain_proposal(
    founder_id: str,
    proposal_id: str,
    status: str = "resolved",
    company_id: str | None = None,
) -> dict[str, Any]:
    """Mark a maintenance proposal resolved, dismissed, or open."""
    data = _load(founder_id, company_id)
    allowed = {"open", "resolved", "dismissed"}
    next_status = status if status in allowed else "resolved"
    for proposal in data.get("proposals", []):
        if proposal.get("id") == proposal_id:
            proposal["status"] = next_status
            proposal["updated_at"] = _now()
            _save(founder_id, data, company_id)
            return {"ok": True, "proposal": proposal}
    return {"ok": False, "error": f"Unknown proposal {proposal_id}"}


def search_company_brain(
    founder_id: str,
    query: str,
    limit: int = 8,
    viewer_id: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Search the company brain for human and agent context retrieval."""
    try:
        from backend.tools.graph_rag_v2 import graph_exists, graph_rag_search
        if (not company_id or company_id == founder_id) and graph_exists(founder_id):
            graph_result = graph_rag_search(founder_id, query, limit=limit)
            if graph_result.get("ok") and graph_result.get("count", 0) > 0:
                return {**graph_result, "retrieval": "graph_rag_v2"}
    except Exception:
        pass
    data = _load(founder_id, company_id)
    terms = [t for t in re.findall(r"[a-zA-Z0-9_-]+", query.lower()) if len(t) > 2]
    scored: list[tuple[float, dict[str, Any]]] = []
    for rec in _filter_readable_records(data, viewer_id):
        if rec.get("status") == "deprecated":
            continue
        hay = f"{rec.get('title', '')} {rec.get('content', '')} {rec.get('source', '')}".lower()
        score = sum(hay.count(term) for term in terms)
        if query.lower() in hay:
            score += 4
        if rec.get("canonical"):
            score += 0.5
        if score > 0:
            scored.append((float(score), rec))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, rec in scored[: max(1, min(limit, 20))]:
        content = rec.get("content", "")
        snippet = content[:420]
        results.append({**rec, "score": score, "snippet": snippet})
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "formatted": format_company_brain_context(results),
        "retrieval": "keyword",
    }


def format_company_brain_context(records: list[dict[str, Any]]) -> str:
    if not records:
        return "No company brain records matched."
    lines = ["Company brain context:"]
    for rec in records:
        lines.append(
            f"- [{rec.get('source')}] {rec.get('title')}: "
            f"{rec.get('snippet') or rec.get('content', '')[:360]}"
        )
    return "\n".join(lines)


def company_brain_agent_context(
    founder_id: str,
    query: str,
    limit: int = 8,
    viewer_id: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Return compact graph context for IDEs, MCP bridges, and external agents."""
    resolved_company_id = company_id or founder_id
    data = _load(founder_id, resolved_company_id)
    search = search_company_brain(
        founder_id,
        query,
        limit=limit,
        viewer_id=viewer_id,
        company_id=resolved_company_id,
    )
    if search.get("retrieval") == "graph_rag_v2":
        return {
            "ok": True,
            "founder_id": founder_id,
            "company_id": resolved_company_id,
            "query": query,
            "context": search.get("formatted", ""),
            "records": search.get("results", []),
            "relationships": search.get("relationships", []),
            "canonical_sources": [],
            "open_proposals": [],
            "maintenance": data.get("maintenance", {}),
            "sync": data.get("sync", {}),
            "retrieval": "graph_rag_v2",
        }
    matched_ids = {record["id"] for record in search["results"]}
    readable_records = _filter_readable_records(data, viewer_id)
    relationships = [
        rel for rel in data.get("relationships", [])
        if rel.get("from") in matched_ids or rel.get("to") in matched_ids
    ][:12]
    proposals = [
        p for p in data.get("proposals", [])
        if p.get("status") == "open" and any(rid in matched_ids for rid in p.get("record_ids", []))
    ][:8]
    canonical = [
        {
            "id": rec.get("id"),
            "source": rec.get("source"),
            "title": rec.get("title"),
            "domain": rec.get("domain"),
            "url": rec.get("url"),
            "content": rec.get("content", "")[:700],
        }
        for rec in readable_records
        if rec.get("canonical") and rec.get("status", "active") == "active"
    ][:12]
    return {
        "ok": True,
        "founder_id": founder_id,
        "company_id": resolved_company_id,
        "query": query,
        "context": search["formatted"],
        "records": search["results"],
        "relationships": relationships,
        "canonical_sources": canonical,
        "open_proposals": proposals,
        "maintenance": data.get("maintenance", {}),
        "sync": data.get("sync", {}),
    }


def company_brain_context(
    founder_id: str,
    query: str,
    limit: int = 6,
    viewer_id: str | None = None,
    company_id: str | None = None,
) -> str:
    """Compact helper for orchestrator context injection."""
    try:
        from backend.tools.graph_rag_v2 import read_context_snapshot
        snapshot = read_context_snapshot(founder_id) if not company_id or company_id == founder_id else ""
        if snapshot:
            return snapshot
    except Exception:
        pass
    return search_company_brain(
        founder_id,
        query,
        limit=limit,
        viewer_id=viewer_id,
        company_id=company_id,
    )["formatted"]


def get_company_name(founder_id: str, company_id: str | None = None) -> str:
    """Best-effort canonical company name for a founder, so operating/continuation runs
    use the SAME name the launch run picked instead of inventing a new one. Order:
    the canonical company-identity record's metadata → its title → empty."""
    try:
        data = _load(founder_id, company_id)
        for rec in data.get("records") or []:
            if rec.get("source") == "company_identity" or rec.get("kind") == "identity":
                name = ((rec.get("metadata") or {}).get("company_name") or "").strip()
                if name:
                    return name
                title = str(rec.get("title") or "")
                if ":" in title:
                    return title.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def ask_company_brain(
    founder_id: str,
    question: str,
    limit: int = 8,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Answer a question using company-brain records with explicit citations."""
    query = question.strip()
    if not query:
        return {
            "ok": False,
            "question": question,
            "answer": "Question is empty.",
            "citations": [],
            "confidence": 0.0,
        }
    lower_query = query.lower()
    report_terms = ("what did", "last week", "this week", "subteam", "team do", "worked on", "assigned")
    team_terms = ("engineering", "growth", "sales", "marketing", "product", "support", "ops", "legal")
    if (
        (not company_id or company_id == founder_id)
        and any(term in lower_query for term in report_terms)
        and any(team in lower_query for team in team_terms)
    ):
        from backend.company_reports import build_company_subteam_report, persist_company_subteam_report

        team = next((candidate for candidate in team_terms if candidate in lower_query), "engineering")
        days = 7 if "week" in lower_query else 30
        report = build_company_subteam_report(founder_id, team, days)
        try:
            persist_company_subteam_report(report)
        except Exception:
            pass
        evidence = [
            f"{item.get('title')} ({item.get('source')}): {item.get('snippet')}"
            for item in report.get("highlights", [])[:6]
        ]
        completed = [
            f"completed: {item.get('title')}"
            for item in report.get("completed_work", [])[:3]
        ]
        active = [
            f"{item.get('status')}: {item.get('title')}"
            for item in report.get("active_work", [])[:3]
        ]
        expected = [
            f"next: {item.get('next_action')}"
            for item in report.get("expected_next_work", [])[:3]
            if item.get("next_action")
        ]
        return {
            "ok": True,
            "question": question,
            "answer": " ".join([
                report["summary"],
                *completed,
                *active,
                *expected,
                *report.get("next_actions", [])[:2],
            ]).strip(),
            "confidence": 0.84 if report.get("record_count") else 0.35,
            "citations": [
                {
                    "index": index,
                    "record_id": item.get("id"),
                    "title": item.get("title"),
                    "source": item.get("source"),
                    "url": "",
                    "canonical": bool(item.get("canonical")),
                    "score": 1.0,
                }
                for index, item in enumerate(report.get("highlights", [])[:6], start=1)
            ],
            "evidence": evidence,
            "context": "\n".join(evidence) if evidence else "No matching Company Brain records for this report window.",
            "report": report,
        }
    if (
        (not company_id or company_id == founder_id)
        and any(term in lower_query for term in ("connector", "integration", "connected", "coverage", "sync"))
    ):
        from backend.connector_coverage import build_connector_coverage

        stack_id = "idea_to_revenue"
        if "sales" in lower_query:
            stack_id = "sales"
        elif "marketing" in lower_query:
            stack_id = "marketing"
        elif "support" in lower_query:
            stack_id = "support"
        elif "product" in lower_query:
            stack_id = "product"
        elif "ops" in lower_query:
            stack_id = "founder_ops"
        coverage = build_connector_coverage(founder_id, stack_id)
        return {
            "ok": True,
            "question": question,
            "answer": coverage["summary"] + (" " + " ".join(coverage["next_actions"][:3]) if coverage.get("next_actions") else ""),
            "confidence": 0.82,
            "citations": [],
            "evidence": [
                f"{item['label']}: {item['coverage_status']} ({item['brain_record_count']} brain records)"
                for item in coverage.get("connectors", [])[:8]
            ],
            "context": "\n".join(
                f"- {item['label']}: {item['coverage_status']} ({item['brain_record_count']} brain records)"
                for item in coverage.get("connectors", [])[:8]
            ),
            "connector_coverage": coverage,
        }
    search = search_company_brain(
        founder_id,
        query,
        limit=limit,
        company_id=company_id,
    )
    records = search.get("results", [])

    # ALWAYS put the canonical company-identity record(s) first, fetched directly from the
    # brain — the GraphRAG index can be stale (new records aren't indexed until the next
    # sync), so identity questions ("what is X / what do we sell") would otherwise miss the
    # authoritative record and get answered from off-topic retrieval.
    try:
        _ids = {r.get("id") for r in records}
        identity = [
            r for r in (_load(founder_id, company_id).get("records") or [])
            if (r.get("source") == "company_identity" or r.get("kind") == "identity") and r.get("id") not in _ids
        ]
        records = identity + records
    except Exception:
        pass

    if not records:
        return {
            "ok": True,
            "question": question,
            "answer": "The company brain doesn't have a clear record of that yet.",
            "citations": [],
            "confidence": 0.0,
        }

    top = records[: max(1, min(limit, 8))]
    evidence_lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for idx, rec in enumerate(top, start=1):
        snippet = (rec.get("snippet") or rec.get("content") or "").strip()
        if len(snippet) > 260:
            snippet = snippet[:257] + "..."
        evidence_lines.append(f"[{idx}] {rec.get('title')} ({rec.get('source')}): {snippet}")
        citations.append({
            "index": idx,
            "record_id": rec.get("id"),
            "title": rec.get("title"),
            "source": rec.get("source"),
            "url": rec.get("url"),
            "canonical": bool(rec.get("canonical")),
            "score": rec.get("score", 0.0),
        })

    canonical_hits = sum(1 for c in citations if c["canonical"])
    top_score = float(citations[0].get("score") or 0.0)
    confidence = min(1.0, round((top_score / 6.0) + (canonical_hits / max(1, len(citations))) * 0.25, 2))

    # SYNTHESIZE a real answer from the retrieved evidence (RAG generation). Without this
    # the "answer" was just a template ("Answer based on N matched records") — retrieval
    # with no generation. Cite sources inline as [n] matching the citations list.
    fallback = (
        f"Answer based on {len(top)} matched records. "
        f"Top source: {citations[0]['title']} ({citations[0]['source']})."
    )
    answer = fallback
    try:
        from backend.tools._llm import generate
        evidence_block = "\n".join(evidence_lines)
        prompt = (
            "You answer questions about THIS company strictly from its own brain records.\n\n"
            "HARD RULES:\n"
            "- Use ONLY the EVIDENCE below. Cite each claim inline with [n].\n"
            "- NEVER invent or substitute a plausible-sounding description. If the evidence does "
            "not explicitly state the answer, reply exactly: \"The company brain doesn't have a "
            "clear record of that yet.\" and (optionally) name what IS in the evidence.\n"
            "- Do NOT describe the company from general knowledge or from what AI/agent platforms "
            "typically do — only what these specific records say.\n\n"
            f"QUESTION: {query}\n\nEVIDENCE:\n{evidence_block}\n\nGrounded answer (with [n] citations):"
        )
        out = generate(prompt, max_tokens=700, model="large", temperature=0.15).strip()
        if out:
            answer = out
    except Exception as exc:
        logger.warning("ask_company_brain answer synthesis failed: %s", exc)
    top_title = str(top[0].get("title") or "").strip()
    if top_title and top_title.lower() not in answer.lower():
        answer = f"{top_title}: {answer}"

    return {
        "ok": True,
        "question": question,
        "answer": answer,
        "confidence": confidence,
        "citations": citations,
        "evidence": evidence_lines,
        "context": search.get("formatted", ""),
    }

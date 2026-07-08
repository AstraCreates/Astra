"""Connector setup contracts for stack deployment.

This module turns stack connector requirements into UI/actionable setup cards:
which credentials are needed, whether webhook ingestion is available, what URL
to register, and whether a connector is ready, connected-but-unsynced, or
missing.
"""

from __future__ import annotations

from typing import Any

from backend.connectors.contracts import (
    CONNECTOR_FIELD_SPECS as _CONNECTOR_FIELD_SPECS,
    connector_field_specs,
    normalize_connector_service,
    prepare_connector_credentials_for_save,
)
from backend.config import settings
from backend.connector_coverage import build_connector_coverage
from backend.connector_validation import validate_connector
from backend.provisioning.credentials_store import load_all_credentials, store_credentials
from backend.stacks.readiness import _CONNECTOR_SERVICE_ALIASES
from backend.stacks.templates import get_stack_template

_WEBHOOK_CAPABLE = {"github", "slack", "discord", "notion", "google_drive", "linear", "crm", "helpdesk", "product_tracker"}

_ENV_CREDENTIAL_SOURCES: dict[str, list[tuple[str, str]]] = {
    "github": [("token", "github_token")],
    "vercel": [("token", "vercel_token")],
    "supabase": [("url", "supabase_url"), ("service_role_key", "supabase_key")],
    "clerk": [("secret_key", "clerk_secret_key")],
    "resend": [("api_key", "resend_api_key")],
    "gmail": [("access_token", "composio_api_key")],
    "google_workspace": [("access_token", "composio_api_key")],
    "google_drive": [("access_token", "composio_api_key")],
    "google_sheets": [("access_token", "composio_api_key")],
    "google_docs": [("access_token", "composio_api_key")],
    "google_slides": [("access_token", "composio_api_key")],
    "google_calendar": [("access_token", "composio_api_key")],
    "notion": [("token", "notion_token")],
    "sendgrid": [("api_key", "sendgrid_api_key")],
    "meta_ads": [("access_token", "meta_access_token")],
    "figma": [("token", "figma_token")],
    "obsidian": [("vault_path", "obsidian_vault")],
}


def build_connector_setup_plan(founder_id: str, stack_id: str | None = None) -> dict[str, Any]:
    """Build a setup plan for the connectors needed by a stack."""
    stack = get_stack_template(stack_id)
    coverage = build_connector_coverage(founder_id, stack.stack_id)
    credentials = load_all_credentials(founder_id)
    connectors = [
        _connector_setup_item(founder_id, item, credentials)
        for item in coverage.get("connectors", [])
    ]
    blockers = [
        connector for connector in connectors
        if connector["required"] and connector["setup_status"] not in {"ready", "connected_needs_sync"}
    ]
    sync_needed = [
        connector for connector in connectors
        if connector["setup_status"] == "connected_needs_sync"
    ]
    return {
        "founder_id": founder_id,
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "backend_url": _backend_url(),
        "ready": not blockers,
        "required_total": len([item for item in connectors if item["required"]]),
        "missing_required": len(blockers),
        "connected_needs_sync": len(sync_needed),
        "connectors": connectors,
        "next_actions": _next_actions(blockers, sync_needed, connectors),
        "summary": (
            f"{stack.name} setup: {len(blockers)} required connector(s) missing, "
            f"{len(sync_needed)} connected connector(s) need Company Brain sync."
        ),
    }


def seed_stack_connector_credentials_from_env(
    founder_id: str,
    stack_id: str | None = None,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Seed founder connector credentials from configured environment tokens.

    This is intentionally explicit: production operators can reuse deployment
    tokens as founder-scoped connector credentials without printing or returning
    the secret values.
    """
    stack = get_stack_template(stack_id)
    existing = load_all_credentials(founder_id)
    seeded = []
    skipped = []
    for connector in stack.connector_requirements:
        sources = _ENV_CREDENTIAL_SOURCES.get(connector.key, [])
        if not sources:
            skipped.append(_seed_skip(connector.key, "no_env_mapping"))
            continue
        aliases = _CONNECTOR_SERVICE_ALIASES.get(connector.key, (connector.key,))
        service = next((alias for alias in aliases if isinstance(existing.get(alias), dict) and existing.get(alias)), connector.key)
        if existing.get(service) and not overwrite:
            skipped.append(_seed_skip(connector.key, "already_configured", service=service))
            continue
        creds = {
            field: str(getattr(settings, setting_name, "") or "")
            for field, setting_name in sources
            if getattr(settings, setting_name, "")
        }
        required_fields = [
            field["key"] for field in _CONNECTOR_FIELD_SPECS.get(connector.key, [{"key": "token", "required": True}])
            if field.get("required")
        ]
        missing = [field for field in required_fields if not _field_present(creds, field)]
        if missing:
            skipped.append(_seed_skip(connector.key, "missing_env", service=service, missing_fields=missing))
            continue
        if not dry_run:
            store_credentials(founder_id, service, creds)
        seeded.append({
            "key": connector.key,
            "service": service,
            "required": connector.required,
            "fields": sorted(creds),
            "secret_values_returned": False,
            "dry_run": dry_run,
        })
    return {
        "ok": True,
        "founder_id": founder_id,
        "stack_id": stack.stack_id,
        "seeded_count": len(seeded),
        "skipped_count": len(skipped),
        "dry_run": dry_run,
        "seeded": seeded,
        "skipped": skipped,
        "summary": f"Seeded {len(seeded)} connector credential set(s) from environment for {stack.name}.",
    }


def _connector_setup_item(founder_id: str, coverage_item: dict[str, Any], credentials: dict[str, Any]) -> dict[str, Any]:
    from backend.tools.company_brain import CONNECTOR_REQUIREMENTS

    key = coverage_item["key"]
    aliases = _CONNECTOR_SERVICE_ALIASES.get(key, (key,))
    connected_alias = next((alias for alias in aliases if isinstance(credentials.get(alias), dict) and credentials.get(alias)), None)
    fields = _CONNECTOR_FIELD_SPECS.get(key, [{"key": "token", "label": f"{coverage_item['label']} token", "secret": True, "required": True}])
    saved = credentials.get(connected_alias or key) or {}
    brain_requirement = CONNECTOR_REQUIREMENTS.get(key) or {}
    missing_fields = [
        field["key"] for field in fields
        if field.get("required") and not _field_present(saved, field["key"])
    ]
    webhook_url = f"{_backend_url()}/brain/{founder_id}/webhooks/{key}" if key in _WEBHOOK_CAPABLE else ""
    has_webhook_secret = bool(saved.get("webhook_secret") or saved.get("signing_secret") or saved.get("secret"))
    coverage_status = coverage_item.get("coverage_status", "")
    setup_status = (
        "ready" if coverage_status == "ready" else
        "connected_needs_sync" if coverage_status == "connected_no_memory" else
        "memory_only_needs_credentials" if coverage_status == "memory_only" else
        "missing_credentials" if missing_fields or not coverage_item.get("connected") else
        "optional_missing" if not coverage_item.get("required") else
        "needs_setup"
    )
    return {
        "key": key,
        "label": coverage_item["label"],
        "category": coverage_item["category"],
        "purpose": coverage_item["purpose"],
        "required": bool(coverage_item.get("required")),
        "connected": bool(coverage_item.get("connected")),
        "credential_service": connected_alias or key,
        "credential_aliases": list(aliases),
        "fields": fields,
        "missing_fields": missing_fields,
        "webhook": {
            "supported": key in _WEBHOOK_CAPABLE,
            "url": webhook_url,
            "secret_configured": has_webhook_secret,
            "auth": "hmac_sha256_or_shared_secret" if key in _WEBHOOK_CAPABLE else "none",
        },
        "sync": {
            "brain_covered": bool(coverage_item.get("brain_covered")),
            "brain_record_count": int(coverage_item.get("brain_record_count") or 0),
            "coverage_status": coverage_status,
        },
        "validation": validate_connector(founder_id, key, credentials=credentials, required=bool(coverage_item.get("required")), live=False),
        "setup_status": setup_status,
        "connect_endpoint": "/setup/service",
        "import_endpoint": f"/brain/{founder_id}/import",
        "setup_url": str(brain_requirement.get("setup_url") or ""),
        "setup_hint": str(brain_requirement.get("setup_hint") or ""),
        "importer": bool(brain_requirement.get("importer", False)),
    }


def _field_present(saved: dict[str, Any], key: str) -> bool:
    aliases = {
        "token": ("token", "api_key", "access_token", "bot_token"),
        "api_key": ("api_key", "token", "access_token"),
        "access_token": ("access_token", "token", "api_key"),
        "service_role_key": ("service_role_key", "service_key", "key"),
    }.get(key, (key,))
    return any(bool(saved.get(alias)) for alias in aliases)


def _seed_skip(key: str, reason: str, *, service: str | None = None, missing_fields: list[str] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "service": service or key,
        "reason": reason,
        "missing_fields": missing_fields or [],
        "secret_values_returned": False,
    }


def _next_actions(blockers: list[dict[str, Any]], sync_needed: list[dict[str, Any]], connectors: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in blockers:
        fields = ", ".join(item["missing_fields"]) or "credentials"
        actions.append(f"Connect {item['label']} via {item['connect_endpoint']} with: {fields}.")
    for item in sync_needed:
        actions.append(f"Run Company Brain import for {item['label']} so agents have memory coverage.")
    for item in connectors:
        if item["webhook"]["supported"] and item["connected"] and not item["webhook"]["secret_configured"]:
            actions.append(f"Add a webhook secret for {item['label']} and register {item['webhook']['url']}.")
    return actions[:10]


def _backend_url() -> str:
    return (settings.backend_url or "http://localhost:8000").rstrip("/")

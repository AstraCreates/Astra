"""Connector coverage reports for Agent Stacks and Company Brain."""

from __future__ import annotations

from typing import Any

from backend.stacks.readiness import stack_readiness
from backend.stacks.templates import get_stack_template
from backend.tools.company_brain import get_company_brain


_BRAIN_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "github": ("github",),
    "vercel": ("github", "astra_vault"),
    "supabase": ("astra_vault",),
    "clerk": ("astra_vault",),
    "gmail": ("gmail", "google_workspace"),
    "google_workspace": ("google_workspace", "google_drive"),
    "google_drive": ("google_drive", "google_workspace"),
    "google_sheets": ("google_drive", "google_workspace"),
    "google_docs": ("google_drive", "google_workspace"),
    "google_slides": ("google_drive", "google_workspace"),
    "google_calendar": ("google_workspace", "google_drive"),
    "slack": ("slack",),
    "notion": ("notion",),
    "linear": ("linear",),
    "crm": ("hubspot", "salesforce", "pipedrive", "astra_vault"),
    "linkedin": ("astra_vault",),
    "meta_ads": ("astra_vault",),
    "analytics": ("astra_vault",),
    "website_cms": ("github", "astra_vault"),
    "helpdesk": ("zendesk",),
    "product_tracker": ("linear", "github"),
    "figma": ("astra_vault",),
    "obsidian": ("astra_vault",),
}


def build_connector_coverage(founder_id: str, stack_id: str | None = None) -> dict[str, Any]:
    """Compare stack connector needs against credentials and brain coverage."""
    stack = get_stack_template(stack_id)
    readiness = stack_readiness(founder_id, stack.stack_id)
    brain = get_company_brain(founder_id)
    sources = brain.get("sources", {})
    records = brain.get("records", [])
    source_counts: dict[str, int] = {}
    for record in records:
        source = str(record.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    connectors: list[dict[str, Any]] = []
    for connector in readiness.get("connectors", []):
        aliases = _BRAIN_SOURCE_ALIASES.get(connector["key"], (connector["key"],))
        matched_sources = [
            {
                "key": key,
                "label": (sources.get(key) or {}).get("label", key),
                "status": (sources.get(key) or {}).get("status", "missing"),
                "record_count": int(source_counts.get(key, (sources.get(key) or {}).get("record_count", 0) or 0)),
            }
            for key in aliases
            if key in sources or key in source_counts
        ]
        brain_record_count = sum(item["record_count"] for item in matched_sources)
        brain_covered = brain_record_count > 0 or any(item["status"] in {"connected", "oauth_ready"} for item in matched_sources)
        connectors.append({
            **connector,
            "brain_sources": matched_sources,
            "brain_record_count": brain_record_count,
            "brain_covered": brain_covered,
            "coverage_status": (
                "ready" if connector.get("connected") and brain_covered else
                "connected_no_memory" if connector.get("connected") else
                "missing_required" if connector.get("required") else
                "memory_only" if brain_covered else
                "optional_missing"
            ),
        })

    required = [item for item in connectors if item.get("required")]
    ready_required = [item for item in required if item["coverage_status"] == "ready"]
    missing_required = [item for item in required if item["coverage_status"] == "missing_required"]
    connected_no_memory = [item for item in required if item["coverage_status"] == "connected_no_memory"]

    next_actions: list[str] = []
    for item in missing_required:
        next_actions.append(f"Connect {item['label']} so the {stack.name} can operate.")
    for item in connected_no_memory:
        next_actions.append(f"Sync {item['label']} into Company Brain; credentials exist but memory coverage is thin.")
    optional_missing = [item for item in connectors if item["coverage_status"] == "optional_missing"]
    for item in optional_missing[:3]:
        next_actions.append(f"Optional: connect {item['label']} for better {item['category']} context.")

    return {
        "founder_id": founder_id,
        "stack_id": stack.stack_id,
        "stack_name": stack.name,
        "required_total": len(required),
        "ready_required": len(ready_required),
        "missing_required": len(missing_required),
        "connected_required_without_memory": len(connected_no_memory),
        "coverage_score": 100 if not required else round((len(ready_required) / len(required)) * 100),
        "connectors": connectors,
        "next_actions": next_actions[:8],
        "summary": (
            f"{stack.name} connector coverage: {len(ready_required)}/{len(required)} required connectors "
            "have both connection readiness and Company Brain coverage."
        ),
    }

"""Connector availability checker — request missing connectors at moment of value.

When a tool needs a connector that's missing/expired/degraded, emit SafeRun
approval action instead of failing. User can connect + continue mid-run.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_connector_requirements(tool_name: str) -> list[str]:
    """Return list of connector keys required by a tool.

    Examples: github_deploy → ["github"], sendgrid_email → ["sendgrid"].
    """
    # Tool-to-connector mapping (expand as tools added)
    tool_connectors = {
        "github_deploy": ["github"],
        "github_search": ["github"],
        "deploy_vercel": ["vercel"],
        "fetch_vercel": ["vercel"],
        "sendgrid_email": ["sendgrid"],
        "resend_email": ["resend"],
        "slack_message": ["slack"],
        "linear_create_issue": ["linear"],
        "jira_create_issue": ["jira"],
        "hubspot_create_contact": ["hubspot"],
        "stripe_create_customer": ["stripe"],
        "notion_create_page": ["notion"],
        "google_drive_upload": ["google_drive"],
        "google_sheets_update": ["google_sheets"],
        "calendly_schedule": ["calendly"],
        "shopify_create_product": ["shopify"],
        "zapier_trigger": ["zapier"],
        "make_trigger": ["make"],
        "apollo_search": ["apollo"],
        "hunter_search": ["hunter"],
        "apollo_enrich": ["apollo"],
        "composio_*": ["composio"],  # Catch-all for Composio tools
    }

    # Direct lookup
    if tool_name in tool_connectors:
        return tool_connectors[tool_name]

    # Pattern matching (composio_*)
    for pattern, connectors in tool_connectors.items():
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if tool_name.startswith(prefix):
                return connectors

    return []


def check_connector_availability(
    founder_id: str,
    tool_name: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Check if required connectors are available + valid.

    Returns:
    - {ok: true, missing: [], expired: [], degraded: []} if all available
    - {ok: false, missing: [...], expired: [...], degraded: [...]} if issues
    """
    from backend.connector_validation import validate_connector
    from backend.connector_coverage import build_connector_coverage

    resolved_company = company_id or founder_id
    required = get_connector_requirements(tool_name)

    if not required:
        return {"ok": True, "missing": [], "expired": [], "degraded": []}

    missing = []
    expired = []
    degraded = []

    coverage = build_connector_coverage(founder_id, stack_id=resolved_company) or {}

    for connector_key in required:
        status_info = coverage.get(connector_key, {})
        status = status_info.get("status", "missing")

        if status == "missing":
            missing.append(connector_key)
        elif status == "expired":
            expired.append(connector_key)
        elif status == "degraded":
            degraded.append(connector_key)

        # Also do a live check
        try:
            check_result = validate_connector(
                founder_id, connector_key, live=True
            )
            if not check_result.get("valid"):
                reason = check_result.get("reason", "unknown")
                if "expired" in reason.lower():
                    if connector_key not in expired:
                        expired.append(connector_key)
                else:
                    if connector_key not in degraded:
                        degraded.append(connector_key)
        except Exception:
            pass  # Validation failed, rely on coverage data

    all_good = not missing and not expired and not degraded
    return {
        "ok": all_good,
        "missing": missing,
        "expired": expired,
        "degraded": degraded,
    }


def build_connector_request_action(
    tool_name: str,
    missing: list[str],
    expired: list[str],
    degraded: list[str],
) -> dict[str, Any] | None:
    """Build SafeRun action for missing/expired/degraded connectors.

    Returns action that can be passed to SafeRun approval system.
    """
    issues = []
    for connector in missing:
        issues.append(f"Missing {connector}")
    for connector in expired:
        issues.append(f"Expired {connector}")
    for connector in degraded:
        issues.append(f"Degraded {connector}")

    if not issues:
        return None

    description = f"Tool requires: {', '.join(issues)}. Connect to continue?"

    return {
        "type": "connector_request",
        "tool": tool_name,
        "description": description,
        "missing_connectors": missing,
        "expired_connectors": expired,
        "degraded_connectors": degraded,
    }

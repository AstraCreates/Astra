"""SafeRun action classification.

SafeRun is Astra's trust layer: every potentially risky external action should
have a visible intent, risk level, evidence context, and result.
"""

from __future__ import annotations

import uuid
from typing import Any


_RISKY_TOOLS: dict[str, dict[str, str]] = {
    "vercel_deploy": {
        "risk_level": "high",
        "category": "public_deploy",
        "approval_gate": "public_deploy",
        "reason": "Deploys a public-facing website or preview surface.",
    },
    "vercel_deploy_from_github": {
        "risk_level": "high",
        "category": "public_deploy",
        "approval_gate": "public_deploy",
        "reason": "Deploys a public-facing website from source control.",
    },
    "send_email_campaign": {
        "risk_level": "high",
        "category": "outbound_send",
        "approval_gate": "outbound_send",
        "reason": "Sends outbound email to prospects or customers.",
    },
    "composio_gmail_send": {
        "risk_level": "high",
        "category": "outbound_send",
        "approval_gate": "outbound_send",
        "reason": "Sends email from a connected Gmail account.",
    },
    "resend_send_email": {
        "risk_level": "high",
        "category": "outbound_send",
        "approval_gate": "outbound_send",
        "reason": "Sends email through Resend.",
    },
    "composio_linkedin_post": {
        "risk_level": "high",
        "category": "public_post",
        "approval_gate": "public_deploy",
        "reason": "Publishes public social content.",
    },
    "build_crm_contact": {
        "risk_level": "low",
        "category": "crm_write",
        "approval_gate": "outbound_send",
        "reason": "Creates or prepares a CRM/customer record.",
    },
    "github_create_repo": {
        # Low risk: creates a (private) repo to build in — NOT a public deploy.
        # Audit-only so it never blocks the build waiting on approval.
        "risk_level": "low",
        "category": "code_change",
        "approval_gate": "public_deploy",
        "reason": "Creates a private source-control repo to build in.",
    },
    "composio_github_create_pr": {
        "risk_level": "medium",
        "category": "code_change",
        "approval_gate": "public_deploy",
        "reason": "Creates a pull request in a connected repository.",
    },
    "composio_github_create_issue": {
        "risk_level": "low",
        "category": "project_write",
        "approval_gate": "public_deploy",
        "reason": "Creates a project-management issue.",
    },
    "create_stripe_product": {
        "risk_level": "high",
        "category": "billing",
        "approval_gate": "legal_publish",
        "reason": "Creates billing objects in a connected Stripe account.",
    },
    "create_stripe_price": {
        "risk_level": "high",
        "category": "billing",
        "approval_gate": "legal_publish",
        "reason": "Creates pricing objects in a connected Stripe account.",
    },
    "create_stripe_payment_link": {
        "risk_level": "high",
        "category": "billing",
        "approval_gate": "legal_publish",
        "reason": "Creates a customer-facing payment link.",
    },
    "register_stripe_webhook": {
        "risk_level": "medium",
        "category": "billing_integration",
        "approval_gate": "legal_publish",
        "reason": "Changes Stripe integration behavior.",
    },
    "cloudflare_setup_vercel_domain": {
        "risk_level": "high",
        "category": "dns_change",
        "approval_gate": "public_deploy",
        "reason": "Changes public DNS/domain configuration.",
    },
    "cloudflare_setup_email_dns": {
        "risk_level": "high",
        "category": "dns_change",
        "approval_gate": "outbound_send",
        "reason": "Changes email DNS configuration.",
    },
}


_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_token", "authorization")


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if any(hint in key.lower() for hint in _SECRET_HINTS):
            safe[key] = "[redacted]"
        elif isinstance(value, str):
            safe[key] = value[:220] + ("..." if len(value) > 220 else "")
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)[:220]
    return safe


# Gates that are AUTO-APPROVED in autonomous runs (audit-only, never block). Deploying
# the founder's OWN product to their OWN hosting is low real-risk and is exactly what the
# agent should do without waiting for a human — unlike outbound_send (mass email) or
# legal_publish, which stay gated. Override with ASTRA_SAFERUN_AUTOAPPROVE_GATES (comma list).
def _auto_approved_gates() -> set[str]:
    import os
    raw = os.environ.get("ASTRA_SAFERUN_AUTOAPPROVE_GATES", "public_deploy")
    return {g.strip() for g in raw.split(",") if g.strip()}


def build_saferun_action(tool_name: str, args: dict[str, Any], agent_name: str) -> dict[str, Any] | None:
    spec = _RISKY_TOOLS.get(tool_name)
    if spec is None:
        try:
            from backend.runtime.tool_registry import registry
            entry = registry.get(tool_name)
            if entry and entry.risk_category:
                spec = {
                    "risk_level": "high" if entry.mutability == "external" else "medium",
                    "category": entry.risk_category,
                    "approval_gate": entry.risk_category,
                    "reason": entry.description or f"Executes {entry.risk_category} action.",
                }
        except Exception:
            spec = None
    if not spec:
        return None
    gated = spec["risk_level"] in {"medium", "high"} and spec["approval_gate"] not in _auto_approved_gates()
    return {
        "id": f"sr_{uuid.uuid4().hex[:10]}",
        "tool": tool_name,
        "agent": agent_name,
        "risk_level": spec["risk_level"],
        "category": spec["category"],
        "approval_gate": spec["approval_gate"],
        "approval_required": gated,
        "mode": "approval_required" if gated else "audit_only",
        "reason": spec["reason"],
        "args_preview": _safe_args(args),
        "status": "planned",
    }

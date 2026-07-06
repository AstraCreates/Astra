"""Deployment evidence report for production operators.

This report is intentionally stricter than local readiness. It answers:
"what exact proof is still missing before we can call this production-grade?"
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from backend.readiness.checks import make_check


def build_deploy_evidence(
    *,
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
    live_connectors: bool = False,
    strict: bool = True,
    smoke_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return operator-facing production deploy evidence and missing proof."""
    from backend.billing import billing_config_status
    from backend.config import settings

    checks: list[dict[str, Any]] = []
    backend_url = base_url or settings.backend_url
    frontend_url = settings.frontend_url
    billing = billing_config_status()

    checks.append(_check(
        "production_backend_url",
        _is_public_https_url(backend_url),
        "Backend URL must be a public HTTPS URL, not localhost.",
        {"url": backend_url},
        missing=["BASE_URL or BACKEND_URL=https://..."] if not _is_public_https_url(backend_url) else [],
    ))
    checks.append(_check(
        "production_frontend_url",
        _is_public_https_url(frontend_url),
        "Frontend URL must be a public HTTPS URL, not localhost.",
        {"url": frontend_url},
        missing=["FRONTEND_URL=https://..."] if not _is_public_https_url(frontend_url) else [],
    ))
    checks.append(_check(
        "auth_enforced",
        bool(settings.astra_require_auth and settings.astra_platform_admins and _auth_provider_configured(settings)),
        "Production requires auth enforcement, platform admins, and a JWT/JWKS auth source.",
        {
            "require_auth": bool(settings.astra_require_auth),
            "platform_admins_configured": bool(settings.astra_platform_admins),
            "auth_provider_configured": _auth_provider_configured(settings),
        },
        missing=_missing_auth(settings),
    ))
    checks.append(_check(
        "credential_encryption_key",
        bool(settings.astra_creds_key),
        "Connector credentials must be encrypted with a stable ASTRA_CREDS_KEY.",
        {"configured": bool(settings.astra_creds_key)},
        missing=["ASTRA_CREDS_KEY"] if not settings.astra_creds_key else [],
    ))
    checks.append(_check(
        "stripe_billing_ready",
        bool(billing.get("checkout_available") and billing.get("portal_available") and settings.stripe_webhook_secret),
        "Self-serve billing requires Stripe checkout, portal, prices, and webhook secret.",
        {
            "checkout_available": bool(billing.get("checkout_available")),
            "portal_available": bool(billing.get("portal_available")),
            "missing_price_ids": billing.get("missing_price_ids", []),
            "webhook_secret_configured": bool(settings.stripe_webhook_secret),
        },
        missing=_missing_billing(settings, billing),
    ))
    checks.append(_check(
        "alert_delivery_ready",
        bool(settings.astra_alert_webhook_url),
        "Production alerts need a delivery webhook.",
        {"configured": bool(settings.astra_alert_webhook_url)},
        missing=["ASTRA_ALERT_WEBHOOK_URL"] if not settings.astra_alert_webhook_url else [],
    ))

    if smoke_report is not None:
        smoke_checks = {str(item.get("key")): item for item in smoke_report.get("checks", []) if isinstance(item, dict)}
        http_missing = [
            key.replace("http_", "/")
            for key in ("http_health", "http_ready", "http_metrics")
            if not bool((smoke_checks.get(key) or {}).get("ok"))
        ]
        checks.append(_check(
            "http_surface_verified",
            not http_missing,
            "Current smoke run must verify /health, /ready, and /metrics.",
            {"missing_or_failed": http_missing},
            missing=[f"live HTTP check {path}" for path in http_missing],
        ))
    else:
        checks.append(_check(
            "http_surface_verified",
            False,
            "Run production smoke with --base-url to verify /health, /ready, and /metrics.",
            {"base_url": base_url},
            missing=["strict production smoke with --base-url"],
        ))

    checks.extend(_connector_evidence(founder_id, stack_id, live_connectors))

    failed = [check for check in checks if not check["ok"]]
    missing = [item for check in failed for item in check.get("missing", [])]
    return {
        "ok": not failed if strict else True,
        "strict": strict,
        "founder_id": founder_id,
        "stack_id": stack_id,
        "live_connectors": live_connectors,
        "checks": checks,
        "failed": failed,
        "missing": missing,
        "summary": (
            "Production deploy evidence is complete."
            if not failed
            else f"Production deploy evidence missing {len(missing)} item(s) across {len(failed)} check(s)."
        ),
    }


def _connector_evidence(founder_id: str, stack_id: str, live_connectors: bool) -> list[dict[str, Any]]:
    if not founder_id:
        return [_check(
            "live_connector_evidence",
            False,
            "Production evidence needs a founder workspace to validate required connectors.",
            {"founder_id": founder_id, "stack_id": stack_id},
            missing=["founder_id for connector validation"],
        )]

    from backend.connector_validation import validate_stack_connectors

    validation = validate_stack_connectors(founder_id, stack_id, live=live_connectors)
    required = [item for item in validation.get("connectors", []) if item.get("required")]
    failed_required = [
        {
            "key": item.get("key"),
            "status": item.get("status"),
            "provider_status": (item.get("provider") or {}).get("status"),
            "missing_fields": item.get("missing_fields", []),
        }
        for item in required
        if (item.get("provider") or {}).get("status") != "ok"
    ]
    missing = []
    if not live_connectors:
        missing.append("--live-connectors")
    missing.extend([f"{item['key']} live provider ok" for item in failed_required])
    return [_check(
        "live_connector_evidence",
        bool(live_connectors and required and not failed_required),
        "Every required connector for the selected stack must pass live provider validation.",
        {
            "ready": bool(validation.get("ready")),
            "live": bool(validation.get("live")),
            "required_total": len(required),
            "failed_required": failed_required,
        },
        missing=missing,
    )]


def _is_public_https_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host not in {"localhost", "127.0.0.1", "::1"} and "." in host


def _auth_provider_configured(settings: Any) -> bool:
    return bool(settings.astra_jwt_jwks_url or settings.astra_jwt_secret or settings.astra_trust_auth_headers)


def _missing_auth(settings: Any) -> list[str]:
    missing = []
    if not settings.astra_require_auth:
        missing.append("ASTRA_REQUIRE_AUTH=true")
    if not settings.astra_platform_admins:
        missing.append("ASTRA_PLATFORM_ADMINS")
    if not _auth_provider_configured(settings):
        missing.append("ASTRA_JWT_JWKS_URL or ASTRA_JWT_SECRET")
    return missing


def _missing_billing(settings: Any, billing: dict[str, Any]) -> list[str]:
    missing = []
    if not settings.stripe_secret_key:
        missing.append("STRIPE_SECRET_KEY")
    for plan in billing.get("missing_price_ids", []):
        missing.append(f"STRIPE_PRICE_{str(plan).upper()}")
    if not settings.stripe_webhook_secret:
        missing.append("STRIPE_WEBHOOK_SECRET")
    return missing


def _check(key: str, ok: bool, message: str, details: dict[str, Any], *, missing: list[str] | None = None) -> dict[str, Any]:
    return make_check(key, ok, message, details, missing=missing, include_empty_missing=True)

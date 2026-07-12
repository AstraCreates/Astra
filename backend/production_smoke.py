"""Production smoke verifier for Astra deployments.

This is the operator-facing proof step after deploying: it composes readiness,
template quality, billing config, alerting, durable state, and optional live
connector/provider checks into one pass/fail report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised in lean local test envs
    class _CompatResponse:
        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

    class _RequestsCompat:
        @staticmethod
        def get(url: str, timeout: int = 10) -> _CompatResponse:
            req = urllib_request.Request(url, method="GET")
            try:
                with urllib_request.urlopen(req, timeout=timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    return _CompatResponse(response.getcode(), body)
            except urllib_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                return _CompatResponse(exc.code, body)

    requests = _RequestsCompat()

from backend.readiness.checks import make_check


def run_production_smoke(
    *,
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    live_connectors: bool = False,
    base_url: str = "",
    strict: bool = False,
    save: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    started = time.time()

    from backend.platform_status import platform_status
    status = platform_status()
    checks.append(_check("platform_ready", bool(status.get("ready")), "Platform readiness gate.", {"status": status.get("status")}))
    for key, value in (status.get("checks") or {}).items():
        if key == "runtime":
            continue
        checks.append(_check(f"platform_check_{key}", bool(value.get("ok")), f"{key} subsystem health.", _compact(value)))

    runtime = (status.get("checks") or {}).get("runtime") or {}
    checks.append(_check("runtime_headroom", runtime.get("memory_percent", 100) < 92 and runtime.get("disk_percent", 100) < 92, "Runtime memory/disk are below hard limits.", _compact(runtime)))

    from backend.stack_catalog_proof import build_stack_catalog_proof
    catalog_proof = build_stack_catalog_proof()
    checks.append(_check("stack_catalog_execution_packages", bool(catalog_proof.get("ok")), "All promised stack templates compile into executable AI department packages.", {
        "templates": catalog_proof.get("stack_count", 0),
        "ready": catalog_proof.get("ready_count", 0),
        "failures": [item.get("stack_id") for item in catalog_proof.get("failed", [])],
    }))

    from backend.objective_readiness import build_objective_readiness
    from backend.objective_readiness import build_objective_evidence_matrix
    objective = build_objective_readiness()
    checks.append(_check("agent_stack_objective_readiness", bool(objective.get("ok")), "Agent Stack Platform objective contract is implemented.", _compact(objective)))
    objective_evidence = build_objective_evidence_matrix(founder_id=founder_id, stack_id=stack_id, base_url=base_url)
    checks.append(_check("agent_stack_objective_evidence", bool(objective_evidence.get("code_contract_ready")), "Agent Stack Platform objective requirements map to concrete evidence.", {
        "production_proven": bool(objective_evidence.get("production_proven")),
        "failed_code": [item.get("key") for item in objective_evidence.get("failed_code", [])],
        "live_missing": [item.get("key") for item in objective_evidence.get("live_missing", [])],
    }))

    from backend.billing import billing_config_status
    billing = billing_config_status()
    checks.append(_check("billing_contracts_present", True, "Billing config and session contracts are importable.", _compact(billing)))
    if strict:
        checks.append(_check("billing_self_serve_configured", bool(billing.get("checkout_available") and billing.get("portal_available")), "Strict mode requires Stripe checkout and portal configuration.", _compact(billing)))

    from backend.alerts import list_alerts, run_alert_check
    alert_result = run_alert_check(status, deliver=False)
    alert_state = list_alerts(limit=20)
    checks.append(_check("alerting_operational", alert_result.get("ok") is True, "Alert evaluator and durable ledger are operational.", {
        "generated": alert_result.get("alert_count", 0),
        "open": alert_state.get("open_count", 0),
    }))
    if strict:
        from backend.config import settings
        checks.append(_check("alert_delivery_configured", bool(settings.astra_alert_webhook_url), "Strict mode requires ASTRA_ALERT_WEBHOOK_URL.", {"configured": bool(settings.astra_alert_webhook_url)}))
        checks.append(_check("strict_base_url_provided", bool(base_url), "Strict mode requires a production base URL for live /health, /ready, and /metrics checks.", {"base_url": base_url}))
        checks.append(_check("strict_founder_id_provided", bool(founder_id), "Strict mode requires a founder workspace for live connector validation.", {"founder_id": founder_id}))
        checks.append(_check("strict_live_connectors_requested", bool(live_connectors), "Strict mode requires --live-connectors so provider reachability is verified.", {"live_connectors": live_connectors}))

    if founder_id:
        from backend.connector_validation import validate_stack_connectors
        validation = validate_stack_connectors(founder_id, stack_id, live=live_connectors)
        checks.append(_check("connector_validation", bool(validation.get("ready")), "Stack connector validation for founder workspace.", _compact(validation)))
        if strict:
            required_connectors = [item for item in validation.get("connectors", []) if item.get("required")]
            failed_required = [
                {
                    "key": item.get("key"),
                    "status": item.get("provider", {}).get("status"),
                    "detail": item.get("provider", {}).get("detail"),
                }
                for item in required_connectors
                if item.get("provider", {}).get("status") != "ok"
            ]
            checks.append(_check(
                "connector_live_validation",
                bool(live_connectors) and bool(required_connectors) and not failed_required,
                "Strict mode requires every required connector to pass live provider validation.",
                {
                    "required_total": len(required_connectors),
                    "failed_required": failed_required[:10],
                    "live": bool(validation.get("live")),
                    "ready": bool(validation.get("ready")),
                },
            ))

    if base_url:
        checks.extend(_http_checks(base_url))

    from backend.deploy_evidence import build_deploy_evidence
    deploy_evidence = build_deploy_evidence(
        founder_id=founder_id,
        stack_id=stack_id,
        base_url=base_url,
        live_connectors=live_connectors,
        strict=strict,
        smoke_report={"checks": checks},
    )
    if strict:
        checks.append(_check(
            "deploy_evidence_ready",
            bool(deploy_evidence.get("ok")),
            "Strict mode requires complete production deploy evidence.",
            {
                "summary": deploy_evidence.get("summary"),
                "missing": deploy_evidence.get("missing", [])[:20],
                "failed": [item.get("key") for item in deploy_evidence.get("failed", [])],
            },
        ))

    failed = [check for check in checks if not check["ok"] and (strict or check.get("required", True))]
    result = {
        "ok": not failed,
        "strict": strict,
        "founder_id": founder_id,
        "stack_id": stack_id,
        "live_connectors": live_connectors,
        "base_url": base_url,
        "created_at": _now(),
        "duration_ms": int((time.time() - started) * 1000),
        "failed_count": len(failed),
        "checks": checks,
        "deploy_evidence": deploy_evidence,
        "stack_catalog_proof": catalog_proof,
        "summary": "production smoke passed" if not failed else f"production smoke failed: {len(failed)} check(s)",
    }
    if save:
        result = save_smoke_report(result)
    return result


def save_smoke_report(report: dict[str, Any]) -> dict[str, Any]:
    """Persist a smoke report as deploy evidence."""
    root = _root()
    report_id = str(report.get("id") or _report_id(report))
    payload = {**report, "id": report_id}
    path = root / f"{report_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    latest = root / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("production_smoke", report_id, payload)
    except Exception:
        pass
    return payload


def list_smoke_reports(limit: int = 20) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for path in sorted(_root().glob("*.json"), reverse=True):
        if path.name == "latest.json":
            continue
        try:
            reports.append(json.loads(path.read_text()))
        except Exception:
            continue
    reports.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    latest = reports[0] if reports else None
    bounded = max(1, min(limit, 100))
    return {
        "reports": reports[:bounded],
        "report_count": len(reports),
        "latest": latest,
        "latest_ok": bool(latest.get("ok")) if latest else False,
    }


def _root() -> Path:
    root = Path(".astra/production_smoke")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _report_id(report: dict[str, Any]) -> str:
    base = f"{report.get('created_at') or _now()}-{report.get('stack_id') or 'stack'}-{'ok' if report.get('ok') else 'fail'}"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", base).strip("_")[:160] or "smoke"


def _http_checks(base_url: str) -> list[dict[str, Any]]:
    base = base_url.rstrip("/")
    checks = []
    for path in ("/health", "/ready", "/metrics"):
        url = f"{base}{path}"
        try:
            headers = {"Authorization": f"Bearer {os.environ['ASTRA_METRICS_BEARER_TOKEN']}"} if path == "/metrics" and os.getenv("ASTRA_METRICS_BEARER_TOKEN") else None
            response = requests.get(url, timeout=10, headers=headers) if headers else requests.get(url, timeout=10)
            checks.append(_check(f"http_{path.strip('/')}", 200 <= response.status_code < 300, f"HTTP {path} returns a successful response.", {
                "url": url,
                "status_code": response.status_code,
                "body_preview": response.text[:160],
            }))
        except Exception as exc:
            checks.append(_check(f"http_{path.strip('/')}", False, f"HTTP {path} request failed.", {"url": url, "error": str(exc)}))
    return checks


def _check(key: str, ok: bool, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = make_check(key, ok, message, details or {})
    payload["required"] = True
    return payload


def _compact(value: dict[str, Any], limit: int = 12) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for idx, (key, item) in enumerate(value.items()):
        if idx >= limit:
            out["truncated"] = True
            break
        if isinstance(item, (str, int, float, bool)) or item is None:
            out[key] = item
        elif isinstance(item, list):
            out[key] = item[:5]
        elif isinstance(item, dict):
            out[key] = {k: v for k, v in list(item.items())[:5] if isinstance(v, (str, int, float, bool)) or v is None}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Astra production smoke verification.")
    parser.add_argument("--founder-id", default="")
    parser.add_argument("--stack-id", default="idea_to_revenue")
    parser.add_argument("--live-connectors", action="store_true")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    result = run_production_smoke(
        founder_id=args.founder_id,
        stack_id=args.stack_id,
        live_connectors=args.live_connectors,
        base_url=args.base_url,
        strict=args.strict,
        save=args.save,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

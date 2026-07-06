"""Aggregate production launch readiness for the Agent Stack Platform."""

from __future__ import annotations

import argparse
import json
from typing import Any

from backend.readiness.checks import make_check


def build_launch_readiness(
    *,
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
    report_id: str = "latest",
) -> dict[str, Any]:
    """Return one pass/fail launch audit across setup, objective proof, and archived evidence."""
    from backend.production_requirements import build_production_requirements
    from backend.production_verify import (
        export_production_verification_bundle,
        get_production_verification_report,
        verify_production_verification_manifest,
    )

    requirements = build_production_requirements(
        founder_id=founder_id,
        stack_id=stack_id,
        base_url=base_url,
        require_final_launch_proof=False,
    )
    objective = requirements.get("objective_evidence") or {}
    latest = get_production_verification_report(report_id)
    report = latest.get("report") or {}
    manifest = verify_production_verification_manifest(report_id)
    bundle = export_production_verification_bundle(report_id) if latest.get("found") and manifest.get("found") else {
        "ok": False,
        "found": False,
        "error": "Production verification bundle requires a saved report and checksum manifest.",
    }

    checks = [
        _check("production_requirements", bool(requirements.get("ok")), requirements.get("summary") or "Production requirements configured.", {
            "missing": requirements.get("missing", []),
        }),
        _check("objective_code_contract", bool(objective.get("code_contract_ready")), objective.get("summary") or "Objective evidence matrix is available.", {
            "failed_code": [item.get("key") for item in objective.get("failed_code", [])],
        }),
        _check("objective_production_proof", bool(objective.get("production_proven")), "Objective evidence is backed by a passing live production verification.", {
            "live_missing": [item.get("key") for item in objective.get("live_missing", [])],
            "live_proof": objective.get("live_proof", {}),
        }),
        _check("latest_report_found", bool(latest.get("found")), "A saved production verification report exists.", {
            "report_id": report_id,
        }),
        _check("latest_report_passed", bool(report.get("ok")), report.get("summary") or "Latest production verification report passed.", {
            "report_id": report.get("id") or report_id,
            "created_at": report.get("created_at"),
        }),
        _check("latest_report_live_connectors", bool(report.get("live_connectors")), "Latest production verification used live connector validation.", {
            "live_connectors": bool(report.get("live_connectors")),
        }),
        _check("checksum_manifest_verified", bool(manifest.get("verified")), manifest.get("summary") or "Production evidence checksum manifest verified.", {
            "failed": manifest.get("failed", []),
        }),
        _check("launch_bundle_exported", bool(bundle.get("ok")), bundle.get("summary") or "Launch evidence bundle exported.", {
            "filename": bundle.get("filename"),
            "sha256": bundle.get("sha256"),
            "error": bundle.get("error"),
        }),
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "ok": not failed,
        "founder_id": founder_id,
        "stack_id": requirements.get("stack_id", stack_id),
        "base_url": requirements.get("base_url", base_url),
        "report_id": report.get("id") or report_id,
        "checks": checks,
        "failed": failed,
        "requirements": requirements,
        "latest_report": report if latest.get("found") else None,
        "manifest": manifest,
        "bundle": bundle,
        "summary": (
            "Astra Agent Stack Platform launch readiness is proven."
            if not failed
            else f"Astra launch readiness is not proven: {len(failed)} gate(s) still failing."
        ),
    }


def _check(key: str, ok: bool, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return make_check(key, ok, message, details)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Astra aggregate production launch-readiness audit.")
    parser.add_argument("--founder-id", default="")
    parser.add_argument("--stack-id", default="idea_to_revenue")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--report-id", default="latest")
    args = parser.parse_args()
    audit = build_launch_readiness(
        founder_id=args.founder_id,
        stack_id=args.stack_id,
        base_url=args.base_url,
        report_id=args.report_id,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Objective-level readiness audit for the Agent Stack Platform promise.

Subsystem health is not enough for Astra. This module verifies that the product
contract itself is present: business outcome routing, deployable stack
templates, Company Brain answering, connector ingestion, approvals, business
controls, and production proof surfaces.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.readiness.checks import make_check, registered_check, run_registered_checks


_OBJECTIVE_READINESS_CHECK_ORDER = [
    "promised_stack_catalog",
    "stack_execution_depth",
    "business_outcome_routing",
    "company_brain_execution_layer",
    "connector_ingestion_and_validation",
    "durable_approval_workflows",
    "business_control_plane",
    "production_proof_surface",
]


def build_objective_readiness() -> dict[str, Any]:
    """Return evidence that the current codebase satisfies the platform shape."""
    checks = run_registered_checks(_OBJECTIVE_READINESS_CHECK_ORDER)
    failed = [check for check in checks if not check["ok"]]
    return {
        "ok": not failed,
        "status": "ready" if not failed else "incomplete",
        "checks": checks,
        "failed": failed,
        "summary": (
            "Agent Stack Platform objective readiness passed."
            if not failed
            else f"Agent Stack Platform objective readiness failed: {len(failed)} gap(s)."
        ),
    }


def build_objective_evidence_matrix(
    *,
    founder_id: str = "",
    stack_id: str = "idea_to_revenue",
    base_url: str = "",
    require_final_launch_proof: bool = True,
) -> dict[str, Any]:
    """Map the business objective to concrete code and production evidence."""
    readiness = build_objective_readiness()
    checks = {check["key"]: check for check in readiness.get("checks", [])}
    live_proof = _latest_live_production_proof(require_final_launch_proof=require_final_launch_proof)
    requirements = [
        _requirement(
            key="business_goal_to_ai_department",
            requirement="A user describes an outcome and Astra routes it into the right deployable AI department.",
            evidence=[
                "backend.stacks.compiler.recommend_stack",
                "backend.stacks.templates.PROMISED_AGENT_STACK_IDS",
                "tests/test_agent_stack_business_contract.py",
            ],
            checks=[checks.get("promised_stack_catalog"), checks.get("business_outcome_routing")],
        ),
        _requirement(
            key="idea_to_revenue_stack",
            requirement="A founder starting from zero can deploy an Idea-to-Revenue Stack with company foundation outputs.",
            evidence=[
                "backend.stacks.templates.IDEA_TO_REVENUE_STACK",
                "market, ICP, pricing, landing page, CRM, legal, investor, and 30-day artifacts",
                "tests/test_stack_execution_blueprint.py",
            ],
            checks=[checks.get("promised_stack_catalog"), checks.get("stack_execution_depth")],
        ),
        _requirement(
            key="existing_business_stacks",
            requirement="Existing companies can deploy Sales, Marketing, Founder Ops, Support, and Product stacks.",
            evidence=[
                "backend.stacks.templates.STACK_TEMPLATES",
                "backend.stacks.template_quality.audit_stack_template",
                "tests/test_agent_stack_business_contract.py",
            ],
            checks=[checks.get("promised_stack_catalog"), checks.get("stack_execution_depth")],
        ),
        _requirement(
            key="stack_operating_system",
            requirement="Each stack includes agents, workflows, connectors, dashboards, approval rules, artifacts, and handoff rules.",
            evidence=[
                "backend.stacks.execution_contracts.build_stack_execution_contract",
                "backend.stacks.execution_blueprint.build_stack_execution_blueprint",
                "backend.stacks.artifact_verification.verify_stack_artifacts",
            ],
            checks=[checks.get("stack_execution_depth")],
        ),
        _requirement(
            key="company_brain_execution_layer",
            requirement="Astra remembers company context, answers subteam questions, versions memory, and enforces access roles.",
            evidence=[
                "backend.tools.company_brain",
                "backend.company_reports",
                "backend.connector_coverage",
                "tests/test_company_brain.py",
            ],
            checks=[checks.get("company_brain_execution_layer")],
        ),
        _requirement(
            key="approval_workflows",
            requirement="External or sensitive actions require durable, role-aware approval workflows beyond an MVP toggle.",
            evidence=[
                "backend.approval_workflows",
                "approval request ids, role checks, decisions, expiry",
                "tests/test_approval_workflows.py",
            ],
            checks=[checks.get("durable_approval_workflows")],
        ),
        _requirement(
            key="business_control_plane",
            requirement="Business-facing polish exists for billing, onboarding, team accounts, usage, and admin controls.",
            evidence=[
                "backend.accounts",
                "backend.billing",
                "frontend/components/SettingsPage.tsx",
                "tests/test_billing.py",
                "tests/test_tenant_auth.py",
            ],
            checks=[checks.get("business_control_plane")],
        ),
        _requirement(
            key="connector_ingestion_sync",
            requirement="Slack, Discord, Google Drive, Notion, and Obsidian can be configured, validated, and synced into memory.",
            evidence=[
                "backend.tools.company_brain_connectors.IMPORTERS",
                "backend.connector_validation._LIVE_CHECKS",
                "backend.connector_webhooks",
                "tests/test_connector_validation.py",
                "tests/test_connector_webhooks.py",
            ],
            checks=[checks.get("connector_ingestion_and_validation")],
            needs_live_proof=True,
            live_verified=bool(live_proof.get("ok")),
        ),
        _requirement(
            key="production_hardening",
            requirement="Production hardening covers auth, tests, health/readiness/metrics, alerts, durable evidence, and deployment verification.",
            evidence=[
                "backend.platform_status",
                "backend.alerts",
                "backend.production_smoke",
                "backend.production_verify",
                "docs/Production_Launch_Runbook.md",
            ],
            checks=[checks.get("production_proof_surface")],
            needs_live_proof=True,
            live_verified=bool(live_proof.get("ok")),
        ),
    ]
    failed_code = [item for item in requirements if not item["code_ok"]]
    live_required = [item for item in requirements if item["needs_live_proof"]]
    live_missing = [item for item in live_required if not item["production_verified"]]
    return {
        "ok": not failed_code,
        "code_contract_ready": not failed_code,
        "production_proven": not live_missing and bool(live_required),
        "founder_id": founder_id,
        "stack_id": stack_id,
        "base_url": base_url,
        "require_final_launch_proof": require_final_launch_proof,
        "requirements": requirements,
        "failed_code": failed_code,
        "live_proof": live_proof,
        "live_missing": live_missing,
        "summary": (
            "Agent Stack Platform code contract is ready; live production evidence is verified."
            if not failed_code and not live_missing
            else "Agent Stack Platform code contract is ready; final live production evidence is still required."
            if not failed_code
            else f"Agent Stack Platform code contract has {len(failed_code)} gap(s)."
        ),
    }


@registered_check("promised_stack_catalog")
def _check_promised_stacks() -> dict[str, Any]:
    from backend.stacks.templates import PROMISED_AGENT_STACK_IDS, STACK_TEMPLATES

    promised = set(PROMISED_AGENT_STACK_IDS)
    present = set(STACK_TEMPLATES)
    missing = sorted(promised - present)
    return _check(
        "promised_stack_catalog",
        not missing and len(promised) >= 6,
        "Catalog includes Idea-to-Revenue plus Sales, Marketing, Founder Ops, Support, and Product stacks.",
        {"promised": sorted(promised), "missing": missing, "present_count": len(present)},
    )


@registered_check("stack_execution_depth")
def _check_stack_depth() -> dict[str, Any]:
    from backend.stack_catalog_proof import build_stack_catalog_proof

    proof = build_stack_catalog_proof()
    failures = proof.get("failed", [])
    return _check(
        "stack_execution_depth",
        bool(proof.get("stack_count")) and not failures,
        "Every promised stack compiles into a production-depth AI department package with lanes, artifacts, connectors, approvals, dashboards, and handoff rules.",
        {
            "audited": proof.get("stack_count", 0),
            "ready_count": proof.get("ready_count", 0),
            "min_score": min((int(item.get("quality_score") or 0) for item in proof.get("stacks", [])), default=0),
            "failures": [{"stack_id": item.get("stack_id"), "gaps": item.get("gaps", [])} for item in failures],
        },
    )


@registered_check("business_outcome_routing")
def _check_outcome_routing() -> dict[str, Any]:
    from backend.stacks.compiler import recommend_stack
    from backend.stacks.package import build_goal_stack_package

    examples = {
        "idea_to_revenue": "startup idea waitlist landing page ICP pricing investor plan",
        "sales": "sales pipeline CRM prospects cold email revenue follow up",
        "marketing": "marketing campaign content paid ads social creative measurement",
        "founder_ops": "weekly operating cadence decision log metrics investor update company brain",
        "support": "support tickets helpdesk SLA escalation macros knowledge base",
        "product": "product roadmap user stories requirements technical spec release",
    }
    routed = {
        stack_id: recommend_stack(goal, "idea" if stack_id == "idea_to_revenue" else "existing business").stack.stack_id
        for stack_id, goal in examples.items()
    }
    mismatches = {expected: actual for expected, actual in routed.items() if expected != actual}
    sample_package = build_goal_stack_package(
        instruction=examples["idea_to_revenue"],
        company_stage="idea",
        company_name="Astra Probe",
    )
    package_proof = sample_package.get("proof", {})
    package_ready = all(bool(package_proof.get(key)) for key in (
        "has_manifest",
        "has_execution_blueprint",
        "has_connector_plan",
        "has_approval_policy",
        "has_artifact_contract",
        "has_memory_policy",
        "has_human_collaboration_model",
    ))
    return _check(
        "business_outcome_routing",
        not mismatches and package_ready,
        "Plain business outcomes route to the correct deployable AI department and compile into a launchable stack package.",
        {"routed": routed, "mismatches": mismatches, "sample_package_proof": package_proof},
    )


@registered_check("company_brain_execution_layer")
def _check_company_brain_execution_layer() -> dict[str, Any]:
    from backend.company_reports import build_company_subteam_report, persist_company_subteam_report
    from backend.connector_coverage import build_connector_coverage
    from backend.tools.company_brain import (
        add_company_brain_record,
        ask_company_brain,
        company_brain_agent_context,
        configure_company_brain_access,
        revise_company_brain_record,
        search_company_brain,
    )

    required: dict[str, Callable[..., Any]] = {
        "ask_company_brain": ask_company_brain,
        "company_brain_agent_context": company_brain_agent_context,
        "search_company_brain": search_company_brain,
        "add_company_brain_record": add_company_brain_record,
        "revise_company_brain_record": revise_company_brain_record,
        "configure_company_brain_access": configure_company_brain_access,
        "build_company_subteam_report": build_company_subteam_report,
        "persist_company_subteam_report": persist_company_subteam_report,
        "build_connector_coverage": build_connector_coverage,
    }
    missing = [name for name, fn in required.items() if not callable(fn)]
    report_shape = build_company_subteam_report("__objective_probe__", "engineering", 7)
    report_fields = {"status_counts", "completed_work", "active_work", "blockers", "expected_next_work"}
    missing_report_fields = sorted(report_fields - set(report_shape))
    return _check(
        "company_brain_execution_layer",
        not missing and not missing_report_fields,
        "Company Brain can answer founder questions, produce execution-aware subteam reports, expose agent context, version records, and enforce access roles.",
        {"callables": sorted(required), "missing": missing, "missing_report_fields": missing_report_fields},
    )


@registered_check("connector_ingestion_and_validation")
def _check_connector_ingestion_surface() -> dict[str, Any]:
    from backend.connector_validation import _LIVE_CHECKS
    from backend.tools.company_brain import CONNECTOR_REQUIREMENTS
    from backend.tools.company_brain_connectors import IMPORTERS

    required_sources = {"slack", "discord", "google_drive", "notion", "obsidian"}
    missing_importers = sorted(required_sources - set(IMPORTERS))
    missing_setup = sorted(required_sources - set(CONNECTOR_REQUIREMENTS))
    missing_live_checks = sorted({"slack", "discord", "google_drive", "notion"} - set(_LIVE_CHECKS))
    return _check(
        "connector_ingestion_and_validation",
        not missing_importers and not missing_setup and not missing_live_checks,
        "Core connectors can be configured, live-validated, and ingested/synced into Company Brain.",
        {
            "required_sources": sorted(required_sources),
            "missing_importers": missing_importers,
            "missing_setup": missing_setup,
            "missing_live_checks": missing_live_checks,
        },
    )


@registered_check("durable_approval_workflows")
def _check_approval_workflows() -> dict[str, Any]:
    from backend.approval_workflows import create_approval_request, decide_approval_request, expire_approval_requests, get_approval_workflow

    required = {
        "create_approval_request": create_approval_request,
        "decide_approval_request": decide_approval_request,
        "expire_approval_requests": expire_approval_requests,
        "get_approval_workflow": get_approval_workflow,
    }
    missing = [name for name, fn in required.items() if not callable(fn)]
    return _check(
        "durable_approval_workflows",
        not missing,
        "Approval-gated external actions are durable, inspectable, and role-aware.",
        {"callables": sorted(required), "missing": missing},
    )


@registered_check("business_control_plane")
def _check_business_control_plane() -> dict[str, Any]:
    from backend.accounts import PLANS, get_or_create_org, record_usage, update_admin_controls, upsert_member
    from backend.billing import apply_platform_billing_event, create_checkout_session, create_customer_portal_session

    required_plans = {"beta", "starter", "team", "scale"}
    missing_plans = sorted(required_plans - set(PLANS))
    required_callables = {
        "get_or_create_org": get_or_create_org,
        "upsert_member": upsert_member,
        "update_admin_controls": update_admin_controls,
        "record_usage": record_usage,
        "create_checkout_session": create_checkout_session,
        "create_customer_portal_session": create_customer_portal_session,
        "apply_platform_billing_event": apply_platform_billing_event,
    }
    missing_callables = [name for name, fn in required_callables.items() if not callable(fn)]
    return _check(
        "business_control_plane",
        not missing_plans and not missing_callables,
        "Billing, onboarding/team accounts, usage limits, admin controls, and subscription events have backend contracts.",
        {"missing_plans": missing_plans, "missing_callables": missing_callables},
    )


@registered_check("production_proof_surface")
def _check_production_proof_surface() -> dict[str, Any]:
    from backend.alerts import run_alert_check
    from backend.deploy_evidence import build_deploy_evidence
    from backend.platform_status import platform_status, prometheus_metrics, readiness_status
    from backend.production_requirements import build_production_requirements
    from backend.production_smoke import list_smoke_reports, run_production_smoke, save_smoke_report
    from backend.production_verify import run_production_verification, save_production_verification_report
    from backend.stack_catalog_proof import build_stack_catalog_proof

    required = {
        "build_deploy_evidence": build_deploy_evidence,
        "build_production_requirements": build_production_requirements,
        "build_stack_catalog_proof": build_stack_catalog_proof,
        "platform_status": platform_status,
        "readiness_status": readiness_status,
        "prometheus_metrics": prometheus_metrics,
        "run_alert_check": run_alert_check,
        "run_production_smoke": run_production_smoke,
        "save_smoke_report": save_smoke_report,
        "list_smoke_reports": list_smoke_reports,
        "run_production_verification": run_production_verification,
        "save_production_verification_report": save_production_verification_report,
    }
    missing = [name for name, fn in required.items() if not callable(fn)]
    return _check(
        "production_proof_surface",
        not missing,
        "Production hardening exposes health/readiness/metrics, alerts, and persisted smoke evidence.",
        {"callables": sorted(required), "missing": missing},
    )


def _check(key: str, ok: bool, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return make_check(key, ok, message, details)


def _requirement(
    *,
    key: str,
    requirement: str,
    evidence: list[str],
    checks: list[dict[str, Any] | None],
    needs_live_proof: bool = False,
    live_verified: bool = False,
) -> dict[str, Any]:
    related_checks = [check for check in checks if check]
    code_ok = bool(related_checks) and all(bool(check.get("ok")) for check in related_checks)
    return {
        "key": key,
        "requirement": requirement,
        "evidence": evidence,
        "checks": [check.get("key") for check in related_checks],
        "code_ok": code_ok,
        "needs_live_proof": needs_live_proof,
        "production_verified": bool(live_verified) if needs_live_proof else code_ok,
        "status": (
            "production_verified" if needs_live_proof and live_verified else
            "needs_live_proof" if needs_live_proof and code_ok else
            "code_ready" if code_ok else
            "missing_code_evidence"
        ),
    }


def _latest_live_production_proof(*, require_final_launch_proof: bool = True) -> dict[str, Any]:
    try:
        from backend.production_launch import get_final_launch_proof, verify_final_launch_proof_manifest
        from backend.production_verify import get_production_verification_report, verify_production_verification_manifest

        report = get_production_verification_report("latest")
        verification_manifest = verify_production_verification_manifest("latest")
        launch_proof = get_final_launch_proof("latest")
        launch_manifest = verify_final_launch_proof_manifest("latest")
        payload = report.get("report") or {}
        proof_payload = launch_proof.get("proof") or {}
        lower_proof_ok = bool(
            report.get("found")
            and payload.get("ok")
            and payload.get("live_connectors")
            and verification_manifest.get("verified")
        )
        final_proof_ok = bool(
            launch_proof.get("found")
            and proof_payload.get("ok")
            and launch_manifest.get("verified")
        )
        ok = bool(lower_proof_ok and (final_proof_ok if require_final_launch_proof else True))
        return {
            "ok": ok,
            "requires_final_launch_proof": require_final_launch_proof,
            "report_found": bool(report.get("found")),
            "report_ok": bool(payload.get("ok")),
            "live_connectors": bool(payload.get("live_connectors")),
            "manifest_verified": bool(verification_manifest.get("verified")),
            "launch_proof_found": bool(launch_proof.get("found")),
            "launch_proof_ok": bool(proof_payload.get("ok")),
            "launch_manifest_verified": bool(launch_manifest.get("verified")),
            "report_id": payload.get("id") or "latest",
            "proof_id": proof_payload.get("id") or "latest",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

"""Run-level completion audit for Agent Stack executions."""

from __future__ import annotations

from typing import Any


FINAL_APPROVAL_STATES = {"approved", "skipped", "rejected", "expired"}
TERMINAL_RUN_STATES = {"done", "stalled", "error", "failed", "killed", "cancelled", "stopped"}


def build_run_completion_audit(session_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Audit a persisted session state against its stack execution blueprint."""
    terminal = _is_terminal_run(state)
    blueprint = state.get("execution_blueprint") or {}
    lanes = blueprint.get("lanes") or []
    lane_status_by_id = {
        str(item.get("lane_id") or item.get("id") or item.get("task_id") or ""): item
        for item in state.get("lane_status", [])
    }
    lane_status_by_agent = {
        str(item.get("agent") or ""): item
        for item in state.get("lane_status", [])
        if item.get("agent")
    }
    artifacts = {str(item.get("key") or "") for item in state.get("artifacts", []) if item.get("key")}
    verifications = {
        str(item.get("lane_id") or item.get("task_id") or item.get("agent") or ""): item
        for item in state.get("artifact_verifications", [])
    }
    verifications_by_agent = {
        str(item.get("agent") or ""): item
        for item in state.get("artifact_verifications", [])
        if item.get("agent")
    }

    lane_results = []
    for lane in lanes:
        lane_id = str(lane.get("id") or "")
        agent = str(lane.get("agent") or "")
        status = lane_status_by_id.get(lane_id) or lane_status_by_agent.get(agent) or {}
        verification = verifications.get(lane_id) or verifications_by_agent.get(agent) or {}
        required_keys = [
            str(deliverable.get("artifact_key") or "")
            for deliverable in lane.get("deliverables", [])
            if deliverable.get("required", True)
        ]
        missing_artifacts = [key for key in required_keys if key and key not in artifacts]
        weak_artifacts = list(verification.get("required_weak") or [])
        verification_status = verification.get("status") or ("missing" if required_keys else "not_required")
        lane_ok = (
            status.get("status") == "done"
            and not missing_artifacts
            and not weak_artifacts
            and verification_status in {"passed", "not_required"}
        )
        lane_results.append({
            "lane_id": lane_id,
            "agent": agent,
            "status": status.get("status") or "missing",
            "ok": lane_ok,
            "required_artifacts": required_keys,
            "missing_artifacts": missing_artifacts,
            "weak_artifacts": weak_artifacts,
            "verification_status": verification_status,
        })

    approvals = state.get("approvals", [])
    approval_results = [
        {
            "key": item.get("key") or item.get("gate_key"),
            "status": item.get("status") or "pending",
            "ok": (item.get("status") or "pending") in FINAL_APPROVAL_STATES or (item.get("status") == "armed" and not item.get("triggered_by")),
            "triggered_by": item.get("triggered_by"),
        }
        for item in approvals
    ]

    memory = _company_brain_handoff_check(session_id, state, required=terminal)
    deployment = _deployment_health_check(state, required=terminal)
    checks = [
        {
            "key": "execution_blueprint_present",
            "ok": bool(blueprint.get("stack_id") and lanes),
            "message": "Session has a stack execution blueprint.",
        },
        {
            "key": "lanes_complete",
            "ok": bool(lanes) and all(item["ok"] for item in lane_results),
            "message": "Every lane is done and has passing required artifacts.",
            "details": {"lanes": lane_results},
        },
        {
            "key": "approvals_resolved",
            "ok": all(item["ok"] for item in approval_results),
            "message": "Triggered approval gates are resolved or left in safe non-triggered state.",
            "details": {"approvals": approval_results},
        },
        {
            "key": "company_brain_handoff",
            "ok": memory["ok"],
            "message": (
                "Run handoff evidence is present in Company Brain."
                if terminal
                else "Company Brain handoff will be required before this run can finish."
            ),
            "details": memory,
        },
        {
            "key": "deployment_health",
            "ok": deployment["ok"],
            "message": (
                "Deployment outputs stayed healthy after post-run verification."
                if terminal and deployment["ok"]
                else (
                    "Deployment outputs failed post-run verification or triggered review flags."
                    if terminal
                    else "Deployment health will be verified before this run is marked finished."
                )
            ),
            "details": deployment,
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    if not terminal:
        failed = [check for check in failed if check["key"] in set()]
    audit_ok = not failed
    audit_status = (
        "pending"
        if not terminal
        else ("complete" if audit_ok else "incomplete")
    )
    summary = (
        "Run completion audit passed."
        if terminal and audit_ok
        else (
            f"Run completion audit has {len(failed)} gap(s)."
            if terminal
            else "Run completion audit is tracking progress until the run reaches a terminal state."
        )
    )
    return {
        "session_id": session_id,
        "ok": audit_ok,
        "status": audit_status,
        "checks": checks,
        "failed": failed,
        "summary": summary,
    }


def _company_brain_handoff_check(session_id: str, state: dict[str, Any], *, required: bool) -> dict[str, Any]:
    if not required:
        return {"ok": True, "required": False, "matched_records": 0, "reason": "Run still in progress."}
    founder_id = _founder_id(state)
    if not founder_id:
        return {"ok": False, "required": True, "founder_id": "", "matched_records": 0, "reason": "No founder id in session state."}
    try:
        from backend.tools.company_brain import get_company_brain
        brain = get_company_brain(founder_id)
    except Exception as exc:
        return {"ok": False, "required": True, "founder_id": founder_id, "matched_records": 0, "reason": str(exc)}
    records = [
        record for record in brain.get("records", [])
        if session_id in str(record.get("title", "")) or session_id in str(record.get("content", "")) or session_id == str((record.get("metadata") or {}).get("session_id") or "")
    ]
    return {
        "ok": bool(records),
        "required": True,
        "founder_id": founder_id,
        "matched_records": len(records),
        "record_titles": [record.get("title") for record in records[:5]],
    }


def _deployment_health_check(state: dict[str, Any], *, required: bool) -> dict[str, Any]:
    urls: list[str] = []
    for agent in (state.get("agents") or {}).values():
        if not isinstance(agent, dict):
            continue
        result = agent.get("result") or {}
        if isinstance(result, dict):
            for key in ("deploy_url", "preview_url", "live_url", "url"):
                value = result.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    urls.append(value)
                    break
        preview = agent.get("previewUrl")
        if isinstance(preview, str) and preview.startswith(("http://", "https://")):
            urls.append(preview)

    state_preview = state.get("previewUrl")
    if isinstance(state_preview, str) and state_preview.startswith(("http://", "https://")):
        urls.append(state_preview)

    session_meta = state.get("session_meta") or {}
    meta_deploy = session_meta.get("deploy_url")
    if isinstance(meta_deploy, str) and meta_deploy.startswith(("http://", "https://")):
        urls.append(meta_deploy)

    deploy_failures = [
        item for item in (state.get("deployment_checks") or [])
        if isinstance(item, dict)
    ]
    review_reason = str(state.get("review_reason") or session_meta.get("review_reason") or "")
    needs_review = bool(state.get("needs_review") or session_meta.get("needs_review"))
    deploy_review_flag = needs_review and "deploy" in review_reason.lower()

    unique_urls = list(dict.fromkeys(urls))
    ok = not required or (not deploy_failures and not deploy_review_flag)
    return {
        "ok": ok,
        "required": required,
        "deploy_urls": unique_urls[:10],
        "failed_checks": deploy_failures[:10],
        "needs_review": needs_review,
        "review_reason": review_reason,
    }


def _is_terminal_run(state: dict[str, Any]) -> bool:
    status = str(state.get("status") or state.get("session_meta", {}).get("status") or "").lower()
    if status in TERMINAL_RUN_STATES:
        return True
    if state.get("session_meta", {}).get("completed_at"):
        return True
    return False


def _founder_id(state: dict[str, Any]) -> str:
    if state.get("founder_id"):
        return str(state["founder_id"])
    digest = state.get("digest") or {}
    if digest.get("founder_id"):
        return str(digest["founder_id"])
    stack = state.get("stack") or {}
    if stack.get("founder_id"):
        return str(stack["founder_id"])
    ledger = state.get("run_ledger") or {}
    if ledger.get("founder_id"):
        return str(ledger["founder_id"])
    return ""

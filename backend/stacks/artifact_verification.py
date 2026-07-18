"""Deterministic artifact verification against stack execution blueprints."""

from __future__ import annotations

from typing import Any


_GENERIC_PHRASES = (
    "plan details will appear",
    "placeholder",
    "lorem ipsum",
    "coming soon",
    "todo",
    "tbd",
    "not provided",
)


def verify_task_artifacts(task: dict[str, Any], result: Any, execution_blueprint: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate one completed task against its expected blueprint deliverables."""
    blueprint = execution_blueprint or {}
    lane = _lane_for_task(task, blueprint)
    deliverables = lane.get("deliverables") or _deliverables_from_task(task)
    expected_keys = set(task.get("expected_artifacts") or [])
    if expected_keys:
        deliverables = [
            deliverable for deliverable in deliverables
            if (deliverable.get("artifact_key") or deliverable.get("key")) in expected_keys
        ] or _deliverables_from_task(task)
    artifact_results = [
        _verify_artifact(deliverable, result)
        for deliverable in deliverables
    ]
    required = [item for item in artifact_results if item.get("required")]
    missing_required = [item for item in required if item["status"] == "missing"]
    weak_required = [item for item in required if item["status"] == "weak"]
    status = "passed"
    if missing_required:
        status = "blocked"
    elif weak_required:
        status = "needs_review"
    return {
        "task_id": task.get("id", ""),
        "lane_id": lane.get("id") or task.get("id", ""),
        "agent": task.get("agent", ""),
        "status": status,
        "artifact_count": len(artifact_results),
        "passed_count": len([item for item in artifact_results if item["status"] == "passed"]),
        "weak_count": len([item for item in artifact_results if item["status"] == "weak"]),
        "missing_count": len([item for item in artifact_results if item["status"] == "missing"]),
        "required_missing": [item["artifact_key"] for item in missing_required],
        "required_weak": [item["artifact_key"] for item in weak_required],
        "artifacts": artifact_results,
        "summary": _summary(status, artifact_results),
    }


def _lane_for_task(task: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    lanes = blueprint.get("lanes") or []
    task_id = task.get("id", "")
    agent = task.get("agent", "")
    return (
        next((lane for lane in lanes if lane.get("id") == task_id), None)
        or next((lane for lane in lanes if lane.get("agent") == agent), None)
        or {}
    )


def _deliverables_from_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_key": key,
            "title": str(key).replace("_", " ").title(),
            "required": True,
            "acceptance_checks": [
                "Includes concrete content.",
                "Is specific enough for downstream handoff.",
            ],
        }
        for key in task.get("expected_artifacts", [])
    ]


def _verify_artifact(deliverable: dict[str, Any], result: Any) -> dict[str, Any]:
    key = str(deliverable.get("artifact_key") or deliverable.get("key") or "")
    title = str(deliverable.get("title") or key)
    evidence = _artifact_evidence(result, key)
    status = _artifact_status(evidence, bool(deliverable.get("required", True)))
    failed_checks = []
    if status == "missing":
        failed_checks.append("No usable evidence found in agent result.")
    elif status == "weak":
        failed_checks.append("Evidence is too short or generic for production handoff.")
    return {
        "artifact_key": key,
        "title": title,
        "required": bool(deliverable.get("required", True)),
        "status": status,
        "evidence_preview": evidence[:360],
        "evidence_chars": len(evidence),
        "acceptance_checks": list(deliverable.get("acceptance_checks") or []),
        "failed_checks": failed_checks,
    }


def _artifact_evidence(result: Any, artifact_key: str) -> str:
    if not isinstance(result, dict):
        return str(result or "").strip()
    candidates = [
        result.get(artifact_key),
        (result.get("artifacts") or {}).get(artifact_key) if isinstance(result.get("artifacts"), dict) else None,
        result.get("summary"),
        result.get("output_summary"),
        result.get("formatted_text"),
        result.get("report"),
        result.get("text"),
        result.get("markdown"),
        result.get("html"),
        result.get("url"),
        result.get("preview_url"),
    ]
    for candidate in candidates:
        if candidate:
            if isinstance(candidate, (dict, list)):
                return str(candidate).strip()
            return str(candidate).strip()
    return ""


def _artifact_status(evidence: str, required: bool) -> str:
    text = " ".join(evidence.lower().split())
    if not text:
        return "missing" if required else "weak"
    if len(text) < 40:
        return "weak"
    if any(phrase in text for phrase in _GENERIC_PHRASES):
        return "weak"
    return "passed"


def _summary(status: str, artifacts: list[dict[str, Any]]) -> str:
    if status == "passed":
        if not artifacts:
            return "Completed; no per-lane artifact checks required."
        return f"{len(artifacts)} artifact checks passed."
    if status == "blocked":
        missing = [item["artifact_key"] for item in artifacts if item["status"] == "missing"]
        return "Missing required artifacts: " + ", ".join(missing)
    weak = [item["artifact_key"] for item in artifacts if item["status"] == "weak"]
    return "Weak artifact evidence needs review: " + ", ".join(weak)

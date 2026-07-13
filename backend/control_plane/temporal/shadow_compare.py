"""Wave 3 shadow-comparison helpers.

Compares legacy and shadow/Temporal observations without executing side effects.
The comparator is deliberately deterministic and categorizes discrepancies so
canary rollout logic can halt on specific safety failures instead of a vague
"mismatch".
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from backend.control_plane.models import ShadowComparison


@dataclass
class ShadowComparisonResult:
    passed: bool
    discrepancies: list[dict[str, Any]]


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(artifact.get("metadata") or {})
    return {
        "key": artifact.get("key") or artifact.get("id"),
        "content_hash": artifact.get("content_hash"),
        "uri": artifact.get("uri"),
        "verification_status": artifact.get("verification_status"),
        "semantic_hash": _stable_hash(
            {
                "uri": artifact.get("uri"),
                "metadata": metadata,
                "verification_status": artifact.get("verification_status"),
            }
        ),
    }


def _compare_terminal_status(legacy_status: str, shadow_status: str) -> list[dict[str, Any]]:
    if legacy_status == shadow_status:
        return []
    return [{
        "category": "terminal_status_mismatch",
        "severity": "critical",
        "legacy_status": legacy_status,
        "shadow_status": shadow_status,
    }]


def _compare_event_subset(
    legacy_events: Iterable[dict[str, Any]],
    shadow_events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    legacy_types = [str(event.get("event_type") or event.get("type") or "") for event in legacy_events]
    shadow_types = [str(event.get("event_type") or event.get("type") or "") for event in shadow_events]
    cursor = 0
    for event_type in shadow_types:
        while cursor < len(legacy_types) and legacy_types[cursor] != event_type:
            cursor += 1
        if cursor >= len(legacy_types):
            return [{
                "category": "event_order_subset_mismatch",
                "severity": "critical",
                "missing_event_type": event_type,
                "legacy_event_types": legacy_types,
                "shadow_event_types": shadow_types,
            }]
        cursor += 1
    return []


def _compare_artifacts(
    legacy_artifacts: Iterable[dict[str, Any]],
    shadow_artifacts: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    discrepancies: list[dict[str, Any]] = []
    legacy_map = {_normalize_artifact(artifact)["key"]: _normalize_artifact(artifact) for artifact in legacy_artifacts}
    shadow_map = {_normalize_artifact(artifact)["key"]: _normalize_artifact(artifact) for artifact in shadow_artifacts}
    for key in sorted(set(legacy_map) | set(shadow_map)):
        legacy_artifact = legacy_map.get(key)
        shadow_artifact = shadow_map.get(key)
        if legacy_artifact is None or shadow_artifact is None:
            discrepancies.append({
                "category": "artifact_presence_mismatch",
                "severity": "critical",
                "artifact_key": key,
                "legacy_present": legacy_artifact is not None,
                "shadow_present": shadow_artifact is not None,
            })
            continue
        if legacy_artifact["content_hash"] and shadow_artifact["content_hash"]:
            if legacy_artifact["content_hash"] != shadow_artifact["content_hash"]:
                discrepancies.append({
                    "category": "artifact_hash_mismatch",
                    "severity": "critical",
                    "artifact_key": key,
                    "legacy_content_hash": legacy_artifact["content_hash"],
                    "shadow_content_hash": shadow_artifact["content_hash"],
                })
            continue
        if legacy_artifact["semantic_hash"] != shadow_artifact["semantic_hash"]:
            discrepancies.append({
                "category": "artifact_semantic_mismatch",
                "severity": "warning",
                "artifact_key": key,
                "legacy_semantic_hash": legacy_artifact["semantic_hash"],
                "shadow_semantic_hash": shadow_artifact["semantic_hash"],
            })
    return discrepancies


def _compare_costs(legacy_cost_usd: Optional[float], shadow_cost_usd: Optional[float], tolerance: float = 0.15) -> list[dict[str, Any]]:
    if legacy_cost_usd is None or shadow_cost_usd is None:
        return []
    if legacy_cost_usd == 0:
        if shadow_cost_usd == 0:
            return []
        return [{
            "category": "cost_tolerance_exceeded",
            "severity": "warning",
            "legacy_cost_usd": legacy_cost_usd,
            "shadow_cost_usd": shadow_cost_usd,
            "tolerance": tolerance,
        }]
    delta = abs(shadow_cost_usd - legacy_cost_usd) / legacy_cost_usd
    if delta <= tolerance:
        return []
    return [{
        "category": "cost_tolerance_exceeded",
        "severity": "warning",
        "legacy_cost_usd": legacy_cost_usd,
        "shadow_cost_usd": shadow_cost_usd,
        "tolerance": tolerance,
        "relative_delta": delta,
    }]


def compare_run_snapshots(
    *,
    run_id: str,
    legacy_status: str,
    shadow_status: str,
    legacy_events: Iterable[dict[str, Any]],
    shadow_events: Iterable[dict[str, Any]],
    legacy_artifacts: Iterable[dict[str, Any]],
    shadow_artifacts: Iterable[dict[str, Any]],
    legacy_cost_usd: Optional[float] = None,
    shadow_cost_usd: Optional[float] = None,
) -> ShadowComparisonResult:
    discrepancies: list[dict[str, Any]] = []
    discrepancies.extend(_compare_terminal_status(legacy_status, shadow_status))
    discrepancies.extend(_compare_event_subset(legacy_events, shadow_events))
    discrepancies.extend(_compare_artifacts(legacy_artifacts, shadow_artifacts))
    discrepancies.extend(_compare_costs(legacy_cost_usd, shadow_cost_usd))
    return ShadowComparisonResult(
        passed=not any(item.get("severity") == "critical" for item in discrepancies),
        discrepancies=discrepancies,
    )


def persist_shadow_comparison(
    *,
    repository: Any,
    run_id: str,
    comparison_type: str,
    result: ShadowComparisonResult,
) -> ShadowComparison:
    record = ShadowComparison(
        id=str(uuid.uuid4()),
        run_id=run_id,
        comparison_type=comparison_type,
        discrepancies=result.discrepancies,
        passed=result.passed,
    )
    return repository.create(record)

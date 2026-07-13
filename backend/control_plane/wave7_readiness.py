"""Wave 7 readiness report.

Separates what is provably implemented in-repo from what still requires live
rollout evidence in production.
"""
from __future__ import annotations

from typing import Any

from backend.control_plane.wave7_archival import build_legacy_retirement_manifest
from backend.control_plane.wave7_rollout import rollout_status_snapshot


def build_wave7_readiness_report() -> dict[str, Any]:
    rollout = rollout_status_snapshot()
    legacy_manifest = build_legacy_retirement_manifest()

    checks = [
        _check_rollout_governance(rollout),
        _check_archival_support(legacy_manifest),
        _check_legacy_retirement_manifest(legacy_manifest),
        _check_live_rollout_evidence(rollout),
    ]

    complete = all(check["status"] == "complete" for check in checks)
    return {
        "ok": True,
        "wave": 7,
        "complete": complete,
        "checks": checks,
        "rollout": rollout,
        "legacy_retirement_manifest": legacy_manifest,
    }


def _check_rollout_governance(rollout: dict[str, Any]) -> dict[str, Any]:
    campaigns = rollout.get("campaigns") or {}
    has_any_campaign_structure = isinstance(campaigns, dict)
    return {
        "key": "rollout_governance",
        "status": "complete" if has_any_campaign_structure else "incomplete",
        "evidence": "Wave 7 rollout status snapshot and campaign model exist",
        "details": {"campaign_count": len(campaigns)},
    }


def _check_archival_support(legacy_manifest: dict[str, Any]) -> dict[str, Any]:
    has_manifest = bool(legacy_manifest.get("items"))
    return {
        "key": "archival_snapshot_support",
        "status": "complete" if has_manifest else "incomplete",
        "evidence": "Wave 7 archival snapshot export and manifest builder exist",
        "details": {"tracked_targets": len(legacy_manifest.get("items") or [])},
    }


def _check_legacy_retirement_manifest(legacy_manifest: dict[str, Any]) -> dict[str, Any]:
    ready = bool(legacy_manifest.get("ready_for_delete_last"))
    return {
        "key": "legacy_delete_last_readiness",
        "status": "complete" if ready else "needs_live_evidence",
        "evidence": "Delete-last manifest computed from current repo/workspace state",
        "details": {
            "ready_for_delete_last": ready,
            "blocking_targets": [
                item["key"]
                for item in legacy_manifest.get("items") or []
                if not item.get("retirement_ready")
            ],
        },
    }


def _check_live_rollout_evidence(rollout: dict[str, Any]) -> dict[str, Any]:
    campaigns = rollout.get("campaigns") or {}
    legacy_retirement = rollout.get("legacy_retirement") or {}
    has_completed_campaign = any(
        str((campaign or {}).get("status") or "").lower() == "completed"
        for campaign in campaigns.values()
    )
    has_ready_retirement = any(
        str((check or {}).get("status") or "").lower() == "ready"
        for check in legacy_retirement.values()
    )
    status = "complete" if has_completed_campaign and has_ready_retirement else "needs_live_evidence"
    return {
        "key": "live_rollout_evidence",
        "status": status,
        "evidence": "Campaign completion and legacy-retirement readiness require real production evidence",
        "details": {
            "completed_campaign_present": has_completed_campaign,
            "ready_retirement_present": has_ready_retirement,
        },
    }

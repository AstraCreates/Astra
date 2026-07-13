"""Wave 3 Temporal shadow-runtime wiring.

Launches hidden observation-only shadow runs and compares them to the visible
legacy run once both have reached a terminal state.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Optional

from backend.control_plane.supabase_repositories import SupabaseRunRepository, durable_create_run_with_event
from backend.control_plane.temporal.shadow_compare import compare_run_snapshots, persist_shadow_comparison

logger = logging.getLogger(__name__)

_DEFAULT_SHADOW_BUDGET_LIMIT_USD = float(os.environ.get("ASTRA_TEMPORAL_SHADOW_BUDGET_USD", "0.05"))
_comparison_locks: dict[str, threading.Lock] = {}
_comparison_locks_guard = threading.Lock()


def _comparison_lock(run_id: str) -> threading.Lock:
    lock = _comparison_locks.get(run_id)
    if lock is None:
        with _comparison_locks_guard:
            lock = _comparison_locks.get(run_id)
            if lock is None:
                lock = threading.Lock()
                _comparison_locks[run_id] = lock
    return lock


def shadow_run_id_for(run_id: str) -> str:
    return f"{run_id}__shadow"


def _terminal_session_status(meta: dict[str, Any] | None) -> Optional[str]:
    status = str((meta or {}).get("status") or "").lower()
    if status in {"done", "error", "killed"}:
        return status
    return None


def _session_cost_usd(session_id: str) -> Optional[float]:
    try:
        from backend.core.usage import get_session_cost

        payload = get_session_cost(session_id) or {}
        cost_usd = payload.get("cost_usd")
        return None if cost_usd is None else float(cost_usd)
    except Exception:
        return None


def _session_artifacts_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = state.get("artifacts") or {}
    if isinstance(artifacts, dict):
        return list(artifacts.values())
    if isinstance(artifacts, list):
        return list(artifacts)
    return []


def _session_events_for_compare(events: list[tuple[int, dict]]) -> list[dict[str, Any]]:
    return [{"sequence": event_id, "event_type": event.get("type", ""), "payload": event} for event_id, event in events]


def _build_state_snapshot(session_id: str) -> tuple[dict[str, Any], list[tuple[int, dict]], dict[str, Any] | None]:
    from backend.core.session_store import get_session_meta, load_events
    from backend.workflow_state import build_session_state

    events = load_events(session_id) or []
    return build_session_state(session_id, events), events, get_session_meta(session_id)


def maybe_compare_shadow_run(run_id: str, shadow_run_id: str) -> bool:
    from backend.core.session_store import get_session_meta, merge_session_meta
    from backend.control_plane.fakes import FakeShadowComparisonRepository
    from backend.control_plane.supabase_repositories import SupabaseShadowComparisonRepository
    from backend.config import settings

    with _comparison_lock(run_id):
        run_meta = get_session_meta(run_id) or {}
        shadow_meta = get_session_meta(shadow_run_id) or {}
        if not _terminal_session_status(run_meta) or not _terminal_session_status(shadow_meta):
            return False
        if (run_meta.get("shadow_comparison_status") or "") == "completed":
            return False

        merge_session_meta(run_id, shadow_comparison_status="comparing", shadow_run_id=shadow_run_id)

        legacy_state, legacy_events, legacy_meta = _build_state_snapshot(run_id)
        shadow_state, shadow_events, shadow_meta = _build_state_snapshot(shadow_run_id)

        result = compare_run_snapshots(
            run_id=run_id,
            legacy_status=str((legacy_meta or {}).get("status") or ""),
            shadow_status=str((shadow_meta or {}).get("status") or ""),
            legacy_events=_session_events_for_compare(legacy_events),
            shadow_events=_session_events_for_compare(shadow_events),
            legacy_artifacts=_session_artifacts_from_state(legacy_state),
            shadow_artifacts=_session_artifacts_from_state(shadow_state),
            legacy_cost_usd=_session_cost_usd(run_id),
            shadow_cost_usd=_session_cost_usd(shadow_run_id),
        )

        try:
            repo = (
                SupabaseShadowComparisonRepository()
                if settings.supabase_url and settings.supabase_key
                else FakeShadowComparisonRepository()
            )
        except Exception:
            repo = FakeShadowComparisonRepository()
        stored = persist_shadow_comparison(
            repository=repo,
            run_id=run_id,
            comparison_type="temporal_shell_vs_legacy",
            result=result,
        )
        merge_session_meta(
            run_id,
            shadow_comparison_status="completed",
            shadow_comparison_id=stored.id,
            shadow_comparison_passed=stored.passed,
            shadow_run_id=shadow_run_id,
        )
        try:
            current_run = SupabaseRunRepository().get(run_id)
            SupabaseRunRepository().update_fields(
                run_id,
                {
                    "metadata": {
                        **dict((current_run.metadata if current_run else {}) or {}),
                        "shadow_comparison_id": stored.id,
                        "shadow_comparison_passed": stored.passed,
                        "shadow_run_id": shadow_run_id,
                    }
                },
            )
        except Exception:
            pass
        logger.info(
            "shadow comparison complete run=%s shadow=%s passed=%s discrepancies=%d",
            run_id,
            shadow_run_id,
            stored.passed,
            len(stored.discrepancies),
        )
        return True


async def start_shadow_run(
    *,
    founder_id: str,
    instruction: str,
    source_run_id: str,
    company_id: str,
    workspace_id: str,
    chapter_id: str,
    stack_id: str | None,
    constraints: dict[str, Any] | None,
    parent_run_id: str | None = None,
    prior_session_id: str | None = None,
    continue_run: bool = False,
) -> str:
    from backend.control_plane.models import Run
    from backend.control_plane.budget import BudgetExceededError, get_default_budget_service
    from backend.control_plane.rollout import assign_run_features
    from backend.control_plane.start_run import _run_created_payload
    from backend.control_plane.temporal.dispatch import start_run as start_temporal_workflow
    from backend.core.session_store import merge_session_meta, register_session

    hidden_run_id = shadow_run_id_for(source_run_id)
    shadow_constraints = dict(constraints or {})
    shadow_constraints.update({
        "shadow_mode": True,
        "shadow_source_run_id": source_run_id,
        "compare_target_run_id": source_run_id,
    })

    register_session(
        session_id=hidden_run_id,
        founder_id=founder_id,
        goal=instruction,
        stack_id=str(stack_id or ""),
        company_name="",
        agents=list(shadow_constraints.get("agents", [])),
        workspace_id=workspace_id,
        company_id=company_id,
        chapter_id=chapter_id,
        parent_session_id=source_run_id,
        kind="shadow",
        visible=False,
    )
    merge_session_meta(
        hidden_run_id,
        engine="temporal",
        shadow_mode=True,
        shadow_source_run_id=source_run_id,
        shadow_parent_run_id=source_run_id,
        constraints=shadow_constraints,
        continue_run=continue_run,
        prior_session_id=prior_session_id or "",
        budget_limit_usd=_DEFAULT_SHADOW_BUDGET_LIMIT_USD,
        shadow_comparison_status="pending",
    )

    try:
        await asyncio.to_thread(
            get_default_budget_service().reserve,
            run_id=hidden_run_id,
            founder_id=founder_id,
            estimated_max_usd=_DEFAULT_SHADOW_BUDGET_LIMIT_USD,
            ttl_seconds=900,
        )
    except BudgetExceededError:
        logger.warning("shadow run skipped for %s: insufficient budget headroom", source_run_id)
        return ""
    except Exception as exc:
        logger.warning("shadow run budget reservation failed for %s: %s", source_run_id, exc)

    feature_assignment = assign_run_features(company_id, hidden_run_id, founder_id=founder_id)
    feature_assignment["engine"] = "temporal"
    feature_assignment["control_plane_v2"] = True
    shadow_run = Run(
        id=hidden_run_id,
        owner_id=founder_id,
        org_id=company_id,
        company_id=company_id or None,
        workspace_id=workspace_id or None,
        chapter_id=chapter_id or None,
        parent_run_id=parent_run_id or source_run_id,
        goal=instruction,
        stack_id=stack_id or None,
        engine="temporal",
        budget_limit_usd=_DEFAULT_SHADOW_BUDGET_LIMIT_USD,
        metadata={
            "feature_assignment": feature_assignment,
            "shadow_mode": True,
            "shadow_source_run_id": source_run_id,
            "shadow_parent_run_id": source_run_id,
            "hidden": True,
        },
    )
    await durable_create_run_with_event(
        shadow_run,
        payload=_run_created_payload(
            run_id=hidden_run_id,
            founder_id=founder_id,
            company_id=company_id,
            workspace_id=workspace_id,
            chapter_id=chapter_id,
            engine="temporal",
            feature_assignment=feature_assignment,
            prior_session_id=prior_session_id,
            continue_run=continue_run,
        ),
    )
    await start_temporal_workflow(
        run_id=hidden_run_id,
        founder_id=founder_id,
        company_id=company_id or None,
        workspace_id=workspace_id or None,
        chapter_id=chapter_id or None,
        shadow=True,
    )
    merge_session_meta(source_run_id, shadow_run_id=hidden_run_id, shadow_comparison_status="pending")
    return hidden_run_id

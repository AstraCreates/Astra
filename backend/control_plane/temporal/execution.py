"""Pure execution helpers for Temporal-backed Astra runs."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Optional

from backend.control_plane.models import RunStep
from backend.control_plane.temporal.contracts import (
    LaneAttemptInput,
    LaneAttemptResult,
    MultiPhaseRunInput,
    PhaseRunInput,
    RunInput,
    VerificationInput,
    VerificationResult,
)
from backend.observability.tracing import artifact_span, step_attempt_span

logger = logging.getLogger(__name__)

_DEFAULT_PHASE_ORDER = ("diagnose", "design", "deploy", "govern", "operate")


def _activity_queue_delay_seconds() -> Optional[float]:
    """Schedule-to-start latency for the current Temporal activity, or None
    when not running inside one (direct/unit-test invocations of
    execute_lane_attempt, or the legacy-orchestrator engine). Real Temporal
    data (activity.info().scheduled_time), never a fabricated estimate --
    that's the whole point of this being optional at the call site rather
    than defaulting to 0."""
    try:
        from temporalio import activity

        info = activity.info()
        scheduled = info.scheduled_time
        if scheduled is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - scheduled).total_seconds())
    except Exception:
        return None


class TemporalPlanRetryableError(RuntimeError):
    pass


class TemporalPlanNonRetryableError(ValueError):
    pass


def _derive_step_specs_from_stack(session_meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from backend.core.orchestrator import _RESEARCH_LANE_FOCUS, candidate_research_agents_for_default_provider
    from backend.stacks import get_stack_template

    goal = str(session_meta.get("goal") or "").strip()
    stack_id = str(session_meta.get("stack_id") or ((session_meta.get("constraints") or {}).get("stack_id")) or "").strip()
    if not goal:
        return {}

    stack_template = get_stack_template(stack_id or None)
    template_tasks = list(getattr(stack_template, "tasks", []) or [])
    step_specs: dict[str, dict[str, Any]] = {}
    research_step_keys: list[str] = []
    planner_research_ids: set[str] = set()

    for task in template_tasks:
        if str(getattr(task, "agent", "") or "") != "research":
            continue
        planner_research_ids.add(str(getattr(task, "id", "") or "t_research"))
        instruction = (
            f"{getattr(task, 'instruction', '')}\n\n"
            f"Founder goal: {goal}\n\n"
            f"Stack: {stack_template.name}. Primary outcome: {stack_template.primary_outcome}"
        ).strip()
        for task_id, agent_name in candidate_research_agents_for_default_provider():
            research_step_keys.append(task_id)
            step_specs[task_id] = {
                "task_id": task_id,
                "agent": agent_name,
                "instruction": f"{instruction}\n\n{_RESEARCH_LANE_FOCUS.get(agent_name, '')}".strip(),
                "phase": "diagnose",
                "depends_on": [],
                # The legacy orchestrator's own fan-out of this same single "research" task
                # into focused parallel lanes (core/orchestrator.py's parallel_research_tasks)
                # never puts task.artifacts on the fanned lanes -- each lane's focus (market
                # size vs named competitors vs customer intel vs GTM, see _RESEARCH_LANE_FOCUS)
                # only covers part of the parent task's full artifact set, so requiring every
                # lane to individually produce market_brief/icp_brief/pricing_hypothesis is
                # unsatisfiable for 3 of the 4 lanes by construction. Confirmed live: this
                # cloned requirement left research_customers/research_gtm/research permanently
                # "blocked" every restart, retrying against artifacts they were never asked to
                # write, burning real iterations. Match legacy: no per-lane artifact gate here.
                "expected_artifacts": [],
                "stack_task_title": str(getattr(task, "title", "") or "Market foundation"),
            }

    for task in template_tasks:
        agent_name = str(getattr(task, "agent", "") or "").strip()
        if not agent_name or agent_name == "research":
            continue
        instruction = (
            f"{getattr(task, 'instruction', '')}\n\n"
            f"Founder goal: {goal}\n\n"
            f"Stack: {stack_template.name}. Primary outcome: {stack_template.primary_outcome}"
        ).strip()
        task_id = str(getattr(task, "id", "") or agent_name)
        depends_on = [str(dep) for dep in list(getattr(task, "depends_on", []) or []) if str(dep)]
        rewritten_deps: list[str] = []
        for dep in depends_on:
            if dep in planner_research_ids:
                rewritten_deps.extend(research_step_keys)
            else:
                rewritten_deps.append(dep)
        step_specs[task_id] = {
            "task_id": task_id,
            "agent": agent_name,
            "instruction": instruction,
            "phase": str(getattr(task, "phase", "") or "deploy") or "deploy",
            "depends_on": rewritten_deps,
            "expected_artifacts": list(getattr(task, "artifacts", []) or []),
            "stack_task_title": str(getattr(task, "title", "") or agent_name),
        }
    return step_specs


def _step_specs_to_plan_payload(
    run_id: str,
    raw_step_specs: dict[str, Any],
    *,
    phase_order: list[str] | None = None,
    timeout_seconds: int = 7200,
) -> dict[str, Any]:
    meta = {
        "temporal_step_specs": dict(raw_step_specs or {}),
        "temporal_phase_order": list(phase_order or []),
        "temporal_phase_timeout_seconds": int(timeout_seconds or 7200),
    }
    _validate_step_specs(dict(raw_step_specs or {}))
    phase_plan = build_multi_phase_run_input(run_id, meta)
    return {
        "run_id": run_id,
        "step_specs": dict(raw_step_specs or {}),
        "phase_order": list(phase_order or []),
        "phases": [
            {
                "run_id": phase.run_id,
                "phase_name": phase.phase_name,
                "next_phase": phase.next_phase,
                "step_keys": list(phase.step_keys or []),
                "step_dependencies": {
                    str(step_key): list(deps or [])
                    for step_key, deps in dict(phase.step_dependencies or {}).items()
                },
                "timeout_seconds": int(phase.timeout_seconds or 7200),
            }
            for phase in list((phase_plan.phases if phase_plan else []) or [])
        ],
    }


def _validate_step_specs(raw_step_specs: dict[str, Any]) -> None:
    if not isinstance(raw_step_specs, dict) or not raw_step_specs:
        raise TemporalPlanNonRetryableError("temporal step specs are empty")

    phases_by_step: dict[str, str] = {}
    for step_key, raw_spec in raw_step_specs.items():
        spec = dict(raw_spec or {})
        agent_name = str(spec.get("agent") or step_key).strip()
        instruction = str(spec.get("instruction") or "").strip()
        if not agent_name:
            raise TemporalPlanNonRetryableError(f"step {step_key!r} is missing an agent")
        if not instruction:
            raise TemporalPlanNonRetryableError(f"step {step_key!r} is missing an instruction")
        phases_by_step[str(step_key)] = str(spec.get("phase") or "deploy").strip() or "deploy"

    for step_key, raw_spec in raw_step_specs.items():
        for dep in [str(dep) for dep in list(dict(raw_spec or {}).get("depends_on") or []) if str(dep)]:
            if dep not in raw_step_specs:
                raise TemporalPlanNonRetryableError(
                    f"step {step_key!r} depends on unknown step {dep!r}"
                )

    adjacency: dict[str, list[str]] = {}
    for step_key, raw_spec in raw_step_specs.items():
        phase_name = phases_by_step[str(step_key)]
        adjacency[str(step_key)] = [
            dep
            for dep in [str(dep) for dep in list(dict(raw_spec or {}).get("depends_on") or []) if str(dep)]
            if phases_by_step.get(dep) == phase_name
        ]

    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(step_key: str) -> None:
        if step_key in visited:
            return
        if step_key in visiting:
            raise TemporalPlanNonRetryableError(f"cycle detected in phase plan at step {step_key!r}")
        visiting.add(step_key)
        for dep in adjacency.get(step_key, []):
            _visit(dep)
        visiting.remove(step_key)
        visited.add(step_key)

    for step_key in adjacency:
        _visit(step_key)


async def build_temporal_run_plan(
    run_id: str,
    session_meta: dict[str, Any] | None,
    *,
    get_orchestrator_fn: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    from backend.stacks import get_stack_template

    meta = dict(session_meta or {})
    existing_step_specs = meta.get("temporal_step_specs") or {}
    if isinstance(existing_step_specs, dict) and existing_step_specs:
        return _step_specs_to_plan_payload(
            run_id,
            existing_step_specs,
            phase_order=list(meta.get("temporal_phase_order") or []),
            timeout_seconds=int(meta.get("temporal_phase_timeout_seconds") or 7200),
        )

    if get_orchestrator_fn is None:
        from backend.core.factory import get_orchestrator

        get_orchestrator_fn = get_orchestrator

    goal = str(meta.get("goal") or "").strip()
    constraints = dict(meta.get("constraints") or {})
    stack_id = str(meta.get("stack_id") or constraints.get("stack_id") or "").strip()
    timeout_seconds = int(meta.get("temporal_phase_timeout_seconds") or 7200)
    phase_order = list(meta.get("temporal_phase_order") or list(_DEFAULT_PHASE_ORDER))

    task_list: list[dict[str, Any]] = []
    selected_agents = [str(agent).strip() for agent in list(constraints.get("agents") or []) if str(agent).strip()]
    if selected_agents:
        orchestrator = get_orchestrator_fn()
        task_list = [
            {
                "id": f"temporal_{agent_name}",
                "agent": agent_name,
                "instruction": goal,
                "depends_on": [],
            }
            for agent_name in selected_agents
            if agent_name in getattr(orchestrator, "specialists", {})
        ]
    elif goal:
        stack_template = get_stack_template(stack_id or None)
        task_list = list(stack_template.build_tasks(goal))

    if not task_list:
        derived = _derive_step_specs_from_stack(meta)
        return _step_specs_to_plan_payload(
            run_id,
            derived,
            phase_order=phase_order,
            timeout_seconds=timeout_seconds,
        )

    from backend.core.orchestrator import _RESEARCH_LANE_FOCUS, candidate_research_agents_for_default_provider

    step_specs: dict[str, dict[str, Any]] = {}
    planner_research_ids: set[str] = set()
    research_step_keys: list[str] = []
    non_research_ids: set[str] = set()

    for task in task_list:
        agent_name = str(task.get("agent") or "").strip()
        task_id = str(task.get("id") or agent_name).strip()
        if not agent_name or not task_id:
            continue
        if agent_name == "research":
            planner_research_ids.add(task_id)
            for derived_id, research_agent_name in candidate_research_agents_for_default_provider():
                research_step_keys.append(derived_id)
                step_specs[derived_id] = {
                    "task_id": derived_id,
                    "agent": research_agent_name,
                    "instruction": f"{task.get('instruction') or goal}\n\n{_RESEARCH_LANE_FOCUS.get(research_agent_name, '')}".strip(),
                    "phase": str(task.get("phase") or "diagnose") or "diagnose",
                    "depends_on": [],
                    # Same bug, second occurrence: see _derive_step_specs_from_stack's
                    # matching comment above. Each fanned lane's focus only covers part
                    # of the parent task's full artifact set -- cloning it here made
                    # research_competitors/research_customers/research_gtm permanently
                    # unable to pass verification. Match legacy's fan-out (no per-lane
                    # artifact requirement at all).
                    "expected_artifacts": [],
                    "stack_task_title": str(task.get("stack_task_title") or task.get("title") or "Market foundation"),
                }
            continue
        non_research_ids.add(task_id)
        step_specs[task_id] = {
            "task_id": task_id,
            "agent": agent_name,
            "instruction": str(task.get("instruction") or goal),
            "phase": str(task.get("phase") or "deploy") or "deploy",
            "depends_on": [str(dep) for dep in list(task.get("depends_on") or []) if str(dep)],
            "expected_artifacts": list(task.get("expected_artifacts") or task.get("deliverables") or []),
            "stack_task_title": str(task.get("stack_task_title") or task.get("title") or agent_name),
        }

    for step_key, spec in list(step_specs.items()):
        depends_on = [str(dep) for dep in list(spec.get("depends_on") or []) if str(dep)]
        rewritten: list[str] = []
        for dep in depends_on:
            if dep in planner_research_ids:
                rewritten.extend(research_step_keys)
            elif dep in non_research_ids or dep in step_specs:
                rewritten.append(dep)
        spec["depends_on"] = rewritten

    return _step_specs_to_plan_payload(
        run_id,
        step_specs,
        phase_order=phase_order,
        timeout_seconds=timeout_seconds,
    )


def _coerce_run_input_values(raw_input: Any) -> dict[str, Any]:
    return {
        "run_id": str((raw_input.get("run_id") if isinstance(raw_input, dict) else getattr(raw_input, "run_id", "")) or ""),
    }


def normalize_run_input(raw_input: Any) -> RunInput:
    if isinstance(raw_input, RunInput):
        return raw_input
    if is_dataclass(raw_input):
        return RunInput(**_coerce_run_input_values(asdict(raw_input)))
    if isinstance(raw_input, dict):
        return RunInput(**_coerce_run_input_values(raw_input))
    if hasattr(raw_input, "run_id"):
        return RunInput(**_coerce_run_input_values(raw_input))
    raise TypeError(f"Unsupported run input type: {type(raw_input)!r}")


def normalize_lane_attempt_input(raw_input: Any) -> LaneAttemptInput:
    if isinstance(raw_input, LaneAttemptInput):
        return raw_input
    if is_dataclass(raw_input):
        values = asdict(raw_input)
        return LaneAttemptInput(
            run_id=str(values.get("run_id") or ""),
            step_key=str(values.get("step_key") or ""),
        )
    if isinstance(raw_input, dict):
        return LaneAttemptInput(
            run_id=str(raw_input.get("run_id") or ""),
            step_key=str(raw_input.get("step_key") or ""),
        )
    return LaneAttemptInput(
        run_id=str(getattr(raw_input, "run_id", "") or ""),
        step_key=str(getattr(raw_input, "step_key", "") or ""),
    )


def normalize_verification_input(raw_input: Any) -> VerificationInput:
    if isinstance(raw_input, VerificationInput):
        return raw_input
    if is_dataclass(raw_input):
        values = asdict(raw_input)
        return VerificationInput(
            run_id=str(values.get("run_id") or ""),
            step_key=str(values.get("step_key") or ""),
            attempt_number=int(values.get("attempt_number") or 1),
        )
    if isinstance(raw_input, dict):
        return VerificationInput(
            run_id=str(raw_input.get("run_id") or ""),
            step_key=str(raw_input.get("step_key") or ""),
            attempt_number=int(raw_input.get("attempt_number") or 1),
        )
    return VerificationInput(
        run_id=str(getattr(raw_input, "run_id", "") or ""),
        step_key=str(getattr(raw_input, "step_key", "") or ""),
        attempt_number=int(getattr(raw_input, "attempt_number", 1) or 1),
    )


def build_orchestrator_constraints(
    run_input: RunInput,
    session_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = session_meta or {}
    constraints = dict(meta.get("constraints") or {})
    founder_id = str(meta.get("founder_id") or "")
    company_id = str(meta.get("company_id") or founder_id)
    workspace_id = str(meta.get("workspace_id") or "")
    chapter_id = str(meta.get("chapter_id") or "")

    constraints["company_id"] = company_id
    if workspace_id:
        constraints["workspace_id"] = workspace_id
    if chapter_id:
        constraints["chapter_id"] = chapter_id
    return constraints


def is_durable_cancel_requested(session_meta: dict[str, Any] | None) -> bool:
    meta = session_meta or {}
    return str(meta.get("status") or "").lower() in {"cancelled", "canceled", "killed"}


def _extract_waiting_approval(session_id: str) -> Optional[dict[str, Any]]:
    try:
        from backend.approval_workflows import expire_approval_requests, get_approval_workflow

        expire_approval_requests(session_id)
        workflow_state = get_approval_workflow(session_id)
        requests = list(workflow_state.get("requests") or [])
        pending = [request for request in requests if str(request.get("status") or "") == "pending"]
        if not pending:
            return None
        latest = pending[-1]
        return {
            "approval_id": latest.get("approval_id") or latest.get("id"),
            "request_id": latest.get("id"),
            "gate_key": latest.get("gate_key"),
            "action_digest": latest.get("action_digest"),
            "required_role": latest.get("required_role"),
            "expires_at": latest.get("expires_at"),
            "title": latest.get("title"),
        }
    except Exception:
        return None


def _default_step_repository():
    from backend.config import settings

    if settings.supabase_url and settings.supabase_key:
        from backend.control_plane.supabase_repositories import SupabaseRunStepRepository

        return SupabaseRunStepRepository()
    from backend.control_plane.fakes import FakeRunStepRepository

    return FakeRunStepRepository()


def build_multi_phase_run_input(
    run_id: str,
    session_meta: dict[str, Any] | None,
) -> MultiPhaseRunInput | None:
    meta = session_meta or {}
    raw_step_specs = meta.get("temporal_step_specs") or _derive_step_specs_from_stack(meta)
    if not isinstance(raw_step_specs, dict) or not raw_step_specs:
        return None

    declared_order = [str(item).strip() for item in list(meta.get("temporal_phase_order") or []) if str(item).strip()]
    seen_phase_names: list[str] = []
    grouped: dict[str, list[str]] = {}

    for step_key, raw_spec in raw_step_specs.items():
        spec = dict(raw_spec or {})
        if spec.get("enabled", True) is False:
            continue
        phase_name = str(spec.get("phase") or "deploy").strip() or "deploy"
        grouped.setdefault(phase_name, []).append(str(step_key))
        if phase_name not in seen_phase_names:
            seen_phase_names.append(phase_name)

    if not grouped:
        return None

    ordered_phases: list[str] = []
    for phase_name in declared_order + list(_DEFAULT_PHASE_ORDER) + seen_phase_names:
        if phase_name and phase_name in grouped and phase_name not in ordered_phases:
            ordered_phases.append(phase_name)

    if not ordered_phases:
        return None

    timeout_seconds = int(meta.get("temporal_phase_timeout_seconds") or 7200)
    phases: list[PhaseRunInput] = []
    for index, phase_name in enumerate(ordered_phases):
        next_phase = ordered_phases[index + 1] if index + 1 < len(ordered_phases) else "complete"
        step_keys = list(grouped.get(phase_name) or [])
        phase_key_set = set(step_keys)
        step_dependencies = {
            step_key: [
                str(dep)
                for dep in list(dict(raw_step_specs.get(step_key) or {}).get("depends_on") or [])
                if str(dep) in phase_key_set
            ]
            for step_key in step_keys
        }
        phases.append(
            PhaseRunInput(
                run_id=run_id,
                phase_name=phase_name,
                next_phase=next_phase,
                step_keys=step_keys,
                step_dependencies=step_dependencies,
                timeout_seconds=timeout_seconds,
            )
        )
    return MultiPhaseRunInput(run_id=run_id, phases=phases)


async def execute_lane_attempt(
    raw_input: Any,
    *,
    get_orchestrator_fn: Callable[[], Any] | None = None,
    get_session_meta_fn: Callable[[str], dict[str, Any] | None] | None = None,
    step_repo: Any | None = None,
    publish_event_fn: Callable[[str, dict[str, Any]], Any] | None = None,
    heartbeat_fn: Callable[[dict[str, Any]], None] | None = None,
    is_cancelled_fn: Callable[[], bool] | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> dict[str, Any]:
    from backend.core.agent import AgentContext
    from backend.core.context_policy import RunContextPolicy
    from backend.core.session_store import merge_session_meta

    attempt_input = normalize_lane_attempt_input(raw_input)
    run_id = attempt_input.run_id
    step_key = attempt_input.step_key
    heartbeat_interval = heartbeat_interval_seconds
    if heartbeat_interval is None:
        heartbeat_interval = float(os.environ.get("TEMPORAL_ACTIVITY_HEARTBEAT_SECONDS", "20"))
    if get_orchestrator_fn is None:
        from backend.core.factory import get_orchestrator

        get_orchestrator_fn = get_orchestrator
    if get_session_meta_fn is None:
        from backend.core.session_store import get_session_meta

        get_session_meta_fn = get_session_meta
    if step_repo is None:
        step_repo = _default_step_repository()
    if publish_event_fn is None:
        from backend.core.events import publish

        async def publish_event_fn(session_id: str, payload: dict[str, Any]) -> Any:
            return await publish(session_id, payload, persist_durable=True)
    if is_cancelled_fn is None:
        is_cancelled_fn = lambda: False

    async def _publish(payload: dict[str, Any]) -> None:
        maybe = publish_event_fn(run_id, payload)
        if asyncio.iscoroutine(maybe):
            await maybe

    def _persist_latest_result(result_payload: dict[str, Any]) -> None:
        latest_specs = dict((get_session_meta_fn(run_id) or {}).get("temporal_step_specs") or {})
        latest_spec = dict(latest_specs.get(step_key) or {})
        latest_spec["latest_result"] = dict(result_payload or {})
        latest_spec["latest_result_at"] = datetime.now(timezone.utc).isoformat()
        latest_specs[step_key] = latest_spec
        merge_session_meta(run_id, temporal_step_specs=latest_specs)

    def _serialize_output_ref(result_payload: dict[str, Any]) -> str:
        return json.dumps(result_payload or {}, sort_keys=True, ensure_ascii=True, default=str)

    session_meta = get_session_meta_fn(run_id) or {}
    founder_id = str(session_meta.get("founder_id") or "").strip()
    goal = str(session_meta.get("goal") or "").strip()
    constraints = dict(session_meta.get("constraints") or {})
    step_specs = dict(session_meta.get("temporal_step_specs") or {})
    spec = dict(step_specs.get(step_key) or {})
    if not founder_id:
        raise ValueError(f"no founder_id found in session store for run_id={run_id}")
    if not goal:
        raise ValueError(f"no goal found in session store for run_id={run_id}")
    agent_name = str(spec.get("agent") or step_key).strip()
    instruction = str(spec.get("instruction") or goal).strip()
    if not instruction:
        raise ValueError(f"no instruction found for lane step={step_key!r} run_id={run_id}")
    orchestrator = get_orchestrator_fn()
    agent = getattr(orchestrator, "specialists", {}).get(agent_name)
    if agent is None:
        raise ValueError(f"unknown specialist {agent_name!r} for step {step_key!r}")

    started_at = datetime.now(timezone.utc)
    step = step_repo.create_attempt(RunStep(
        id=str(uuid.uuid4()),
        run_id=run_id,
        step_key=step_key,
        kind=str(spec.get("kind") or "agent"),
        agent=agent_name,
        phase=str(spec.get("phase") or "") or None,
        status="running",
        max_attempts=int(spec.get("max_attempts") or 1),
        started_at=started_at,
        heartbeat_at=started_at,
        input_ref=str(spec.get("input_ref") or "") or None,
    ))
    await _publish({
        "type": "agent_start",
        "agent": agent_name,
        "task_id": str(spec.get("task_id") or step_key),
        "step_id": step.id,
        "step_key": step_key,
        "attempt_number": step.attempt_number,
    })

    policy = RunContextPolicy(run_id, founder_id, constraints)
    shared = policy.build_agent_shared(
        base_shared=dict(spec.get("base_shared") or {}),
        agent_name=agent_name,
        task={
            "id": str(spec.get("task_id") or step_key),
            "agent": agent_name,
            "instruction": instruction,
            "depends_on": list(spec.get("depends_on") or []),
            "phase": spec.get("phase"),
            "expected_artifacts": list(spec.get("expected_artifacts") or []),
        },
        dep_results=dict(spec.get("dep_results") or {}),
        vault_context=str(spec.get("vault_context") or ""),
    )
    ctx = AgentContext(
        goal=instruction,
        founder_id=founder_id,
        session_id=run_id,
        # Action receipts reference astra_run_steps.id, not the planner's
        # logical task key (for example, t_web). Using the logical key here
        # caused every durable external action to fail its step FK constraint.
        # Keep the logical key in the task metadata; the execution context
        # carries the concrete attempt UUID for idempotency and receipts.
        task_id=step.id,
        shadow_mode=bool(constraints.get("shadow_mode", False)),
        unlimited_credits=bool(constraints.get("unlimited_credits", False)),
        shared=shared,
        dep_results=dict(spec.get("dep_results") or {}),
        vault_context=str(spec.get("vault_context") or ""),
    )
    if spec.get("task_brief") is not None:
        ctx.shared["task_brief"] = spec.get("task_brief")

    with step_attempt_span(
        run_id, step_key, agent_name, step.attempt_number,
        org_id=founder_id, queue_delay_seconds=_activity_queue_delay_seconds(),
    ):
        try:
            if heartbeat_fn:
                heartbeat_fn({"run_id": run_id, "step_key": step_key, "state": "starting"})
            task = asyncio.create_task(agent.run(ctx))
            while not task.done():
                heartbeat_at = datetime.now(timezone.utc)
                step_repo.update_fields(step.id, {"heartbeat_at": heartbeat_at})
                if heartbeat_fn:
                    heartbeat_fn({
                        "run_id": run_id,
                        "step_key": step_key,
                        "step_id": step.id,
                        "attempt_number": step.attempt_number,
                        "state": "running",
                    })
                if is_cancelled_fn():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    raise asyncio.CancelledError()
                await asyncio.sleep(heartbeat_interval)
            result = await task
            result_payload = result if isinstance(result, dict) else {"output": str(result)}
            completed_at = datetime.now(timezone.utc)
            _persist_latest_result(result_payload)
            step_repo.update_fields(step.id, {
                "status": "succeeded",
                "completed_at": completed_at,
                "heartbeat_at": completed_at,
                "output_ref": _serialize_output_ref(result_payload),
            })
            await _publish({
                "type": "agent_done",
                "agent": agent_name,
                "task_id": str(spec.get("task_id") or step_key),
                "step_id": step.id,
                "step_key": step_key,
                "attempt_number": step.attempt_number,
            })
            return LaneAttemptResult(
                run_id=run_id,
                step_key=step_key,
                step_id=step.id,
                agent=agent_name,
                status="succeeded",
                attempt_number=step.attempt_number,
                result=result_payload,
            ).__dict__
        except asyncio.CancelledError:
            completed_at = datetime.now(timezone.utc)
            step_repo.update_fields(step.id, {
                "status": "cancelled",
                "completed_at": completed_at,
                "heartbeat_at": completed_at,
                "error": "cancelled",
            })
            raise
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            step_repo.update_fields(step.id, {
                "status": "failed",
                "completed_at": completed_at,
                "heartbeat_at": completed_at,
                "error": str(exc)[:500],
            })
            await _publish({
                "type": "agent_error",
                "agent": agent_name,
                "task_id": str(spec.get("task_id") or step_key),
                "step_id": step.id,
                "step_key": step_key,
                "attempt_number": step.attempt_number,
                "error": str(exc)[:300],
            })
            raise


class _CancelledFence:
    """Adapts Temporal's cooperative-cancellation signal into the
    is_set()-style cancellation_fence deep_research()/browser_research.py
    already check at every meaningful checkpoint (per-model attempt,
    per-angle search loop -- see backend/tools/web_search.py). Outside a
    real activity context (direct/unit-test calls) this is always unset,
    matching every other Temporal-optional helper in this module."""

    def is_set(self) -> bool:
        try:
            from temporalio import activity

            return activity.is_cancelled()
        except Exception:
            return False


async def execute_deep_research(
    raw_input: Any,
    *,
    get_session_meta_fn: Callable[[str], dict[str, Any] | None] | None = None,
    heartbeat: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Wave 5.3: run web_search.deep_research() as a bounded, cancellable
    Temporal activity (invoked by DeepResearchWorkflow, see
    backend/control_plane/temporal/deep_research_workflow.py).

    Runs the (synchronous, network-bound) deep_research() call in a thread
    so the activity's asyncio event loop stays free to observe cancellation
    and heartbeat -- deep_research() itself already threads its own
    cancellation_fence through every model attempt and search angle
    (Wave 5.3's earlier cancellation-checkpoint work), so a real Temporal
    cancel request surfaces there within one checkpoint interval, not just
    at activity boundaries.
    """
    from backend.control_plane.temporal.contracts import DeepResearchInput, DeepResearchResult
    from backend.tools.research_schema import research_result_to_dict
    from backend.tools.web_search import deep_research

    input_ = raw_input if isinstance(raw_input, DeepResearchInput) else DeepResearchInput(**dict(raw_input or {}))

    if get_session_meta_fn is None:
        from backend.core.session_store import get_session_meta

        get_session_meta_fn = get_session_meta

    session_meta = get_session_meta_fn(input_.run_id) or {}
    queries = dict(session_meta.get("deep_research_queries") or {})
    spec = dict(queries.get(input_.query_id) or {})
    query = str(spec.get("query") or "").strip()
    focus = str(spec.get("focus") or "").strip()
    if not query:
        return dict(
            DeepResearchResult(
                run_id=input_.run_id, query_id=input_.query_id, status="error",
                error=f"no query found for query_id={input_.query_id!r} in session deep_research_queries",
            ).__dict__
        )

    fence = _CancelledFence()

    def _run() -> dict[str, Any]:
        return deep_research(query, focus=focus, cancellation_fence=fence, run_id=input_.run_id, step_id=input_.step_id)

    task = asyncio.create_task(asyncio.to_thread(_run))
    while not task.done():
        if heartbeat:
            try:
                heartbeat({"run_id": input_.run_id, "query_id": input_.query_id, "state": "researching"})
            except Exception:
                pass
        if fence.is_set():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return dict(
                DeepResearchResult(run_id=input_.run_id, query_id=input_.query_id, status="cancelled").__dict__
            )
        await asyncio.sleep(1)
    raw_result = await task
    # deep_research() itself checks `fence` at its own checkpoints (per-model
    # attempt, per-angle search) and can return {"error": "cancelled"} on its
    # own well before this loop's outer fence.is_set() check ever fires --
    # that's the fast/common cancellation path, not the fallback above.
    # Reporting it as "completed" with an empty structured result would hide
    # a real cancellation from whatever's watching DeepResearchResult.status.
    if raw_result.get("error") == "cancelled":
        return dict(
            DeepResearchResult(run_id=input_.run_id, query_id=input_.query_id, status="cancelled").__dict__
        )
    structured = raw_result.get("structured") or {}
    return dict(
        DeepResearchResult(
            run_id=input_.run_id, query_id=input_.query_id, status="completed", structured=structured,
        ).__dict__
    )


async def execute_verification(
    raw_input: Any,
    *,
    get_orchestrator_fn: Callable[[], Any] | None = None,
    get_session_meta_fn: Callable[[str], dict[str, Any] | None] | None = None,
    step_repo: Any | None = None,
    publish_event_fn: Callable[[str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    from backend.stacks import run_deep_verification, verify_task_artifacts

    verification_input = normalize_verification_input(raw_input)
    run_id = verification_input.run_id
    step_key = verification_input.step_key
    if get_orchestrator_fn is None:
        from backend.core.factory import get_orchestrator

        get_orchestrator_fn = get_orchestrator
    if get_session_meta_fn is None:
        from backend.core.session_store import get_session_meta

        get_session_meta_fn = get_session_meta
    if step_repo is None:
        step_repo = _default_step_repository()
    if publish_event_fn is None:
        from backend.core.events import publish

        async def publish_event_fn(session_id: str, payload: dict[str, Any]) -> Any:
            return await publish(session_id, payload, persist_durable=True)

    async def _publish(payload: dict[str, Any]) -> None:
        maybe = publish_event_fn(run_id, payload)
        if asyncio.iscoroutine(maybe):
            await maybe

    session_meta = get_session_meta_fn(run_id) or {}
    step_specs = dict(session_meta.get("temporal_step_specs") or {})
    spec = dict(step_specs.get(step_key) or {})
    agent_name = str(spec.get("agent") or step_key).strip()
    result_payload = dict(spec.get("latest_result") or {})
    task_payload = {
        "id": str(spec.get("task_id") or step_key),
        "agent": agent_name,
        "instruction": str(spec.get("instruction") or session_meta.get("goal") or ""),
        "expected_artifacts": list(spec.get("expected_artifacts") or []),
    }
    execution_blueprint = spec.get("execution_blueprint")
    if not result_payload:
        latest_attempt = step_repo.get_latest_attempt(run_id, step_key)
        if latest_attempt is not None and latest_attempt.output_ref:
            result_payload = {"summary": str(latest_attempt.output_ref)}
    base_verdict = verify_task_artifacts(task_payload, result_payload, execution_blueprint)
    orchestrator = get_orchestrator_fn()
    deep_verdict = await run_deep_verification(
        agent_name=agent_name,
        task=task_payload,
        result=result_payload,
        base_verdict=base_verdict,
        llm_call=orchestrator._verify_llm_call,
    )
    deep_verdict.setdefault("attempts", verification_input.attempt_number)
    for artifact_result in list(deep_verdict.get("artifacts") or []):
        artifact_key = str(artifact_result.get("artifact_key") or "")
        if not artifact_key:
            continue
        with artifact_span(run_id, artifact_key, artifact_key) as _artifact_span:
            _artifact_span.set_attribute("artifact.status", str(artifact_result.get("status") or ""))
    latest_attempt = step_repo.get_latest_attempt(run_id, step_key)
    if latest_attempt is not None:
        patch: dict[str, Any] = {"heartbeat_at": datetime.now(timezone.utc)}
        if deep_verdict.get("status") == "blocked":
            patch["error"] = deep_verdict.get("summary") or "artifact verification blocked"
        else:
            # Verification receipts belong in the verification event/output,
            # not in the step error column. Clearing a stale value also repairs
            # attempts created by the earlier projection bug.
            patch["error"] = None
        step_repo.update_fields(latest_attempt.id, patch)
    await _publish({
        "type": "stack_artifact_verification",
        "step_key": step_key,
        "agent": agent_name,
        "verification": deep_verdict,
    })
    return VerificationResult(
        run_id=run_id,
        step_key=step_key,
        agent=agent_name,
        status=str(deep_verdict.get("status") or "passed"),
        verification=deep_verdict,
    ).__dict__


async def execute_orchestrator_run(
    raw_input: Any,
    *,
    heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float | None = None,
    get_orchestrator_fn: Callable[[], Any] | None = None,
    get_session_meta_fn: Callable[[str], dict[str, Any] | None] | None = None,
    register_task_fn: Callable[..., Any] | None = None,
    request_kill_fn: Callable[[str], bool] | None = None,
    is_killed_fn: Callable[[str], bool] | None = None,
    observe_state_fn: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Run the legacy orchestrator against the pre-registered run/session ID."""
    from backend.core import cancellation

    run_input = normalize_run_input(raw_input)
    session_id = run_input.run_id
    heartbeat_interval = heartbeat_interval_seconds
    if heartbeat_interval is None:
        heartbeat_interval = float(os.environ.get("TEMPORAL_ACTIVITY_HEARTBEAT_SECONDS", "20"))

    if get_orchestrator_fn is None:
        from backend.core.factory import get_orchestrator

        get_orchestrator_fn = get_orchestrator
    if get_session_meta_fn is None:
        from backend.core.session_store import get_session_meta

        get_session_meta_fn = get_session_meta
    register_task_fn = register_task_fn or cancellation.register_task
    request_kill_fn = request_kill_fn or cancellation.request_kill
    is_killed_fn = is_killed_fn or cancellation.is_killed

    session_meta = get_session_meta_fn(session_id) or {}
    goal = str(session_meta.get("goal") or "").strip()
    founder_id = str(session_meta.get("founder_id") or "").strip()
    shadow_mode = bool(session_meta.get("shadow_mode")) or bool((session_meta.get("constraints") or {}).get("shadow_mode"))
    if not goal:
        raise ValueError(f"no goal found in session store for run_id={session_id}")
    if not founder_id:
        raise ValueError(f"no founder_id found in session store for run_id={session_id}")

    constraints = build_orchestrator_constraints(run_input, session_meta)
    orch = get_orchestrator_fn()

    if heartbeat:
        heartbeat(f"run={session_id} state=starting")
    if observe_state_fn:
        observe_state_fn({
            "workflow_status": "running",
            "active_step": "legacy_orchestrator",
            "waiting_approval": _extract_waiting_approval(session_id),
            "cancellation_requested": False,
            "shadow_mode": shadow_mode,
            "metadata": {"phase": "starting"},
        })

    logger.info(
        "Executing orchestrator for durable run=%s session=%s founder=%s goal_chars=%d",
        run_input.run_id,
        session_id,
        founder_id,
        len(goal),
    )

    orch_task = asyncio.create_task(
        orch.run(
            goal=goal,
            founder_id=founder_id,
            constraints=constraints,
            session_id=session_id,
        )
    )
    register_task_fn(session_id, orch_task, attempt_id=f"temporal-run:{session_id}")

    async def _heartbeat_loop() -> None:
        saw_cancel = False
        last_waiting_approval: Optional[dict[str, Any]] = None
        last_cancel_requested = False
        while not orch_task.done():
            latest_meta = get_session_meta_fn(session_id) or {}
            cancel_requested = is_killed_fn(session_id) or is_durable_cancel_requested(latest_meta)
            waiting_approval = _extract_waiting_approval(session_id)
            if cancel_requested and not saw_cancel:
                saw_cancel = True
                logger.info("Detected cancellation request for durable run=%s", session_id)
                request_kill_fn(session_id)
            if observe_state_fn and (
                cancel_requested != last_cancel_requested or waiting_approval != last_waiting_approval
            ):
                observe_state_fn({
                    "workflow_status": "cancelling" if cancel_requested else ("awaiting_approval" if waiting_approval else "running"),
                    "active_step": "legacy_orchestrator",
                    "waiting_approval": waiting_approval,
                    "cancellation_requested": bool(cancel_requested),
                    "shadow_mode": shadow_mode,
                    "metadata": {"phase": "heartbeat"},
                })
                last_cancel_requested = bool(cancel_requested)
                last_waiting_approval = waiting_approval
            if heartbeat:
                state = "cancelling" if cancel_requested else "running"
                heartbeat(f"run={session_id} state={state}")
            await asyncio.sleep(heartbeat_interval)

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        result = await orch_task
        if heartbeat:
            heartbeat(f"run={session_id} state=completed")
        if observe_state_fn:
            observe_state_fn({
                "workflow_status": "succeeded",
                "active_step": None,
                "waiting_approval": None,
                "cancellation_requested": False,
                "shadow_mode": shadow_mode,
                "metadata": {"phase": "completed"},
            })
        return {
            "session_id": session_id,
            "run_id": run_input.run_id,
            "status": "completed",
            "result": result if isinstance(result, dict) else {"output": str(result)[:1000]},
        }
    except asyncio.CancelledError:
        logger.info("Orchestrator cancelled for durable run=%s", session_id)
        request_kill_fn(session_id)
        if observe_state_fn:
            observe_state_fn({
                "workflow_status": "cancelled",
                "active_step": None,
                "waiting_approval": None,
                "cancellation_requested": True,
                "shadow_mode": shadow_mode,
                "metadata": {"phase": "cancelled"},
            })
        raise
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        cancellation.clear(session_id)

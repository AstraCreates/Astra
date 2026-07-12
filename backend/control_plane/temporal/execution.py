"""Pure execution helpers for Temporal-backed Astra runs."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from backend.control_plane.temporal.contracts import RunInput

logger = logging.getLogger(__name__)


def _coerce_run_input_values(raw_input: Any) -> dict[str, Any]:
    return {
        "run_id": str((raw_input.get("run_id") if isinstance(raw_input, dict) else getattr(raw_input, "run_id", "")) or ""),
        "goal": str((raw_input.get("goal") if isinstance(raw_input, dict) else getattr(raw_input, "goal", "")) or ""),
        "founder_id": str((raw_input.get("founder_id") if isinstance(raw_input, dict) else getattr(raw_input, "founder_id", "")) or ""),
        "company_id": str((raw_input.get("company_id") if isinstance(raw_input, dict) else getattr(raw_input, "company_id", "")) or ""),
        "constraints": dict((raw_input.get("constraints") if isinstance(raw_input, dict) else getattr(raw_input, "constraints", None)) or {}),
        "workspace_id": str((raw_input.get("workspace_id") if isinstance(raw_input, dict) else getattr(raw_input, "workspace_id", "")) or ""),
        "chapter_id": str((raw_input.get("chapter_id") if isinstance(raw_input, dict) else getattr(raw_input, "chapter_id", "")) or ""),
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


def build_orchestrator_constraints(
    run_input: RunInput,
    session_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = session_meta or {}
    constraints = dict(meta.get("constraints") or {})
    constraints.update(run_input.constraints or {})
    founder_id = str(meta.get("founder_id") or run_input.founder_id or "")
    company_id = str(run_input.company_id or meta.get("company_id") or founder_id)
    workspace_id = str(run_input.workspace_id or meta.get("workspace_id") or "")
    chapter_id = str(run_input.chapter_id or meta.get("chapter_id") or "")

    constraints["company_id"] = company_id
    if workspace_id:
        constraints["workspace_id"] = workspace_id
    if chapter_id:
        constraints["chapter_id"] = chapter_id
    return constraints


def is_durable_cancel_requested(session_meta: dict[str, Any] | None) -> bool:
    meta = session_meta or {}
    return str(meta.get("status") or "").lower() in {"cancelled", "canceled", "killed"}


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
    goal = str(run_input.goal or session_meta.get("goal") or "").strip()
    founder_id = str(session_meta.get("founder_id") or run_input.founder_id or "").strip()
    if not goal:
        raise ValueError(f"no goal found in session store for run_id={session_id}")
    if not founder_id:
        raise ValueError(f"no founder_id found in session store for run_id={session_id}")

    constraints = build_orchestrator_constraints(run_input, session_meta)
    orch = get_orchestrator_fn()

    if heartbeat:
        heartbeat(f"run={session_id} state=starting")

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
        while not orch_task.done():
            latest_meta = get_session_meta_fn(session_id) or {}
            cancel_requested = is_killed_fn(session_id) or is_durable_cancel_requested(latest_meta)
            if cancel_requested and not saw_cancel:
                saw_cancel = True
                logger.info("Detected cancellation request for durable run=%s", session_id)
                request_kill_fn(session_id)
            if heartbeat:
                state = "cancelling" if cancel_requested else "running"
                heartbeat(f"run={session_id} state={state}")
            await asyncio.sleep(heartbeat_interval)

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        result = await orch_task
        if heartbeat:
            heartbeat(f"run={session_id} state=completed")
        return {
            "session_id": session_id,
            "run_id": run_input.run_id,
            "status": "completed",
            "result": result if isinstance(result, dict) else {"output": str(result)[:1000]},
        }
    except asyncio.CancelledError:
        logger.info("Orchestrator cancelled for durable run=%s", session_id)
        request_kill_fn(session_id)
        raise
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        cancellation.clear(session_id)

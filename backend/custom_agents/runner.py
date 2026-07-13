"""Launch a custom agent as an orchestrated run.

Shared by the run-now API endpoint and the recurring scheduler. Uses the NORMAL
orchestrator path (not bypass_planner) so stack approval gates still apply — a
custom agent with send/post tools must not auto-fire irreversible actions.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)
_completion_watch_tasks: set[asyncio.Task[Any]] = set()


def _default_goal(spec: dict[str, Any]) -> str:
    """A goal string for runs where the founder didn't supply one. The agent's
    role prompt carries the real instructions; this just frames the run."""
    return (
        f"Execute your defined task as the \"{spec.get('name', 'custom')}\" agent. "
        "Follow your role instructions exactly and produce your expected output."
    )


async def _email_run_result(
    founder_id: str, session_id: str, agent_id: str, agent_label: str, company_name: str,
    error: str = "",
) -> None:
    """Best-effort: auto-email a formatted summary of every custom agent run —
    not just when there's a file deliverable. Custom agents are often unattended
    (scheduled at an interval), so there's no UI for a founder to click
    "email me a copy" — send the result to them automatically instead."""
    try:
        from backend.core.session_store import load_events
        from backend.workflow_state import build_session_state
        from backend.deliverables import (
            collect_result_attachment_paths,
            send_run_result_email,
            sync_deliverables_to_library,
        )

        events = load_events(session_id) or []
        state = build_session_state(session_id, events)
        agent_state = (state.get("agents") or {}).get(agent_id) or {}
        status = agent_state.get("status") or ("error" if error else "done")
        result = dict(agent_state.get("result") or {})
        if error and "error" not in result:
            result["error"] = error

        resolved_paths = collect_result_attachment_paths(result)

        sent = await asyncio.to_thread(
            send_run_result_email,
            founder_id=founder_id,
            agent_label=agent_label,
            company_name=company_name,
            status=status,
            result=result,
            attachment_paths=resolved_paths,
            session_id=session_id,
        )

        await asyncio.to_thread(
            sync_deliverables_to_library, founder_id, session_id, agent_label, result
        )
        if not sent.get("sent") and not sent.get("skipped"):
            logger.warning("run-result email failed session=%s: %s", session_id, sent)
    except Exception as exc:
        logger.warning("auto-email run result failed session=%s: %s", session_id, exc)


async def launch_custom_agent_run(
    *,
    founder_id: str,
    spec: dict[str, Any],
    goal: str | None = None,
    company_id: str | None = None,
    kind: str = "",
) -> str:
    """Start a background orchestrator run scoped to a single custom agent.

    Returns the new session_id immediately; the run continues in the background.
    """
    from backend.api.schemas import RunCreateRequest
    from backend.control_plane.start_run import start_run

    agent_id = spec["id"]
    resolved_company = company_id or spec.get("company_id") or founder_id
    run_goal = (goal or "").strip() or _default_goal(spec)

    # Unlimited credits for scale/beta plans, mirroring submit_goal.
    unlimited = False
    try:
        from backend.accounts import get_or_create_org
        plan = (get_or_create_org(founder_id) or {}).get("plan", "starter")
        unlimited = plan in ("scale", "beta")
    except Exception:
        pass

    # Pull the pinned company name so the orchestrator never invents one.
    _company_name = ""
    try:
        from backend.missions.company_goal import get_company_name as _gcn
        _company_name = _gcn(founder_id, resolved_company) or ""
    except Exception:
        pass

    constraints: dict[str, Any] = {
        "agents": [agent_id],
        "stack_id": "custom",
        "bypass_planner": True,
        "company_id": resolved_company,
        "company_name": _company_name,
        "unlimited_credits": unlimited,
        "custom_agent_id": agent_id,
    }
    result = await start_run(
        RunCreateRequest(
            founder_id=founder_id,
            instruction=run_goal,
            stack_id="custom",
            constraints=constraints,
            company_id=resolved_company,
            workspace_id=resolved_company,
        ),
        request=None,
    )
    session_id = result.session_id
    agent_label = str(spec.get("name") or agent_id)

    async def _watch_completion() -> None:
        from backend.core.session_store import get_session_meta

        error = ""
        try:
            while True:
                await asyncio.sleep(2)
                meta = await asyncio.to_thread(get_session_meta, session_id)
                status = str((meta or {}).get("status") or "")
                if status in {"done", "error", "killed"}:
                    if status == "error":
                        error = str((meta or {}).get("last_error") or "")
                    break
            await _email_run_result(founder_id, session_id, agent_id, agent_label, _company_name, error=error)
        except Exception as exc:
            logger.warning("custom-agent completion watch failed session=%s: %s", session_id, exc)

    watch_task = asyncio.create_task(_watch_completion())
    _completion_watch_tasks.add(watch_task)
    watch_task.add_done_callback(_completion_watch_tasks.discard)
    logger.info("custom_agent run launched via StartRun: agent=%s session=%s", agent_id, session_id)
    return session_id

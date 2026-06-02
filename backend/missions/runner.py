"""Mission runner — executes a single mission run end-to-end.

A mission run:
  1. Loads the mission from the store.
  2. Builds a context string: goal + objectives + last 5 progress notes.
  3. Gets the singleton Orchestrator via get_orchestrator().
  4. Generates a unique session_id for this run.
  5. Runs the relevant department agent with the context injected as the goal.
  6. Writes a progress note back to the store with the result summary.
  7. Updates last_run_at, run_count, and total_cost_usd.

Public API
----------
    result = await run_mission(mission_id)
    # result: {success: bool, session_id: str, summary: str, cost_usd: float}
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Department → specialist agent name
_DEPARTMENT_AGENT: dict[str, str] = {
    "research":  "research",
    "marketing": "marketing_content",
    "sales":     "sales_pipeline",
    "technical": "technical_scaffold",
    "legal":     "legal_docs",
    "ops":       "ops",
    "finance":   "finance_model",
}


def _build_context(mission: dict) -> str:
    """Compose the goal string injected as the agent's mission context."""
    parts: list[str] = []

    parts.append(f"MISSION: {mission['name']}")
    parts.append(f"DEPARTMENT: {mission['department'].upper()}")
    parts.append(f"\nGOAL:\n{mission['goal']}")

    primary_metric = mission.get("primary_metric", "")
    if primary_metric:
        parts.append(f"\nPRIMARY METRIC TO MOVE: {primary_metric}")

    objectives: list[str] = mission.get("objectives") or []
    if objectives:
        obj_lines = "\n".join(f"  {i + 1}. {obj}" for i, obj in enumerate(objectives))
        parts.append(f"\nOBJECTIVES:\n{obj_lines}")

    notes: list[dict] = mission.get("progress_notes") or []
    recent = notes[-5:]  # last 5 notes
    if recent:
        note_lines: list[str] = []
        for n in recent:
            ts = n.get("timestamp", "")
            text = n.get("note", "")
            note_lines.append(f"  [{ts}] {text}")
        parts.append("\nPRIOR PROGRESS (most recent 5 runs):\n" + "\n".join(note_lines))
    else:
        parts.append("\nPRIOR PROGRESS: This is the first run — no prior progress notes.")

    parts.append(
        "\nYour task: make meaningful progress toward the mission goal. "
        "Produce concrete outputs (documents, analysis, code, outreach, etc.) "
        "and include a clear summary of what was accomplished in this run."
    )

    return "\n".join(parts)


def _extract_summary(result: Any, agent_name: str) -> str:
    """Pull the best available summary text out of an agent result dict."""
    if not isinstance(result, dict):
        return str(result)[:500]

    for key in ("summary", "output_summary", "formatted_text", "report", "text"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:1000]

    # Fallback: concatenate short string fields
    parts: list[str] = []
    for k, v in result.items():
        if k in ("agent", "error") or not isinstance(v, str):
            continue
        if len(v) > 10:
            parts.append(f"{k}: {v[:200]}")
        if len(parts) >= 5:
            break
    return "; ".join(parts)[:1000] if parts else f"{agent_name} run completed (no summary returned)"


def _estimate_cost(result: Any) -> float:
    """Extract or estimate the USD cost of this run from the result dict.

    Real cost tracking would require token counts from the LLM response.
    For now we check if the agent stored a cost key, otherwise return 0.0.
    The scheduler can update this with real billing data when available.
    """
    if not isinstance(result, dict):
        return 0.0
    return float(result.get("cost_usd") or result.get("cost") or 0.0)


async def run_mission(mission_id: str) -> dict[str, Any]:
    """Execute a single mission run.

    Args:
        mission_id: UUID of the mission to run.

    Returns:
        A dict with keys:
            success   (bool)  — True if the agent ran without raising.
            session_id (str)  — The session created for this run.
            summary   (str)   — Human-readable summary of what the agent did.
            cost_usd  (float) — Estimated USD cost of this run.
    """
    # ── 1. Load mission ────────────────────────────────────────────────────────
    from backend.missions.store import (
        append_progress_note,
        get_mission,
        increment_run_count,
    )

    session_id = uuid.uuid4().hex[:12]

    try:
        mission = get_mission(mission_id)
    except Exception as exc:
        logger.error("run_mission: failed to load mission %s: %s", mission_id, exc)
        return {"success": False, "session_id": session_id, "summary": f"Load error: {exc}", "cost_usd": 0.0}

    if mission is None:
        logger.error("run_mission: mission %s not found", mission_id)
        return {"success": False, "session_id": session_id, "summary": "Mission not found", "cost_usd": 0.0}

    founder_id: str = mission["founder_id"]
    department: str = mission["department"]
    mission_name: str = mission.get("name", mission_id)

    logger.info(
        "run_mission: START mission=%s name=%r department=%s founder=%s session=%s",
        mission_id, mission_name, department, founder_id, session_id,
    )

    # ── 2. Resolve the target agent ────────────────────────────────────────────
    agent_name = _DEPARTMENT_AGENT.get(department)
    if not agent_name:
        msg = f"No agent mapped for department '{department}'"
        logger.error("run_mission: %s (mission=%s)", msg, mission_id)
        return {"success": False, "session_id": session_id, "summary": msg, "cost_usd": 0.0}

    # ── 3. Build context string ────────────────────────────────────────────────
    context_goal = _build_context(mission)

    # ── 4. Get orchestrator and locate the specialist ──────────────────────────
    try:
        from backend.core.factory import get_orchestrator
        orch = get_orchestrator()
    except Exception as exc:
        logger.error("run_mission: orchestrator init failed: %s", exc, exc_info=True)
        return {"success": False, "session_id": session_id, "summary": f"Orchestrator error: {exc}", "cost_usd": 0.0}

    agent = orch.specialists.get(agent_name)
    if agent is None:
        msg = f"Specialist '{agent_name}' not found in orchestrator"
        logger.error("run_mission: %s (mission=%s)", msg, mission_id)
        return {"success": False, "session_id": session_id, "summary": msg, "cost_usd": 0.0}

    # ── 5. Register session in the session store ───────────────────────────────
    try:
        from backend.core.session_store import register_session
        register_session(
            session_id=session_id,
            founder_id=founder_id,
            goal=context_goal,
            agents=[agent_name],
        )
    except Exception as exc:
        # Non-fatal — continue even if session registration fails
        logger.warning("run_mission: session registration failed: %s", exc)

    # ── 6. Run the agent ───────────────────────────────────────────────────────
    result: Any = None
    success = False
    summary = ""
    cost_usd = 0.0

    try:
        from backend.core.agent import AgentContext

        # Load any prior vault notes for additional context
        vault_context_text = ""
        try:
            from backend.tools.obsidian_logger import format_vault_context
            vault_context_text = await asyncio.wait_for(
                asyncio.to_thread(format_vault_context, agent_name, 5, founder_id),
                timeout=8.0,
            )
        except Exception as _ve:
            logger.debug("run_mission: vault context load skipped: %s", _ve)

        ctx = AgentContext(
            goal=context_goal,
            founder_id=founder_id,
            session_id=session_id,
            shared={
                "mission_id": mission_id,
                "mission_name": mission_name,
                "department": department,
                "is_mission_run": True,
                "prior_vault_notes": vault_context_text,
            },
        )

        result = await agent.run(ctx)
        success = True

        # Auto-log to Obsidian (best-effort)
        try:
            from backend.tools.obsidian_logger import auto_log_if_missing
            await asyncio.to_thread(auto_log_if_missing, agent_name, session_id, result, founder_id)
        except Exception as _ole:
            logger.debug("run_mission: obsidian auto-log skipped: %s", _ole)

    except Exception as exc:
        logger.error(
            "run_mission: agent %s raised during mission %s: %s",
            agent_name, mission_id, exc, exc_info=True,
        )
        summary = f"Agent error: {exc}"
        result = {"error": str(exc)}

    # ── 7. Extract summary and cost ───────────────────────────────────────────
    if success:
        summary = _extract_summary(result, agent_name)
        cost_usd = _estimate_cost(result)

    # ── 8. Write progress note back to the store ───────────────────────────────
    try:
        append_progress_note(
            mission_id=mission_id,
            note=summary if summary else "(no summary)",
            run_id=session_id,
        )
    except Exception as exc:
        logger.warning("run_mission: failed to append progress note for %s: %s", mission_id, exc)

    # ── 9. Update run counters (last_run_at, run_count, total_cost_usd) ────────
    try:
        increment_run_count(mission_id=mission_id, cost_usd=cost_usd)
    except Exception as exc:
        logger.warning("run_mission: failed to increment run count for %s: %s", mission_id, exc)

    logger.info(
        "run_mission: END mission=%s session=%s success=%s cost_usd=%.4f summary=%r",
        mission_id, session_id, success, cost_usd, summary[:120],
    )

    return {
        "success": success,
        "session_id": session_id,
        "summary": summary,
        "cost_usd": cost_usd,
    }

"""Optional background reviewer that creates draft skill proposals only."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.runtime.rollout import enabled as runtime_feature_enabled
from backend.skills.proposals import create_proposal

logger = logging.getLogger(__name__)


async def review_run_for_skill_proposal(
    *, founder_id: str, specialist: str, session_id: str,
    goal: str, result: dict[str, Any],
) -> dict[str, Any] | None:
    if not runtime_feature_enabled("skill_review", founder_id) or not founder_id or not isinstance(result, dict):
        return None
    prompt = (
        "Review this completed agent run for one durable workflow improvement. "
        "Do not include secrets, transient setup failures, or unverified facts. "
        "Return JSON only: {\"propose\": bool, \"evidence\": str, "
        "\"proposed_change\": str, \"risk_level\": \"low|medium|high\"}.\n\n"
        f"Specialist: {specialist}\nGoal: {goal}\n"
        f"Result: {json.dumps(result, default=str)[:12000]}"
    )
    try:
        from backend.tools._llm import generate
        raw = await asyncio.to_thread(generate, prompt, max_tokens=1200, model="small")
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start:end + 1]) if start >= 0 and end > start else {}
        if not parsed.get("propose"):
            return None
        return create_proposal(
            founder_id=founder_id,
            specialist=specialist,
            source_session=session_id,
            evidence=str(parsed.get("evidence", "")),
            proposed_change=str(parsed.get("proposed_change", "")),
            risk_level=str(parsed.get("risk_level", "low")),
            reviewer="background_agent",
        )
    except Exception as exc:
        logger.warning("Skill review failed for %s/%s: %s", session_id, specialist, exc)
        return None

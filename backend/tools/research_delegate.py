"""delegate_research_task — technical research via ling-backed synthesis."""
from __future__ import annotations

from typing import Any


async def delegate_research_task(
    target: str,
    questions: list[str],
    session_id: str = "",
    founder_id: str = "",
) -> dict[str, Any]:
    """Spawn a deep-research call to look up technical information for a build.

    Uses the shared lightweight ling research model for synthesis and returns
    findings in the same contract technical agents already consume.

    Args:
        target:    Topic to research, e.g. "Supabase RLS with Next.js App Router"
        questions: Specific questions, e.g. ["correct SSR cookie pattern", "middleware example"]
        session_id/founder_id: auto-injected by agent runtime — do not pass.
    """
    from backend.core.llm_cache import openrouter_extra_body
    from backend.core.llm_client import get_async_or_client
    from backend.config import settings

    prompt = (
        f"Research target: {target}\n\n"
        f"Answer ALL of the following questions with specific, actionable findings "
        f"including code examples where relevant:\n"
        + "\n".join(f"- {q}" for q in questions)
    )

    model = getattr(settings, "or_light_model", "") or "inclusionai/ling-2.6-flash"
    client = get_async_or_client(settings.openrouter_base_url, timeout=300.0)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        extra_body=openrouter_extra_body(model),
        timeout=300.0,
    )
    msg = ((getattr(resp, "choices", None) or [{}])[0]).message if getattr(resp, "choices", None) else None
    return {
        "target": target,
        "findings": getattr(msg, "content", "") or "",
        "annotations": getattr(msg, "annotations", None) or [],
        "usage": getattr(resp, "usage", None) or {},
    }

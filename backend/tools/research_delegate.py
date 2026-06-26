"""delegate_research_task — deep research for technical agents via o4-mini-deep-research."""
from __future__ import annotations

from typing import Any


async def delegate_research_task(
    target: str,
    questions: list[str],
    session_id: str = "",
    founder_id: str = "",
) -> dict[str, Any]:
    """Spawn a deep-research call to look up technical information for a build.

    Uses openai/o4-mini-deep-research (built-in web search) — no manual
    search/fetch orchestration needed. Returns findings with source citations.

    Args:
        target:    Topic to research, e.g. "Supabase RLS with Next.js App Router"
        questions: Specific questions, e.g. ["correct SSR cookie pattern", "middleware example"]
        session_id/founder_id: auto-injected by agent runtime — do not pass.
    """
    import httpx
    from backend.core.key_rotator import get_openrouter_key
    from backend.config import settings

    prompt = (
        f"Research target: {target}\n\n"
        f"Answer ALL of the following questions with specific, actionable findings "
        f"including code examples where relevant:\n"
        + "\n".join(f"- {q}" for q in questions)
    )

    key = get_openrouter_key() or settings.agent_model_api_key
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "perplexity/sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "provider": {"allow_fallbacks": False},
                "usage": {"include": True},
            },
        )
    data = r.json()
    if "error" in data:
        return {"error": data["error"], "target": target}
    msg = ((data.get("choices") or [{}])[0]).get("message") or {}
    return {
        "target": target,
        "findings": msg.get("content") or "",
        "annotations": msg.get("annotations") or [],
        "usage": data.get("usage") or {},
    }

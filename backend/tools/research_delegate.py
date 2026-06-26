"""delegate_research_task — lets technical/web agents spawn a focused research sub-agent."""
from __future__ import annotations

import uuid
from typing import Any


async def delegate_research_task(
    target: str,
    questions: list[str],
    session_id: str = "",
    founder_id: str = "",
) -> dict[str, Any]:
    """Spawn a focused research sub-agent to look up technical information.

    Use when you need specific docs, API references, or library patterns before
    writing code. The sub-agent does targeted web search and returns findings.

    Args:
        target:    Topic to research, e.g. "Supabase RLS with Next.js App Router"
        questions: List of specific questions, e.g. ["How to enable RLS?", "Auth session pattern?"]
        session_id/founder_id: auto-injected by the agent runtime — do not pass.
    """
    from backend.core.agent import Agent, AgentContext
    from backend.core.key_rotator import get_openrouter_key
    from backend.config import settings
    from backend.tools.web_search import batch_search
    from backend.tools.page_fetcher import fetch_and_read

    goal = (
        f"Research target: {target}\n\n"
        f"Answer ALL of these questions with specific, actionable findings:\n"
        + "\n".join(f"- {q}" for q in questions)
        + "\n\nReturn a JSON object: {\"findings\": [{\"question\": str, \"answer\": str, "
        "\"sources\": [url, ...]}, ...], \"summary\": str}"
    )

    agent = Agent(
        name=f"research_delegate:{uuid.uuid4().hex[:8]}",
        role=(
            "You are a focused technical research agent. You look up specific API docs, "
            "library patterns, and code examples. Use batch_search to find relevant pages, "
            "then fetch_and_read for the most relevant ones. Be concise and precise — "
            "return only what the caller needs to write correct code. "
            "Output JSON only: {\"findings\": [{\"question\", \"answer\", \"sources\"}], \"summary\"}."
        ),
        tools={"batch_search": batch_search, "fetch_and_read": fetch_and_read},
        model=settings.or_light_model,
        model_base_url=settings.openrouter_base_url,
        model_api_key=get_openrouter_key() or settings.agent_model_api_key,
        max_iterations=15,
    )

    ctx = AgentContext(
        goal=goal,
        founder_id=founder_id,
        session_id=session_id or "research_delegate",
        task_id=f"rd_{uuid.uuid4().hex[:12]}",
        delegation_depth=1,  # prevent further sub-delegation
    )

    return await agent.run(ctx)

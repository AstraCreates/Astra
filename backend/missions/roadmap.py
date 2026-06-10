"""Personalized roadmap generator — Now/Next/Later goals from genome."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_roadmap(
    founder_id: str,
    company_id: str | None = None,
    genome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate personalized roadmap from company genome using LLM.

    Returns structure with 'now', 'next', 'later' goal lists, each with
    title, description, success_criteria, kpis, estimated_credits.
    Idempotent: if roadmap already exists, returns it unchanged.
    """
    from backend.missions.company_goal import get_company_goal
    from backend.genome.store import get_genome
    from backend.tools._llm import generate

    resolved_company = company_id or founder_id

    # Check if roadmap already exists (idempotent)
    existing = get_company_goal(founder_id, resolved_company)
    if existing and existing.get("goals"):
        logger.info("Roadmap already exists for %s/%s", founder_id, resolved_company)
        return {"ok": True, "reason": "already_exists"}

    # Load genome for context
    if not genome:
        genome = get_genome(founder_id, resolved_company) or {}

    # Extract key facts from genome sections
    stage = genome.get("sections", {}).get("stage", {}).get("value", "unknown")
    product = genome.get("sections", {}).get("product", {}).get("value", "")
    icp = genome.get("sections", {}).get("icp", {}).get("value", "")
    metrics = genome.get("sections", {}).get("metrics", {}).get("value", "")

    prompt = f"""You are a startup advisor. Based on the company profile below, generate a personalized 90-day roadmap with Now/Next/Later goals.

Company Profile:
- Stage: {stage}
- Product: {product}
- ICP: {icp}
- Key Metrics: {metrics}

For each goal, provide:
- title (short, action-oriented)
- description (1-2 sentences)
- success_criteria (list of 2-3 measurable criteria)
- kpis (list of 2-3 KPIs to track)
- estimated_credits (1-50, relative effort estimate)

Return ONLY a JSON object with this structure:
{{
  "now": [
    {{"title": "...", "description": "...", "success_criteria": [...], "kpis": [...], "estimated_credits": 5}},
    ...
  ],
  "next": [...],
  "later": [...]
}}

Now goals are 1-2 weeks, Next are 2-4 weeks, Later are after that."""

    try:
        response = generate(prompt, max_tokens=1500, model="large", temperature=0.7)

        # Extract JSON from response
        import re
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            logger.warning("No JSON in roadmap response: %s", response[:200])
            return {"ok": False, "error": "invalid_response"}

        roadmap = json.loads(match.group(0))
        return {"ok": True, "roadmap": roadmap}

    except Exception as e:
        logger.error("Roadmap generation failed: %s", e)
        return {"ok": False, "error": str(e)}


def apply_roadmap(
    founder_id: str,
    company_id: str | None = None,
    roadmap: dict[str, Any] | None = None,
) -> bool:
    """Convert roadmap into company_goal goals with bucket + success_criteria.

    Creates goals with bucket: "now"|"next"|"later", persists them.
    Idempotent: if goals already exist, skips.
    """
    from backend.missions.company_goal import get_company_goal, upsert_company_goal
    import uuid

    resolved_company = company_id or founder_id

    existing = get_company_goal(founder_id, resolved_company)
    if existing and existing.get("goals"):
        logger.info("Goals already exist for %s/%s", founder_id, resolved_company)
        return True

    if not roadmap:
        result = generate_roadmap(founder_id, resolved_company)
        if not result.get("ok"):
            return False
        roadmap = result.get("roadmap", {})

    # Convert roadmap to goal objects with bucket field
    goals = []
    for bucket in ["now", "next", "later"]:
        for item in roadmap.get(bucket, []):
            goal = {
                "id": str(uuid.uuid4()),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "bucket": bucket,
                "status": "proposed",  # Founder approves/rejects
                "success_criteria": item.get("success_criteria", []),
                "kpis": item.get("kpis", []),
                "tasks": [],
                "created_at": None,
                "updated_at": None,
                "credits_estimated": item.get("estimated_credits", 10),
            }
            goals.append(goal)

    # Persist goals into company_goal
    try:
        company_goal = get_company_goal(founder_id, resolved_company) or {
            "founder_id": founder_id,
            "company_id": resolved_company,
            "north_star": "",
            "company_goal": "",
            "status": "operating",
            "goals": [],
        }
        company_goal["goals"] = goals
        company_goal["current_goal_id"] = goals[0]["id"] if goals else ""

        upsert_company_goal(
            founder_id,
            north_star=company_goal.get("north_star", ""),
            company_goal=company_goal.get("company_goal", ""),
            source_session_id=company_goal.get("source_session_id", "roadmap_v1"),
            status=company_goal.get("status", "operating"),
            company_id=resolved_company,
        )

        # Update with goals
        from backend.missions.company_goal import _save
        company_goal_updated = _save(company_goal)

        logger.info("Applied roadmap for %s/%s: %d goals", founder_id, resolved_company, len(goals))
        return True

    except Exception as e:
        logger.error("Failed to apply roadmap: %s", e)
        return False

"""Team Map — score departments and identify capability gaps."""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.genome.store import get_genome
from backend.outcomes.store import list_outcomes
from backend.connector_coverage import build_connector_coverage
from backend.missions.company_goal import get_company_goal

logger = logging.getLogger(__name__)

DEPARTMENTS = [
    "Sales",
    "Marketing",
    "Product",
    "Engineering",
    "Operations",
    "Finance",
    "Legal",
    "Support",
    "Data",
]


def score_team_map(
    founder_id: str,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Score each department on capability maturity (0-100).

    Scoring inputs:
    - Genome completeness for domain (% of relevant facts filled)
    - Outcome activity (executions in past 30 days per dept tags)
    - Connected integrations (# of dept-relevant tools connected)
    - Goal coverage (% of dept goals completed/in-progress)
    """
    resolved_company = company_id or founder_id

    scores = {}

    # Load company data
    try:
        genome = get_genome(founder_id, resolved_company) or {}
        goals = get_company_goal(founder_id, resolved_company) or {}
        outcomes = list_outcomes(founder_id, resolved_company)
        coverage = build_connector_coverage(founder_id) or {}
    except Exception as e:
        logger.warning("Failed to load company data for team map: %s", e)
        return {"ok": False, "error": str(e)}

    # Genome section keywords per department
    dept_genome_keys = {
        "Sales": ["icp", "positioning", "pricing", "competitors", "objections"],
        "Marketing": [
            "brand_voice",
            "positioning",
            "personas",
            "metrics",
            "offers",
        ],
        "Product": ["product", "icp", "personas", "metrics", "roadmap"],
        "Engineering": ["product", "metrics", "decisions", "risks"],
        "Operations": ["metrics", "risks", "decisions", "goals"],
        "Finance": ["metrics", "pricing", "decisions", "risks"],
        "Legal": ["brand_voice", "risks", "decisions"],
        "Support": ["brand_voice", "icp", "personas", "objections"],
        "Data": ["metrics", "data", "decisions"],
    }

    # Dept-specific integration keywords
    dept_integrations = {
        "Sales": [
            "apollo",
            "hunter",
            "salesforce",
            "pipedrive",
            "hubspot",
        ],
        "Marketing": ["hubspot", "mailchimp", "segment", "stripe"],
        "Product": ["github", "jira", "linear"],
        "Engineering": ["github", "jira", "linear", "datadog"],
        "Operations": ["slack", "asana", "linear", "stripe"],
        "Finance": ["stripe", "quickbooks", "xero"],
        "Legal": ["stripe", "docusign"],
        "Support": ["zendesk", "intercom", "hubspot"],
        "Data": ["slack", "segment", "datadog", "stripe"],
    }

    # Score each department
    for dept in DEPARTMENTS:
        score_components = {}

        # Genome completeness: % of relevant keys with values
        genome_keys = dept_genome_keys.get(dept, [])
        if genome_keys:
            sections = genome.get("sections", {})
            filled = sum(
                1
                for key in genome_keys
                if key in sections and sections[key].get("value")
            )
            score_components["genome"] = int(100 * filled / len(genome_keys))
        else:
            score_components["genome"] = 50

        # Outcome activity: count executed outcomes in past 30 days tagged with dept
        dept_outcomes = [
            o
            for o in outcomes
            if o.get("state") == "executed"
            and dept.lower() in o.get("metric", "").lower()
        ]
        score_components["activity"] = min(100, len(dept_outcomes) * 10)

        # Integration coverage: % of dept integrations connected
        dept_tools = dept_integrations.get(dept, [])
        if dept_tools:
            connected = sum(
                1
                for tool in dept_tools
                if coverage.get(tool, {}).get("status") == "connected"
            )
            score_components["integrations"] = int(
                100 * connected / len(dept_tools)
            )
        else:
            score_components["integrations"] = 50

        # Goal coverage: % of dept goals completed
        dept_goals = [
            g
            for g in goals.get("goals", [])
            if dept.lower() in g.get("title", "").lower()
            or dept.lower() in g.get("description", "").lower()
        ]
        completed_goals = sum(1 for g in dept_goals if g.get("status") == "approved")
        if dept_goals:
            score_components["goals"] = int(100 * completed_goals / len(dept_goals))
        else:
            score_components["goals"] = 50

        # Weighted average: genome 30%, activity 20%, integrations 25%, goals 25%
        overall_score = int(
            0.3 * score_components["genome"]
            + 0.2 * score_components["activity"]
            + 0.25 * score_components["integrations"]
            + 0.25 * score_components["goals"]
        )

        scores[dept] = {
            "overall": overall_score,
            "components": score_components,
            "gaps": _identify_gaps(dept, score_components),
        }

    return {"ok": True, "team_map": scores}


def _identify_gaps(dept: str, components: dict[str, int]) -> list[str]:
    """Identify capability gaps from component scores."""
    gaps = []

    if components.get("genome", 0) < 40:
        gaps.append(f"{dept} knowledge incomplete — run discovery session")

    if components.get("activity", 0) < 20:
        gaps.append(f"{dept} inactive — assign goals to drive engagement")

    if components.get("integrations", 0) < 50:
        gaps.append(f"{dept} missing key tools — connect integrations")

    if components.get("goals", 0) < 30:
        gaps.append(f"{dept} goals not progressing — review blockers")

    return gaps


def create_goal_from_gap(
    founder_id: str,
    company_id: str | None = None,
    dept: str = "",
    gap: str = "",
) -> dict[str, Any]:
    """Convert gap into a company_goal in 'next' bucket.

    LLM generates actionable goal from dept + gap description.
    """
    from backend.tools._llm import generate
    from backend.missions.company_goal import get_company_goal, _save
    import uuid

    resolved_company = company_id or founder_id

    prompt = f"""You are a startup advisor. Convert this capability gap into an actionable goal.

Department: {dept}
Gap: {gap}

Generate a short, action-oriented goal with:
- title (5-10 words)
- description (1-2 sentences)
- success_criteria (list of 2-3 measurable items)

Return ONLY valid JSON:
{{"title": "...", "description": "...", "success_criteria": [...]}}"""

    try:
        response = generate(prompt, max_tokens=300, temperature=0.7)

        # Extract JSON (resilient to truncation/prose wrappers).
        from backend.core.json_extract import extract_json
        goal_data = extract_json(response, prefer_keys=("title", "description"))
        if not goal_data:
            return {"ok": False, "error": "invalid_llm_response"}

        # Add to company_goal "next" bucket
        company_goal = get_company_goal(founder_id, resolved_company) or {
            "founder_id": founder_id,
            "company_id": resolved_company,
            "north_star": "",
            "company_goal": "",
            "status": "operating",
            "goals": [],
        }

        new_goal = {
            "id": str(uuid.uuid4()),
            "title": goal_data.get("title", gap),
            "description": goal_data.get("description", ""),
            "bucket": "next",
            "status": "proposed",
            "success_criteria": goal_data.get("success_criteria", []),
            "kpis": [],
            "tasks": [],
            "created_at": None,
            "updated_at": None,
            "credits_estimated": 20,
        }

        company_goal["goals"].append(new_goal)
        _save(company_goal)

        logger.info("Created goal from gap: %s", new_goal["title"])
        return {"ok": True, "goal": new_goal}

    except Exception as e:
        logger.error("Failed to create goal from gap: %s", e)
        return {"ok": False, "error": str(e)}

"""Stack Compiler.

Maps a plain business outcome to the most appropriate Agent Stack template.
The first version is deterministic and inspectable; an LLM/router can sit on
top later, but this gives the product a concrete "goal -> deployable stack"
primitive now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.stacks.templates import AgentStackTemplate, get_stack_template


@dataclass(frozen=True)
class StackRecommendation:
    stack: AgentStackTemplate
    confidence: float
    reason: str
    matched_signals: list[str]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "stack": self.stack.to_public_dict(),
            "confidence": self.confidence,
            "reason": self.reason,
            "matched_signals": self.matched_signals,
        }


_STACK_SIGNALS: dict[str, tuple[str, ...]] = {
    "idea_to_revenue": (
        "startup idea", "from zero", "new company", "launch a company", "waitlist",
        "landing page", "pitch deck", "investor", "mvp", "founder", "validate",
        "pricing", "icp", "competitor", "go to market", "go-to-market",
    ),
    "sales": (
        "sales", "pipeline", "leads", "prospects", "crm", "outbound", "cold email",
        "revenue", "book meetings", "qualified", "deal", "close", "follow up",
    ),
    "marketing": (
        "marketing", "campaign", "content", "seo", "ads", "paid", "launch campaign",
        "social", "email newsletter", "creative", "brand awareness", "growth",
    ),
    "founder_ops": (
        "ops", "operating", "weekly", "investor update", "board", "decision log",
        "priorities", "metrics", "cadence", "company brain", "tasks", "what did",
    ),
    "support": (
        "support", "tickets", "customer service", "helpdesk", "knowledge base",
        "sla", "escalation", "macros", "customer questions", "bugs",
    ),
    "product": (
        "product", "roadmap", "spec", "requirements", "feature", "release",
        "sprint", "user stories", "figma", "technical spec", "architecture",
    ),
}


_STACK_REASONS: dict[str, str] = {
    "idea_to_revenue": "The goal reads like a founder/company creation outcome, so Astra should deploy the company-foundation stack.",
    "sales": "The goal centers on pipeline, prospects, CRM, or revenue execution, so Astra should deploy the sales operating stack.",
    "marketing": "The goal centers on campaigns, channels, content, or paid/social growth, so Astra should deploy the marketing stack.",
    "founder_ops": "The goal centers on company operating cadence, internal context, decisions, or founder workflows, so Astra should deploy the founder ops stack.",
    "support": "The goal centers on customer requests, support workflows, knowledge base, or escalation, so Astra should deploy the support stack.",
    "product": "The goal centers on product planning, specs, roadmap, implementation, or release execution, so Astra should deploy the product stack.",
}


def recommend_stack(goal: str, company_stage: str | None = None) -> StackRecommendation:
    text = f"{goal} {company_stage or ''}".lower()
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}
    for stack_id, signals in _STACK_SIGNALS.items():
        found = [signal for signal in signals if signal in text]
        scores[stack_id] = len(found)
        matches[stack_id] = found

    if company_stage:
        stage = company_stage.lower()
        if any(term in stage for term in ("idea", "zero", "pre", "new")):
            scores["idea_to_revenue"] += 2
            matches["idea_to_revenue"].append(f"stage:{company_stage}")
        if any(term in stage for term in ("existing", "business", "team", "revenue")):
            for stack_id in ("sales", "marketing", "founder_ops", "support", "product"):
                scores[stack_id] += 1

    best_id = max(scores, key=lambda stack_id: scores[stack_id])
    best_score = scores[best_id]
    if best_score <= 0:
        best_id = "idea_to_revenue"
        best_score = 1
        matches[best_id] = ["default founder outcome"]

    confidence = min(0.92, 0.52 + (best_score * 0.08))
    return StackRecommendation(
        stack=get_stack_template(best_id),
        confidence=round(confidence, 2),
        reason=_STACK_REASONS[best_id],
        matched_signals=matches[best_id][:8],
    )

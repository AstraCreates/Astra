"""
Founder Mirror — System G.

Adversarial red-team agent. Attacks every specialist output before
it reaches the founder. Returns pass/flag/block + critique.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_AGENT_QUESTIONS = {
    "research": [
        "Is this market size credible? What are the sources?",
        "What key competitors or substitutes are missing?",
        "Is the TAM calculation methodology sound?",
        "What assumption, if wrong, kills the thesis?",
    ],
    "legal": [
        "Does any clause expose the founder to unusual liability?",
        "What term would kill a Series A term sheet?",
        "Is jurisdiction appropriate for the founder's location?",
        "What's missing that a real attorney would flag immediately?",
    ],
    "web": [
        "Would a real customer click this CTA? Is it specific?",
        "Is the headline generic — could it apply to 12 competitors?",
        "Is there a clear, specific value proposition with real numbers?",
        "What would make a visitor bounce in the first 5 seconds?",
    ],
    "marketing": [
        "Who specifically is this for? Name a real person.",
        "What makes this copy different from every competitor?",
        "Is the call to action weak or vague?",
        "Would this perform better or worse than average for the platform?",
    ],
    "technical": [
        "Is this scaffold production-ready or a demo?",
        "What breaks at 1,000 concurrent users?",
        "Are there security vulnerabilities in the generated code?",
        "What critical dependency is missing from the architecture?",
    ],
    "ops": [
        "What's the single biggest operational risk not addressed here?",
        "Is the fundraising narrative coherent and defensible?",
        "What assumption in the financial model is most fragile?",
        "What would a skeptical Series A investor ask first?",
    ],
}

_SYSTEM_PROMPT = """\
You are Founder Mirror, a ruthless but constructive adversarial reviewer.
Your job: find critical flaws in AI agent outputs before they reach a founder.
Be direct. Be specific. Do not soften criticism.

Agent: {agent}
Output to review:
---
{output}
---

Focused questions to answer:
{questions}

Respond in this exact JSON format:
{{
  "verdict": "pass" | "flag" | "block",
  "critique": "2-4 sentences identifying the most critical weakness",
  "questions": ["specific unresolved question 1", "specific unresolved question 2"],
  "revised_recommendation": "concrete suggestion to fix the worst issue, or null if pass"
}}

Verdict thresholds:
- pass: output survives scrutiny, no critical flaws
- flag: output is weak but usable, founder should be aware
- block: output has a critical flaw that must be fixed before delivery

Return only valid JSON."""


@dataclass
class MirrorResult:
    verdict: str
    critique: str
    questions: list[str]
    revised_recommendation: str | None
    agent: str
    raw_output_length: int


class FounderMirror:
    def __init__(self):
        pass

    def review(self, agent: str, output: str) -> MirrorResult:
        """Run adversarial review. Returns MirrorResult with verdict."""
        import json as _json

        questions = _AGENT_QUESTIONS.get(agent, ["What is the single biggest flaw in this output?"])
        question_block = "\n".join(f"- {q}" for q in questions)

        prompt = _SYSTEM_PROMPT.format(
            agent=agent,
            output=output[:8000],  # cap input to mirror — not the generation
            questions=question_block,
        )

        try:
            from backend.tools._llm import generate
            raw = generate(prompt)
            # Strip markdown code fences if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = _json.loads(raw.strip())
            verdict = data.get("verdict", "flag")
            if verdict not in ("pass", "flag", "block"):
                verdict = "flag"
            return MirrorResult(
                verdict=verdict,
                critique=data.get("critique", ""),
                questions=data.get("questions", []),
                revised_recommendation=data.get("revised_recommendation"),
                agent=agent,
                raw_output_length=len(output),
            )
        except Exception as e:
            logger.warning("Mirror review failed (%s) — defaulting to flag", e)
            return MirrorResult(
                verdict="flag",
                critique=f"Mirror review failed: {e}",
                questions=questions[:2],
                revised_recommendation=None,
                agent=agent,
                raw_output_length=len(output),
            )

    def format_verdict(self, result: MirrorResult) -> str:
        symbol = {"pass": "✓", "flag": "⚑", "block": "✗"}.get(result.verdict, "?")
        lines = [
            f"[Founder Mirror — {result.agent.upper()}] {symbol} {result.verdict.upper()}",
            f"Critique: {result.critique}",
        ]
        if result.questions:
            lines.append("Open questions:")
            for q in result.questions:
                lines.append(f"  - {q}")
        if result.revised_recommendation:
            lines.append(f"Fix: {result.revised_recommendation}")
        return "\n".join(lines)

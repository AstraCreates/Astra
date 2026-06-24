"""AI-generated approval gates for custom stacks.

Calls the light model once with all selected task summaries and asks it to
identify which tasks require a founder approval gate — i.e. tasks that take
an irreversible, external, financial, or reputational action.

Falls back to the static _AGENT_APPROVAL_GATES dict if the call fails or times out.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a risk-assessment assistant for an AI startup platform.
You will be given a list of tasks an AI agent stack will execute on behalf of a founder.
Your job: identify which tasks require a HUMAN APPROVAL GATE before the action is taken.

Only create a gate for a task if it meets at least one of these criteria:
1. IRREVERSIBLE — files legal documents, registers an entity, executes a transaction
2. EXTERNAL — sends email/messages to real people outside the workspace
3. FINANCIAL — spends money, activates paid ad campaigns, commits budget
4. REPUTATIONAL — publishes content publicly (website, social post, press release)
5. INVESTOR/LEGAL — contacts investors, signs agreements, files IP or trademarks

DO NOT create gates for: research tasks, document drafting, internal planning, generating artifacts for review, data architecture, financial modeling (no external action).

Respond with ONLY a JSON object in this exact schema — no prose, no markdown:
{
  "gates": [
    {
      "agent": "<agent_id>",
      "key": "<short_snake_case_key>",
      "title": "<short human title, max 8 words>",
      "trigger": "<one sentence: what event arms this gate>",
      "required_before": "<one sentence: what action must not happen before approval>",
      "reason": "<one sentence: why founder must approve>"
    }
  ]
}

Rules:
- Use a shared key when multiple agents trigger the same category of risk (e.g. key="outbound_send" for any cold email, key="public_deploy" for any public publish).
- If no tasks require a gate, return {"gates": []}.
- Maximum 8 gates total. Merge similar risks under one key.
"""


def _parse_gates(raw: str) -> list[dict[str, str]]:
    """Extract JSON from model output, tolerating markdown fences."""
    text = raw.strip()
    if "```" in text:
        # strip fences
        text = text.split("```")[-2] if text.count("```") >= 2 else text.replace("```json", "").replace("```", "")
    text = text.strip()
    # find first { ... }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return []
    data = json.loads(text[start:end])
    return data.get("gates", [])


def generate_ai_approval_gates(
    tasks: list[dict[str, Any]],
    instruction: str,
    fallback: dict[str, Any],
    timeout: float = 12.0,
) -> dict[str, dict[str, str]]:
    """Return {agent_id: gate_dict} using AI, falling back to static dict on error."""
    try:
        from backend.config import settings
        from backend.core.key_rotator import get_openrouter_key

        api_key = get_openrouter_key() or settings.openrouter_api_key
        if not api_key:
            logger.warning("ai_gates: no OpenRouter key — using static fallback")
            return fallback

        from backend.core.llm_client import get_or_client
        client = get_or_client(settings.openrouter_base_url, api_key)

        task_lines = "\n".join(
            f"- agent={t['agent']} title={t['stack_task_title']!r} "
            f"produces={t['expected_artifacts']}"
            for t in tasks
        )
        user_msg = (
            f"Founder goal: {instruction}\n\n"
            f"Tasks to evaluate:\n{task_lines}"
        )

        resp = client.chat.completions.create(
            model=settings.or_light_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1024,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        gates = _parse_gates(raw)

        # Build {agent_id: gate_dict}, keeping only well-formed entries
        result: dict[str, dict[str, str]] = {}
        for g in gates:
            agent = g.get("agent", "")
            if not agent or not g.get("key"):
                continue
            result[agent] = {
                "key": g["key"],
                "title": g.get("title", "Founder approval required"),
                "trigger": g.get("trigger", ""),
                "required_before": g.get("required_before", ""),
                "reason": g.get("reason", ""),
            }

        logger.info("ai_gates: generated %d gates for %d tasks", len(result), len(tasks))
        return result

    except Exception as exc:
        logger.warning("ai_gates: failed (%s) — using static fallback", exc)
        return fallback

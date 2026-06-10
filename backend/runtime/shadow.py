"""Low-cost shadow comparison for legacy and normalized action parsing."""
from __future__ import annotations

from backend.runtime.actions import AgentAction
from backend.runtime.metrics import increment


def compare_action(parsed: dict) -> None:
    """Record whether the normalized action agrees with the legacy action."""
    try:
        normalized = AgentAction.from_json(parsed)
        legacy = parsed.get("action") or ("tool" if parsed.get("tool") else "done")
        if legacy in {"tool_call", "function_call", "call_tool", "use_tool"}:
            legacy = "tool"
        increment("shadow_action_match_total" if normalized.kind == legacy else "shadow_action_mismatch_total")
    except Exception:
        increment("shadow_action_error_total")

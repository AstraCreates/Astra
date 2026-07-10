import json
import sys
import types
from unittest.mock import AsyncMock

import pytest

if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object, RateLimitError=Exception)

from backend.core.agent import Agent, AgentContext


def _ctx() -> AgentContext:
    return AgentContext(goal="Investigate competitors", founder_id="f1", session_id="s1", shared={})


@pytest.mark.asyncio
async def test_agent_recovers_when_action_field_is_a_dict(mocker):
    """Real production crash: the model returned {"action": {...}} (a dict, not a
    string) on its first turn. Unguarded `x in self.tools` / `x == "done"` checks
    against that value raised TypeError: unhashable type: 'dict' before any tool
    was even dispatched — the run never got a chance to reach a normal completion
    or error status, agent.run() itself raised.

    This test deliberately asserts NOTHING about how/when the run eventually
    finishes (that depends on unrelated completion-quality-gate machinery keyed
    off agent name/tools — orthogonal to this bug and not this test's job to
    pin down). The only thing under test: a malformed dict-shaped action must
    not raise TypeError out of agent.run() — it should be treated as an
    'unknown action' and the loop should keep control (retry/exhaust normally),
    exactly like the WARNING-logged recovery already visible for any other
    malformed-but-hashable action value."""
    malformed = json.dumps({
        "action": {"tool": "generate_pdf"},
        "reasoning": {"note": "wrong shape"},
    })

    def fake_llm(_messages, _ctx=None):
        return malformed

    agent = Agent(name="hardening_probe", role="probe", tools={}, max_iterations=2)
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())

    result = await agent.run(_ctx())  # must not raise TypeError

    assert isinstance(result, dict)

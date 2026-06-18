import pytest
from unittest.mock import AsyncMock

from backend import copilot


def test_parse_action_recovers_preface_and_malformed_tool_payload():
    raw = """
Looking at the live session snapshot, I can see the web agent completed but the preview is missing.

Let me get more details on the current session and then dispatch the team if needed.
{"action":"tool","tool":"args":{"session_id":"26c128c62c8a4e04aa8b39b66c2fd11a"},"tool":"get_session_digest"}
""".strip()

    parsed = copilot._parse_action(raw)

    assert parsed["action"] == "tool"
    assert parsed["tool"] == "get_session_digest"
    assert parsed["args"] == {"session_id": "26c128c62c8a4e04aa8b39b66c2fd11a"}
    assert "Let me get more details" in parsed["preface"]


@pytest.mark.asyncio
async def test_run_copilot_executes_recovered_tool_then_replies(monkeypatch):
    outputs = iter([
        """
I can see the preview is missing, so I’m checking the current run first.
{"action":"tool","tool":"args":{"session_id":"sess_123"},"tool":"get_session_digest"}
""".strip(),
        '{"action":"reply","text":"I checked the current run and confirmed the preview is missing. I am re-dispatching the web and technical agents to rebuild it."}',
    ])

    async def fake_tool(founder_id: str, session_id: str, args: dict):
        assert founder_id == "founder_123"
        assert session_id == "sess_123"
        assert args == {"session_id": "sess_123"}
        return {"ok": True, "session_id": session_id, "goal": "Rebuild preview"}

    monkeypatch.setattr("backend.tools._llm.generate", lambda *args, **kwargs: next(outputs))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={"running_agents": []}))
    monkeypatch.setitem(copilot._TOOLS, "get_session_digest", ("doc", fake_tool))

    result = await copilot.run_copilot("founder_123", "sess_123", "fix the missing preview")

    assert result["ok"] is True
    assert "preview is missing" in result["reply"]
    assert result["actions"]
    assert result["actions"][0]["tool"] == "get_session_digest"
    assert result["history"][-1]["content"] == result["reply"]

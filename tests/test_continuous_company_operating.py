import asyncio
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_orchestrator_starts_operating_bootstrap_after_goal_done(monkeypatch):
    from backend.core.orchestrator import Orchestrator

    class Planner:
        name = "planner"
        model = "test"

        def _call_llm(self, _messages):
            return '{"tasks":[]}'

    class Agent:
        def __init__(self, output):
            self.output = output
            self.tools = {}
            self.name = "agent"

        async def run(self, _ctx):
            return self.output

    planner = Planner()
    web = Agent({"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"})
    orch = Orchestrator(planner=planner, specialists={"web": web})

    published = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    bootstrap_mock = AsyncMock()
    monkeypatch.setattr("backend.core.events.publish", capture_publish)
    monkeypatch.setattr(orch, "_bootstrap_operating_after_run", bootstrap_mock)
    monkeypatch.setattr(orch, "_expand_goal", AsyncMock(return_value="goal"))

    with patch("backend.tools.obsidian_logger._note_path"), \
         patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False), \
         patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True}):
        await orch.run(goal="g", founder_id="f", session_id="s", constraints={"agents": ["web"], "bypass_planner": True})
        await asyncio.sleep(0)

    assert any(event.get("type") == "goal_done" for event in published)
    bootstrap_mock.assert_awaited()

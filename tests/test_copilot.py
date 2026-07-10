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

    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(side_effect=lambda *args, **kwargs: next(outputs)))
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


@pytest.mark.asyncio
async def test_run_copilot_normalizes_bare_tool_name_action(monkeypatch):
    """Reproduces a real observed failure: the model emits {"action":"<tool_name>",
    ...} instead of {"action":"tool","tool":"<tool_name>",...}. Before the fix this
    silently fell through to the reply branch and dumped the raw JSON to the founder
    without ever calling the tool -- confirmed against real copilot history where
    stop_agent/session_status/run_cycle calls were shown verbatim as replies."""
    outputs = iter([
        '{"action":"stop_agent","agent":"research","session_id":"sess_123"}',
        '{"action":"reply","text":"Stopped the research agents."}',
    ])
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(side_effect=lambda *a, **k: next(outputs)))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={"running_agents": ["research"]}))

    called = {}

    async def fake_stop_agent(founder_id, session_id, args):
        called.update(args)
        return {"ok": True, "stopped": ["research"]}

    monkeypatch.setitem(copilot._TOOLS, "stop_agent", ("doc", fake_stop_agent))

    result = await copilot.run_copilot("founder_123", "sess_123", "tell research to finish")

    assert called == {"agent": "research", "session_id": "sess_123"}
    assert result["actions"] and result["actions"][0]["tool"] == "stop_agent"
    assert result["reply"] == "Stopped the research agents."
    assert "action" not in result["reply"]  # never the raw JSON blob


@pytest.mark.asyncio
async def test_run_copilot_unknown_tool_name_retries_instead_of_dumping_json(monkeypatch):
    """A hallucinated/misspelled tool name must feed back an error and let the
    model retry within its step budget, not dump raw JSON as the final reply."""
    outputs = iter([
        '{"action":"tool","tool":"kill_agent","args":{"agent":"research"}}',
        '{"action":"tool","tool":"stop_agent","args":{"agent":"research"}}',
        '{"action":"reply","text":"Done."}',
    ])
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(side_effect=lambda *a, **k: next(outputs)))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={"running_agents": ["research"]}))
    monkeypatch.setitem(copilot._TOOLS, "stop_agent", ("doc", AsyncMock(return_value={"ok": True})))

    result = await copilot.run_copilot("founder_123", "sess_123", "kill research")

    assert result["reply"] == "Done."
    assert result["actions"] and result["actions"][0]["tool"] == "stop_agent"


@pytest.mark.asyncio
async def test_run_copilot_auto_routes_named_agent_directive(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *args, **kwargs: '{"action":"reply","text":"I am on it."}')
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(return_value='{"action":"reply","text":"I am on it."}'))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={
        "running_agents": ["web"],
        "child_sessions_running": [],
        "session_meta": {"status": "running", "review_reason": ""},
        "deploy_targets": [],
    }))
    monkeypatch.setattr(copilot, "_agent_roster", lambda: {"web": "landing pages", "technical": "apps"})

    delivered: list[tuple[str, str]] = []

    async def fake_message_agent(founder_id: str, session_id: str, args: dict):
        delivered.append((args["agent"], args["message"]))
        return {"ok": True, "target_agent": args["agent"], "delivered": args["message"]}

    monkeypatch.setattr(copilot, "_tool_message_agent", fake_message_agent)

    result = await copilot.run_copilot("founder_123", "sess_123", "Tell the web agent to polish the deployment flow.")

    assert delivered == [("web", "Tell the web agent to polish the deployment flow.")]
    assert result["actions"][0]["tool"] == "message_agent"
    assert "Sent to web" in result["reply"]


@pytest.mark.asyncio
async def test_run_copilot_routes_explicit_ui_mentions_to_each_running_agent(monkeypatch):
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(return_value='{"action":"reply","text":"I am on it."}'))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={
        "running_agents": ["web", "design"],
        "child_sessions_running": [],
        "session_meta": {"status": "running"},
    }))
    monkeypatch.setattr(copilot, "_agent_roster", lambda: {"web": "landing pages", "design": "brand systems"})

    delivered: list[str] = []

    async def fake_message_agent(founder_id: str, session_id: str, args: dict):
        delivered.append(args["agent"])
        return {"ok": True, "target_agent": args["agent"]}

    monkeypatch.setattr(copilot, "_tool_message_agent", fake_message_agent)

    result = await copilot.run_copilot(
        "founder_123",
        "sess_123",
        "@web @design tighten the launch experience",
        mentioned_agents=["web", "design", "not_a_real_agent"],
    )

    assert delivered == ["web", "design"]
    assert [action["tool"] for action in result["actions"]] == ["message_agent", "message_agent"]


@pytest.mark.asyncio
async def test_run_copilot_preserves_unmentioned_idle_dispatch(monkeypatch):
    outputs = iter([
        '{"action":"tool","tool":"dispatch_agents","args":{"agents":["web","technical"],"instruction":"Build the launch site"}}',
        '{"action":"reply","text":"I started the build."}',
    ])
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(side_effect=lambda *args, **kwargs: next(outputs)))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={
        "running_agents": [],
        "child_sessions_running": [],
        "session_meta": {"status": "done"},
    }))
    monkeypatch.setattr(copilot, "_agent_roster", lambda: {"web": "landing pages", "technical": "apps"})

    dispatched: list[dict] = []

    async def fake_dispatch(founder_id: str, session_id: str, args: dict):
        dispatched.append(args)
        return {"ok": True, "dispatched": args["agents"]}

    monkeypatch.setitem(copilot._TOOLS, "dispatch_agents", ("doc", fake_dispatch))

    result = await copilot.run_copilot("founder_123", "sess_123", "Build the launch site")

    assert dispatched == [{"agents": ["web", "technical"], "instruction": "Build the launch site"}]
    assert result["reply"] == "I started the build."


@pytest.mark.asyncio
async def test_run_copilot_auto_dispatches_deploy_breakage_fix(monkeypatch):
    monkeypatch.setattr(copilot, "_copilot_generate", AsyncMock(return_value='{"action":"reply","text":"Checking."}'))
    monkeypatch.setattr(copilot, "get_history", lambda session_id: [])
    monkeypatch.setattr(copilot, "_save_history", lambda session_id, history: None)
    monkeypatch.setattr(copilot, "_load_live_context", AsyncMock(return_value={
        "running_agents": [],
        "child_sessions_running": [],
        "session_meta": {"status": "done", "review_reason": "deploy check failed"},
        "deploy_targets": [{"agent": "web", "url": "https://broken.example.com"}],
    }))

    dispatched: list[dict] = []

    async def fake_dispatch(founder_id: str, session_id: str, args: dict):
        dispatched.append(args)
        return {"ok": True, "dispatched": args["agents"], "session_id": "child_fix"}

    monkeypatch.setattr(copilot, "_tool_dispatch_agents", fake_dispatch)

    result = await copilot.run_copilot("founder_123", "sess_123", "The preview is 404 again.")

    assert dispatched
    assert dispatched[0]["agents"] == ["web", "technical"]
    assert "broken deployment" in dispatched[0]["instruction"].lower()
    assert result["actions"][0]["tool"] == "dispatch_agents"


@pytest.mark.asyncio
async def test_tool_decide_goal_task_updates_waiting_milestone(monkeypatch):
    monkeypatch.setattr(copilot, "_company_for_session", lambda session_id, founder_id: "company_123")

    called = {}

    def fake_decide_task(founder_id, task_id, approved, note="", company_id=None):
        called.update({
            "founder_id": founder_id,
            "task_id": task_id,
            "approved": approved,
            "note": note,
            "company_id": company_id,
        })
        return {"title": "Approve homepage", "status": "done"}

    monkeypatch.setattr("backend.missions.company_goal.decide_task", fake_decide_task)

    result = await copilot._tool_decide_goal_task(
        "founder_123",
        "sess_123",
        {"task_id": "task_1", "approved": True, "note": "Looks good"},
    )

    assert result["ok"] is True
    assert result["status"] == "done"
    assert called == {
        "founder_id": "founder_123",
        "task_id": "task_1",
        "approved": True,
        "note": "Looks good",
        "company_id": "company_123",
    }


@pytest.mark.asyncio
async def test_tool_stop_agent_expands_research_lanes(monkeypatch):
    """'research' is not one process -- it's 5 concurrently-running lanes. Stopping
    the bare name must stop all of them, not just the literal 'research' agent."""
    monkeypatch.setattr(copilot, "_assert_session_owner", lambda session_id, founder_id: None)
    monkeypatch.setattr("backend.core.events.publish", AsyncMock())

    stopped = []
    monkeypatch.setattr("backend.core.cancellation.request_kill_agent", lambda sid, name: stopped.append(name))

    result = await copilot._tool_stop_agent("founder_123", "sess_123", {"agent": "research"})

    assert result["ok"] is True
    assert set(stopped) == {
        "research", "research_gtm", "research_competitors",
        "research_customers", "research_execution",
    }
    assert set(result["stopped"]) == set(stopped)


@pytest.mark.asyncio
async def test_tool_stop_agent_single_instance_unaffected(monkeypatch):
    """A single-instance specialist (no lanes) must stop only itself."""
    monkeypatch.setattr(copilot, "_assert_session_owner", lambda session_id, founder_id: None)
    monkeypatch.setattr("backend.core.events.publish", AsyncMock())

    stopped = []
    monkeypatch.setattr("backend.core.cancellation.request_kill_agent", lambda sid, name: stopped.append(name))

    result = await copilot._tool_stop_agent("founder_123", "sess_123", {"agent": "design"})

    assert result["ok"] is True
    assert stopped == ["design"]


@pytest.mark.asyncio
async def test_tool_get_subteam_report_returns_summary(monkeypatch):
    monkeypatch.setattr(
        "backend.company_reports.build_company_subteam_report",
        lambda founder_id, team, days: {
            "team": team,
            "summary": f"{team} summary",
            "record_count": 4,
            "session_count": 2,
            "active_work": [{"title": "Ship flow"}],
            "completed_work": [{"title": "Deploy"}],
            "blockers": [{"title": "Need copy"}],
            "next_actions": ["Review deploy"],
        },
    )

    result = await copilot._tool_get_subteam_report("founder_123", "sess_123", {"team": "engineering", "days": 14})

    assert result["ok"] is True
    assert result["team"] == "engineering"
    assert result["record_count"] == 4
    assert result["next_actions"] == ["Review deploy"]

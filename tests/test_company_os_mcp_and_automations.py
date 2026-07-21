"""Regression coverage for the Company OS MCP and automation bridges."""
from __future__ import annotations

from types import SimpleNamespace


def test_company_os_replays_mcp_audit_events(tmp_path):
    from backend import company_os

    company_os.create_company_os("co", "founder", "Company", root=tmp_path)
    company_os.append_event("co", "mcp.tool_called", {"call_id": "call", "tool": "astra_company_research"}, root=tmp_path)
    company_os.append_event("co", "mcp.tool_completed", {"call_id": "call", "tool": "astra_company_research", "ok": True}, root=tmp_path)

    state = company_os.get_company_os("co", root=tmp_path)
    assert [entry["event_type"] for entry in state["mcp_audit"]] == ["mcp.tool_called", "mcp.tool_completed"]


def test_company_research_persists_a_live_search_count_onto_the_task(tmp_path, monkeypatch):
    from backend import company_os
    import backend.astra_mcp as mcp

    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    company_os.create_company_os("co", "founder", "Company")
    initiative = company_os.create_initiative("co", "Research", initiative_id="i1")
    squad = company_os.create_squad("co", "i1", "Insights", squad_id="s1")
    task = company_os.create_task("co", "i1", "s1", "Gather validated evidence", task_id="t1", state="working")

    def fake_pipeline(topic, *, focus, max_results_each, on_search=None):
        for _ in range(3):
            on_search()
        return {
            "combined_formatted": "evidence", "queries_run": 3,
            "sources": [{"url": "https://example.com/a", "retrieved_at": "2026-07-21T00:00:00Z"},
                        {"url": "https://example.org/b", "retrieved_at": "2026-07-21T00:00:00Z"}],
        }
    # The public Company OS research boundary is deep research. The old
    # batch pipeline is only used by delegated worker calls.
    async def fake_deep(topic, **scope):
        assert scope["task_id"] == "t1"
        return {
            "combined_formatted": "evidence", "queries_run": 3,
            "search_count": 3,
            "sources": [{"url": "https://example.com/a", "retrieved_at": "2026-07-21T00:00:00Z"},
                        {"url": "https://example.org/b", "retrieved_at": "2026-07-21T00:00:00Z"}],
            "structured": {"evidence": [{"claim": "supported"}]},
            "coverage": {"ready": True, "gaps": []},
        }
    monkeypatch.setattr("backend.tools.open_deep_research_adapter.run_open_deep_research", fake_deep)
    monkeypatch.setattr("backend.tools.browser_research.run_research_pipeline", fake_pipeline)

    result = mcp._company_research({"company_id": "co", "founder_id": "founder", "subject": "instacart", "task_id": "t1"})

    assert result["ok"] is True
    updated_task = next(item for item in company_os.get_company_os("co")["tasks"] if item["task_id"] == "t1")
    assert updated_task["search_count"] == 3


def test_deep_worker_uses_quick_pipeline_without_recursing_into_supervisor(tmp_path, monkeypatch):
    from backend import company_os
    import backend.astra_mcp as mcp

    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    company_os.create_company_os("co", "founder", "Company")
    calls = []

    def fake_pipeline(topic, *, focus, max_results_each, on_search=None):
        calls.append(topic)
        return {
            "combined_formatted": "worker evidence", "queries_run": 1,
            "sources": [{"url": "https://example.com/worker", "retrieved_at": "2026-07-21T00:00:00Z"}],
            "structured": {"evidence": [{"claim": "worker claim"}]},
        }

    monkeypatch.setattr("backend.tools.browser_research.run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(
        "backend.tools.open_deep_research_adapter.run_open_deep_research",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("worker recursed into supervisor")),
    )

    result = mcp._company_research({
        "company_id": "co", "founder_id": "founder", "subject": "pricing evidence",
        "task_id": "t1", "deep_worker": True,
    })
    assert result["ok"] is True
    assert calls == ["pricing evidence"]


def test_deep_worker_search_count_accumulates_instead_of_resetting_across_delegated_calls(tmp_path, monkeypatch):
    """The Open Deep Research supervisor delegates to the same task_id many
    times (one nested deep_worker call per sub-question). Each nested call
    used to persist only its own local count, resetting the task's live
    search_count back down to one call's small cap every time a call
    finished -- capping the UI at _RESEARCH_QUERY_PLAN_LIMIT forever."""
    from backend import company_os
    import backend.astra_mcp as mcp

    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    company_os.create_company_os("co", "founder", "Company")
    initiative = company_os.create_initiative("co", "Research", initiative_id="i1")
    squad = company_os.create_squad("co", "i1", "Insights", squad_id="s1")
    company_os.create_task("co", "i1", "s1", "Gather validated evidence", task_id="t1", state="working")

    def fake_pipeline(topic, *, focus, max_results_each, on_search=None):
        for _ in range(6):
            on_search()
        return {
            "combined_formatted": "worker evidence", "queries_run": 6,
            "sources": [{"url": "https://example.com/worker", "retrieved_at": "2026-07-21T00:00:00Z"}],
            "structured": {"evidence": [{"claim": "worker claim"}]},
        }

    monkeypatch.setattr("backend.tools.browser_research.run_research_pipeline", fake_pipeline)

    mcp._company_research({"company_id": "co", "founder_id": "founder", "subject": "first sub-question", "task_id": "t1", "deep_worker": True})
    task_after_first = next(t for t in company_os.get_company_os("co")["tasks"] if t["task_id"] == "t1")
    assert task_after_first["search_count"] == 6

    mcp._company_research({"company_id": "co", "founder_id": "founder", "subject": "second sub-question", "task_id": "t1", "deep_worker": True})
    task_after_second = next(t for t in company_os.get_company_os("co")["tasks"] if t["task_id"] == "t1")
    assert task_after_second["search_count"] == 12


def test_company_mcp_bridge_audits_registered_tool(monkeypatch):
    from backend import company_os_mcp

    events = []
    monkeypatch.setattr(company_os_mcp, "get_company_os", lambda _: {"company_id": "co", "founder_id": "founder"})
    monkeypatch.setattr(company_os_mcp, "append_event", lambda *args: events.append(args))
    import backend.astra_mcp as mcp
    monkeypatch.setattr(mcp, "call_tool", lambda name, args, founder: {"ok": True, "name": name, "founder": founder})

    result = company_os_mcp.invoke("co", "astra_credits")
    assert result["ok"] is True
    assert result["founder"] == "founder"
    assert [event[1] for event in events] == ["mcp.tool_called", "mcp.tool_completed"]


def test_company_mcp_bridge_falls_through_to_runtime_registry(monkeypatch):
    from backend import company_os_mcp
    from backend.runtime.tool_registry import ToolEntry, registry

    events = []
    monkeypatch.setattr(company_os_mcp, "get_company_os", lambda _: {"company_id": "co", "founder_id": "founder"})
    monkeypatch.setattr(company_os_mcp, "append_event", lambda *args: events.append(args))
    registry.register(ToolEntry(
        name="specialist_read", toolset="research", schema={"name": "specialist_read", "parameters": {}},
        handler=lambda founder_id="": {"founder": founder_id}, context_fields=frozenset({"founder_id"}),
    ), override=True)

    result = company_os_mcp.invoke("co", "specialist_read", task_id="task", mission_id="mission")
    assert result == {"founder": "founder"}
    assert events[0][2]["task_id"] == "task"
    assert events[-1][2]["mission_id"] == "mission"


def test_stdio_mcp_rejects_removed_run_tools():
    from backend import astra_mcp

    response = astra_mcp.handle_request({"id": 1, "method": "tools/call", "params": {"name": "astra_submit_goal", "arguments": {}}})
    assert response["error"]["code"] == -32000
    assert "removed" in response["error"]["message"]


def test_automation_external_node_becomes_company_approval(monkeypatch):
    from backend import company_os_automations as bridge

    company = {
        "company_id": "co", "founder_id": "founder",
        "initiatives": [{"initiative_id": "ops", "system_key": "company_operations"}],
        "squads": [{"squad_id": "squad", "initiative_id": "ops", "state": "active"}],
    }
    created = []
    approvals = []
    monkeypatch.setattr(bridge, "list_company_os", lambda founder: [company])
    monkeypatch.setattr(bridge, "ensure_company_operations", lambda _: {"initiative_id": "ops"})
    monkeypatch.setattr(bridge, "get_company_os", lambda _: company)
    monkeypatch.setattr(bridge, "create_mission", lambda *args, **kwargs: {"mission_id": "mission"})
    monkeypatch.setattr(bridge, "create_task", lambda *args, **kwargs: created.append(kwargs) or {"task_id": f"task-{len(created)}"})
    monkeypatch.setattr(bridge, "_record_policy", lambda *args: None)
    monkeypatch.setattr(bridge, "_create_approval_card", lambda *args: approvals.append(args))

    context = bridge.prepare_flow_run("founder", {"id": "flow", "name": "Notify", "nodes": [{"id": "mail", "type": "email", "config": {"to": "a@example.com"}}]}, "attempt")
    assert context and context["requires_approval"] is True
    assert created[0]["state"] == "awaiting_approval"
    assert len(approvals) == 1

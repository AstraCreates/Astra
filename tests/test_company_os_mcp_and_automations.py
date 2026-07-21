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
    monkeypatch.setattr("backend.tools.browser_research.run_research_pipeline", fake_pipeline)

    result = mcp._company_research({"company_id": "co", "founder_id": "founder", "subject": "instacart", "task_id": "t1"})

    assert result["ok"] is True
    updated_task = next(item for item in company_os.get_company_os("co")["tasks"] if item["task_id"] == "t1")
    assert updated_task["search_count"] == 3


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

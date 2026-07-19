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

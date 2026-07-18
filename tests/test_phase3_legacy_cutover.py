"""Phase 3 must reject old run/session APIs before their handlers run."""
from fastapi.testclient import TestClient


def test_legacy_run_session_routes_return_removal_without_store_reads(monkeypatch):
    import backend.main as main

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy session store must not be read")

    import backend.core.session_store as session_store
    monkeypatch.setattr(session_store, "list_sessions", forbidden)
    client = TestClient(main.app)
    for path in ("/sessions?founder_id=founder", "/runs/run_123", "/copilot/bootstrap", "/stream/session_123"):
        response = client.get(path)
        assert response.status_code == 410
        assert response.json()["error"] == "legacy_run_session_removed"


def test_company_mcp_tools_remain_while_legacy_mcp_tools_are_removed():
    from backend import astra_mcp

    names = {tool["name"] for tool in astra_mcp.TOOLS}
    assert {"astra_company_os_context", "astra_company_research"} <= names
    assert "astra_submit_goal" not in names
    try:
        astra_mcp.call_tool("astra_submit_goal", {}, "founder")
    except ValueError as exc:
        assert "removed" in str(exc)
    else:
        raise AssertionError("legacy MCP tool must not be callable")


def test_automation_run_urls_are_removed_in_favor_of_attempts():
    import backend.main as main

    client = TestClient(main.app)
    response = client.get("/automations/flows/flow_123/runs")
    assert response.status_code == 410
    assert response.json()["error"] == "legacy_run_removed"


def test_http_mcp_rejects_retired_session_action():
    import backend.main as main

    client = TestClient(main.app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "astra_submit_goal", "arguments": {}}})
    payload = response.json()["result"]["structuredContent"]
    assert payload["error"] == "legacy_run_session_removed"
    response = client.post("/automations/flows/flow_123/run")
    assert response.status_code == 410
    assert response.json()["error"] == "legacy_run_removed"

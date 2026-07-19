import pytest

from backend import company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import run_mission


@pytest.mark.asyncio
async def test_research_mission_runs_to_a_durable_decision_brief(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    company_os.create_company_os("acme", "founder", "Acme")
    dispatch = dispatch_intent("acme", "Research the viability of an AI consulting company")

    monkeypatch.setattr(
        "backend.company_os_runner.invoke_mcp",
        lambda *_args, **_kwargs: {
            "combined_formatted": "Demand exists, but differentiation and specialist credibility are critical.",
            "sources": [
                {"title": "Industry report", "url": "https://example.com/report"},
                {"title": "Customer evidence", "url": "https://customers.example/customer"},
                {"title": "Competitor evidence", "url": "https://competitors.example/competitor"},
            ],
            "coverage": {"ready": True},
        },
    )

    await run_mission("acme", dispatch["mission"]["mission_id"])

    state = company_os.get_company_os("acme")
    assert [task["state"] for task in state["tasks"]] == ["done", "done", "done"]
    assert [attempt["state"] for attempt in state["task_attempts"]] == ["completed"] * 3
    assert state["missions"][-1]["state"] == "done"
    assert state["squads"][-1]["lifecycle"] == "done"
    assert len(state["artifacts"]) == 3
    assert "Decision brief" in state["artifacts"][-1]["content"]
    assert any("Working on:" in message["message"] for message in state["conversation"])

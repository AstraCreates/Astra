import pytest

from backend import company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import run_mission
from backend.company_os_runner import _complete_chat_reply, _fallback_summary, _is_comparison_request


def _fake_llm_generate(prompt, *, model="large", json_mode=False, max_tokens=None, temperature=0.7):
    if json_mode:
        return '{"title": "AI Consulting Viability Brief", "content": "## Direct answer\\n\\nDemand exists, but differentiation and specialist credibility are the real risk.\\n\\n## Bottom line\\nNarrow to one vertical before selling."}'
    return "Demand's there for AI consulting, but differentiation and specialist credibility are the real risk. Full write-up is in the brief if you want more."


def test_chat_reply_rejects_a_cutoff_provider_response_and_has_a_clean_fallback():
    assert not _complete_chat_reply("Cofounder has a free")
    assert _complete_chat_reply("Cofounder has a free trial.\n\n- Astra has a setup fee.")
    assert _fallback_summary("## Context\n\nAstra is aimed at founders building an operating system.").endswith(".")
    assert _is_comparison_request("Compare Cofounder.co to AstraCreates.com")


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
    monkeypatch.setattr("backend.tools._llm.generate", _fake_llm_generate)

    await run_mission("acme", dispatch["mission"]["mission_id"])

    state = company_os.get_company_os("acme")
    assert [task["state"] for task in state["tasks"]] == ["done", "done", "done"]
    assert [attempt["state"] for attempt in state["task_attempts"]] == ["completed"] * 3
    assert state["missions"][-1]["state"] == "done"
    assert state["squads"][-1]["lifecycle"] == "done"
    assert len(state["artifacts"]) == 3
    assert state["artifacts"][-1]["name"] == "AI Consulting Viability Brief"
    assert "Bottom line" in state["artifacts"][-1]["content"]
    assert any("Working on:" in message["message"] for message in state["conversation"])
    assert any("differentiation" in message["message"] for message in state["conversation"] if message.get("kind") == "chat")


@pytest.mark.asyncio
async def test_document_synthesis_falls_back_to_raw_excerpt_when_llm_fails(tmp_path, monkeypatch):
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
        },
    )

    def _broken_generate(*_args, **_kwargs):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr("backend.tools._llm.generate", _broken_generate)

    await run_mission("acme", dispatch["mission"]["mission_id"])

    state = company_os.get_company_os("acme")
    # A model hiccup must never block the mission -- it degrades to a plain
    # excerpt instead of leaving the task blocked.
    assert [task["state"] for task in state["tasks"]] == ["done", "done", "done"]
    assert "Demand exists" in state["artifacts"][-1]["content"]
    assert any(message.get("kind") == "chat" for message in state["conversation"])

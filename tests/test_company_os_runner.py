import contextlib

import pytest

from backend import company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import recover_pending_missions, run_mission
from backend.company_os_runner import _comparison_document, _complete_chat_reply, _decision_brief, _fallback_summary, _is_comparison_request, _synthesize_comparison_document, _website_preview


def _fake_llm_generate(prompt, *, model="large", json_mode=False, max_tokens=None, temperature=0.7):
    if json_mode:
        return '{"title": "AI Consulting Viability Brief", "content": "## Direct answer\\n\\nDemand exists, but differentiation and specialist credibility are the real risk.\\n\\n## Bottom line\\nNarrow to one vertical before selling."}'
    return "Demand's there for AI consulting, but differentiation and specialist credibility are the real risk. Full write-up is in the brief if you want more."


def test_chat_reply_rejects_a_cutoff_provider_response_and_has_a_clean_fallback():
    assert not _complete_chat_reply("Cofounder has a free")
    assert _complete_chat_reply("Cofounder has a free trial for founders testing the product.\n\n- Astra has a setup fee before a founder can begin using the product.")
    assert _fallback_summary("## Context\n\nAstra is aimed at founders building an operating system.").endswith(".")
    assert _is_comparison_request("Compare Cofounder.co to AstraCreates.com")


@pytest.mark.asyncio
async def test_recover_pending_missions_requeues_stale_working_tasks(monkeypatch):
    company = {
        "company_id": "acme",
        "missions": [{"mission_id": "mission-1", "state": "working"}],
        "tasks": [{
            "task_id": "task-1",
            "mission_id": "mission-1",
            "name": "Deep research",
            "state": "working",
            "updated_at": "2020-01-01T00:00:00Z",
        }],
        "task_attempts": [{"attempt_id": "attempt-1", "task_id": "task-1", "state": "running"}],
    }
    updates = []
    attempt_updates = []
    messages = []
    launches = []

    class _Settings:
        company_os_stale_task_seconds = 60

    monkeypatch.setattr("backend.config.settings", _Settings())
    monkeypatch.setattr("backend.company_os_runner.list_company_os", lambda: [company])
    monkeypatch.setattr("backend.company_os_runner.company_recovery_lock", lambda *_args, **_kwargs: contextlib.nullcontext())
    monkeypatch.setattr("backend.company_os_runner.get_company_os", lambda *_args, **_kwargs: company)
    monkeypatch.setattr("backend.company_os_runner.update_task", lambda *args, **kwargs: updates.append((args, kwargs)))
    monkeypatch.setattr("backend.company_os_runner.update_task_attempt", lambda *args, **kwargs: attempt_updates.append((args, kwargs)))
    monkeypatch.setattr("backend.company_os_runner.append_message", lambda *args, **kwargs: messages.append((args, kwargs)))
    async def _run_recovered(company_id, mission_id):
        launches.append((company_id, mission_id))
    monkeypatch.setattr("backend.company_os_runner.run_mission", _run_recovered)
    monkeypatch.setattr("backend.company_os_runner.launch_mission", lambda company_id, mission_id: launches.append((company_id, mission_id)) or True)

    assert await recover_pending_missions() == 1
    assert updates[0][0] == ("acme", "task-1")
    assert updates[0][1]["state"] == "pending"
    assert updates[0][1]["recovery_reason"] == "stale_working_task_after_process_restart"
    assert attempt_updates[0][0] == ("acme", "attempt-1")
    assert attempt_updates[0][1]["error"] == "orphaned_after_process_restart"
    assert launches == [("acme", "mission-1")]
    assert "Recovered stalled work" in messages[0][0][1]


def test_comparison_document_never_recommends_with_unbalanced_evidence():
    title, content = _comparison_document("Compare Cofounder to Astra", {"evidence_ledger": {"Cofounder": {"product": [{"title": "About", "url": "https://cofounder.example/about"}], "pricing": [], "privacy": []}, "Astra": {"product": [], "pricing": [], "privacy": []}}})
    assert "comparison" in title.lower()
    assert "No winner is declared" in content
    assert "Not verified from available public evidence" in content


def _comparison_evidence():
    return {
        "evidence_ledger": {
            "Cofounder": {"product": [{"title": "About", "url": "https://cofounder.example/about", "excerpt": "Cofounder is an agentic operating system."}], "pricing": [{"title": "Pricing", "url": "https://cofounder.example/pricing", "excerpt": "Pro plan is $20/mo of usage."}]},
            "Astra": {"product": [{"title": "Home", "url": "https://astra.example", "excerpt": "Astra launches a company from an idea."}], "pricing": [{"title": "Pricing", "url": "https://astra.example/pricing", "excerpt": "Build plan is $40/mo."}]},
        },
        "coverage": {"ready": True},
        "combined_formatted": "Cofounder is an agentic operating system. Pro plan is $20/mo. Astra launches from an idea. Build plan is $40/mo.",
    }


def test_synthesize_comparison_document_uses_the_llm_report_when_available(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: (
        '{"title": "Cofounder and Astra Compared", '
        '"content": "## Executive summary\\n\\nBoth help founders build companies.\\n\\n'
        '## Comparison overview\\n\\n| Dimension | Cofounder | Astra |\\n| --- | --- | --- |\\n| Pricing | $20/mo | $40/mo |\\n\\n'
        '### Cofounder pros and cons\\n\\n| Pros | Cons |\\n| --- | --- |\\n| Broad | Complex |\\n\\n'
        '## Bottom line\\n\\nPick based on budget."}'
    ))

    title, content = _synthesize_comparison_document("Compare Cofounder and Astra", _comparison_evidence())

    assert title == "Cofounder and Astra Compared"
    assert "## Executive summary" in content
    assert "## Comparison overview" in content
    assert "pros and cons" in content


def test_synthesize_comparison_document_falls_back_to_the_evidence_table_on_llm_failure(monkeypatch):
    def broken_generate(*_a, **_k):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr("backend.tools._llm.generate", broken_generate)

    title, content = _synthesize_comparison_document("Compare Cofounder and Astra", _comparison_evidence())

    # Falls back to the mechanical, evidence-gated table -- never leaves the
    # founder with nothing, and never invents a recommendation the LLM path
    # would have (this evidence set has both dimensions covered, so the
    # fallback declares readiness rather than withholding).
    assert "comparison" in title.lower()
    assert "Verified evidence" in content


def test_decision_brief_uses_the_supervisor_report_verbatim_instead_of_resummarizing(monkeypatch):
    def _fail_if_called(*_a, **_k):
        raise AssertionError("should not re-synthesize a supervisor report through the LLM")
    monkeypatch.setattr("backend.tools._llm.generate", _fail_if_called)

    report = "# Viability of AI Consulting\n\n" + ("Detailed cited finding. " * 40)
    evidence = {
        "deep_research_supervisor": True,
        "content": report,
        "source_references": [{"title": "Report", "url": "https://example.com/report"}],
    }

    title, content = _decision_brief("Research the viability of AI consulting", evidence)

    assert title == "Viability of AI Consulting"
    assert content == report.strip()


def test_decision_brief_falls_back_to_synthesis_when_supervisor_report_is_thin(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: (
        '{"title": "Fallback Brief", "content": "## Bottom line\\n\\nSynthesized instead."}'
    ))

    evidence = {
        "deep_research_supervisor": True,
        "content": "too short",
        "source_references": [{"title": "Report", "url": "https://example.com/report"}],
    }

    title, content = _decision_brief("Research the viability of AI consulting", evidence)

    assert title == "Fallback Brief"
    assert "Synthesized instead" in content


def test_website_preview_is_domain_specific_and_never_echoes_the_raw_request():
    preview = _website_preview("compare cofounder.co and astracreates.com and create a website for goon.com that has the best of both worlds", [{"title": "Source", "url": "https://example.com"}])
    assert "Goon" in preview
    assert "goon.com" in preview
    assert "Informed by 1 cited research source" in preview
    assert "compare cofounder.co and astracreates.com" not in preview


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
            "queries_run": 1,
            "structured": {"research": {"evidence": [{"retrieved_at": "2026-01-01T00:00:00Z"}]}},
            "research_status": "validated",
            "evidence_validation": {"ok": True, "gaps": [], "search_count": 1, "source_count": 3},
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
            "queries_run": 1,
            "structured": {"research": {"evidence": [{"retrieved_at": "2026-01-01T00:00:00Z"}]}},
            "research_status": "validated",
            "evidence_validation": {"ok": True, "gaps": [], "search_count": 1, "source_count": 3},
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

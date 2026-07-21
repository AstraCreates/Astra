import pytest

from backend import company_os
from backend.company_os_dispatch import dispatch_intent
from backend.company_os_runner import run_mission
from backend.company_os_runner import _comparison_document, _complete_chat_reply, _fallback_summary, _is_comparison_request, _synthesize_comparison_document, _website_preview


def _fake_llm_generate(prompt, *, model="large", json_mode=False, max_tokens=None, temperature=0.7):
    if json_mode:
        return '{"title": "AI Consulting Viability Brief", "content": "## Direct answer\\n\\nDemand exists, but differentiation and specialist credibility are the real risk.\\n\\n## Bottom line\\nNarrow to one vertical before selling."}'
    return "Demand's there for AI consulting, but differentiation and specialist credibility are the real risk. Full write-up is in the brief if you want more."


def test_chat_reply_rejects_a_cutoff_provider_response_and_has_a_clean_fallback():
    assert not _complete_chat_reply("Cofounder has a free")
    assert _complete_chat_reply("Cofounder has a free trial for founders testing the product.\n\n- Astra has a setup fee before a founder can begin using the product.")
    assert _fallback_summary("## Context\n\nAstra is aimed at founders building an operating system.").endswith(".")
    assert _is_comparison_request("Compare Cofounder.co to AstraCreates.com")


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

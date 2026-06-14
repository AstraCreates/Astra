"""Deep verification ladder: shape / executable / semantic + evidence block."""
import pytest

from backend.stacks import run_deep_verification
from backend.stacks.verification_gates import _infer_kind, probe_live_url


async def _pass_llm(_messages):
    return '{"verdict": "pass", "issues": []}'


async def _fail_llm(_messages):
    return '{"verdict": "fail", "issues": ["competitors not named"]}'


def _base(key, title="", required=True):
    return {"status": "passed", "artifacts": [{"artifact_key": key, "title": title, "required": required}]}


async def test_url_deliverable_without_url_is_blocked():
    v = await run_deep_verification(
        agent_name="web",
        task={"id": "t", "instruction": "build", "expected_artifacts": ["landing_page"]},
        result={"summary": "x" * 400},
        base_verdict=_base("landing_page", "Landing page"),
        llm_call=_pass_llm,
    )
    assert v["status"] == "blocked"
    assert any("URL" in c for c in v["levels"]["shape"])


async def test_thin_doc_deliverable_is_blocked():
    v = await run_deep_verification(
        agent_name="custom_x",
        task={"id": "t", "instruction": "x", "expected_artifacts": ["compliance_report"]},
        result={"compliance_report": "short"},
        base_verdict=_base("compliance_report", "Compliance report"),
        llm_call=_pass_llm,
    )
    assert v["status"] == "blocked"


async def test_good_doc_custom_agent_passes_with_evidence():
    body = "Acme must comply with GDPR Article 6. Source: https://gdpr.eu [1] " * 12
    v = await run_deep_verification(
        agent_name="custom_x",
        task={"id": "t", "instruction": "x", "expected_artifacts": ["compliance_report"]},
        result={"compliance_report": body},
        base_verdict=_base("compliance_report", "Compliance report"),
        llm_call=_pass_llm,
    )
    assert v["status"] == "passed"
    assert v["evidence"]["semantic"]["sources_count"] > 0
    assert v["evidence"]["shape"]["passed"] is True


async def test_semantic_failure_is_needs_review_not_blocked():
    body = "Acme raised $12M in 2024. Competitors: Notion, Linear, Asana. TAM is 4.5B. " * 16
    v = await run_deep_verification(
        agent_name="research",
        task={"id": "t", "instruction": "research", "expected_artifacts": ["market_brief"]},
        result={"market_brief": body, "findings": body},
        base_verdict=_base("market_brief", "Market brief"),
        llm_call=_fail_llm,
    )
    assert v["status"] == "needs_review"
    assert v["levels"]["semantic"] == ["competitors not named"]


def test_infer_kind_word_boundary_not_substring():
    # "compliance_report" contains the substring "repo" but is a document, not a URL.
    assert _infer_kind("compliance_report", "Compliance report") == "doc"
    assert _infer_kind("github_repo", "GitHub repo") == "url"
    assert _infer_kind("landing_page", "Landing page") == "url"
    assert _infer_kind("market_brief", "Market brief") == "doc"


async def test_probe_live_url_dead_host_reports_not_ok():
    ev = await probe_live_url("http://nonexistent.invalid.test")
    assert ev["ok"] is False
    assert ev["error"]

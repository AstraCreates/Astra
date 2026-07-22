import json

import pytest

from backend import company_os
from backend.company_os_copilot import _build_prompt, coordinate_turn
from backend.tools.intent_classifier import IntentClassification, IntentStep


def _no_launch(monkeypatch):
    # Routing is what's under test here; mission execution is covered by
    # test_company_os_runner.py, so keep launch_mission a no-op.
    monkeypatch.setattr("backend.company_os_copilot.launch_mission", lambda *_a, **_k: False)


def _mock_classification(monkeypatch, classification: IntentClassification):
    monkeypatch.setattr("backend.company_os_copilot.classify_intent", lambda *_a, **_k: classification)


@pytest.mark.asyncio
async def test_answer_kind_replies_without_dispatching(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="answer"))

    def fail_dispatch(*_a, **_k):
        raise AssertionError("an answer-kind classification must never dispatch")
    monkeypatch.setattr("backend.company_os_copilot.dispatch_intent", fail_dispatch)
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"initiative_id": None, "reply": "Nothing's running yet -- what should I start?"}
    ))

    result = await coordinate_turn("acme", "what were the results")

    assert result["dispatch"] is None
    assert result["message"] == "Nothing's running yet -- what should I start?"
    state = company_os.get_company_os("acme")
    assert state["initiatives"] == []
    assert state["conversation"][-1]["message"] == result["message"]


@pytest.mark.asyncio
async def test_negated_kind_acknowledges_without_an_llm_call_or_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="negated"))

    def fail_anything(*_a, **_k):
        raise AssertionError("negation must be handled without any further LLM call or dispatch")
    monkeypatch.setattr("backend.company_os_copilot.dispatch_intent", fail_anything)
    monkeypatch.setattr("backend.tools._llm.generate", fail_anything)

    result = await coordinate_turn("acme", "don't build a website yet, just tell me what you found")

    assert result["dispatch"] is None
    assert "holding off" in result["message"].lower()


@pytest.mark.asyncio
async def test_mcp_command_kind_replies_without_dispatching(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="mcp_command"))

    def fail_dispatch(*_a, **_k):
        raise AssertionError("an mcp_command classification must never dispatch a squad")
    monkeypatch.setattr("backend.company_os_copilot.dispatch_intent", fail_dispatch)
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"initiative_id": None, "reply": "I can't approve that from chat yet -- use the Approvals panel."}
    ))

    result = await coordinate_turn("acme", "approve the pending task")

    assert result["dispatch"] is None
    assert "approvals" in result["message"].lower()


@pytest.mark.asyncio
async def test_work_kind_dispatches_using_the_classifier_departments_directly(tmp_path, monkeypatch):
    """The classifier decides departments; no separate capability-extraction
    LLM call happens anymore."""
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="work", steps=[
        IntentStep(text="create a website about blackstone", department="product_technical"),
    ]))
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"initiative_id": None, "reply": "On it -- building a site about Blackstone now."}
    ))

    result = await coordinate_turn("acme", "create a website about blackstone")

    assert result["dispatch"] is not None
    assert result["dispatch"]["department"] == "product_technical"
    state = company_os.get_company_os("acme")
    assert state["initiatives"]


@pytest.mark.asyncio
async def test_compound_work_dispatches_a_primary_mission_and_a_handoff(tmp_path, monkeypatch):
    """Confirmed live before this rewrite: a compound "what is X ... then
    create a site" request got answered as a status check and silently
    dropped the second clause. The classifier now returns both steps
    directly; dispatch_intent's existing handoff-mission mechanism (already
    used for other multi-capability requests) picks up the second one with
    no new dispatch logic needed."""
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="work", steps=[
        IntentStep(text="what is Blackstone the company and how do they make money", department="research"),
        IntentStep(text="create a site to display the results of the research", department="product_technical"),
    ]))
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"initiative_id": None, "reply": "I'll research Blackstone first, then build a site around it."}
    ))

    result = await coordinate_turn("acme", "what is Blackstone the company and how do they make money "
                                            "then create a site to display the results of the research")

    assert result["dispatch"] is not None
    assert result["dispatch"]["department"] == "research"
    assert result["dispatch"]["handoff_missions"]
    assert result["dispatch"]["handoff_missions"][0]["department"] == "product_technical"


@pytest.mark.asyncio
async def test_a_total_classifier_failure_still_dispatches_instead_of_blocking(tmp_path, monkeypatch):
    """intent_classifier.classify_intent() falls back to a single
    unclassified step (department="") when every provider attempt fails.
    coordinate_turn must still produce a real dispatch (to whatever default
    department route_work_request's own tie-break picks) rather than ever
    leaving the founder stuck waiting on a clarifying question -- there is
    no clarification mechanism in this architecture at all."""
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="work", steps=[
        IntentStep(text="find out if a cookie clicker game can be monetized", department=""),
    ]))
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "not json at all")

    result = await coordinate_turn("acme", "find out if a cookie clicker game can be monetized")

    assert result["dispatch"] is not None
    state = company_os.get_company_os("acme")
    assert state["initiatives"]


@pytest.mark.asyncio
async def test_ground_and_reply_failure_falls_back_to_a_generated_plan_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="work", steps=[
        IntentStep(text="research Instacart", department="research"),
    ]))
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "not json at all")

    result = await coordinate_turn("acme", "research instacart")

    assert result["dispatch"] is not None
    assert "**Work plan**" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_reply_carries_the_squad_id_for_the_inline_plan_card(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    _mock_classification(monkeypatch, IntentClassification(kind="work", steps=[
        IntentStep(text="what is instacart", department="research"),
    ]))
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"initiative_id": None, "reply": "On it."}
    ))

    result = await coordinate_turn("acme", "what is instacart")

    assert result["dispatch"] is not None
    state = company_os.get_company_os("acme")
    last = state["conversation"][-1]
    assert last["kind"] == "plan"
    assert last["squad_id"] == result["dispatch"]["squad"]["squad_id"]


def test_grounded_prompt_injects_the_classifier_steps_and_forbids_cross_subject_answers():
    """The classifier decides WHAT department(s); this prompt's only jobs
    are continue-vs-new and reply-writing -- but the anti-leak guardrail from
    the old single-call design (a finding about a different company must
    never answer a question about this one) still has to hold for the
    "answer" kind's reply-writing instructions."""
    company = {
        "initiatives": [{"initiative_id": "i1", "name": "Northrop Grumman research", "department": "research", "state": "working"}],
        "squads": [{"squad_id": "s1", "initiative_id": "i1", "name": "Insights"}],
        "tasks": [{"task_id": "t1", "initiative_id": "i1"}],
        "artifacts": [{"task_id": "t1", "content": "Northrop Grumman makes money via defense contracts."}],
        "conversation": [],
    }
    classification = IntentClassification(kind="work", steps=[IntentStep(text="what is Palantir and how do they make money", department="research")])
    prompt = _build_prompt(company, "what is Palantir and how do they make money", classification)

    assert "Palantir" in prompt
    assert '"what is Palantir and how do they make money" -> research' in prompt

    answer_classification = IntentClassification(kind="answer")
    answer_prompt = _build_prompt(company, "what were the results", answer_classification)
    assert "never use a different initiative's finding just because one exists" in answer_prompt

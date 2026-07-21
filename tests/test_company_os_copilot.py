import json

import pytest

from backend import company_os
from backend.company_os_copilot import coordinate_turn
from backend.company_os_copilot import _classify_turn


def _no_launch(monkeypatch):
    # Routing is what's under test here; mission execution is covered by
    # test_company_os_runner.py, so keep launch_mission a no-op.
    monkeypatch.setattr("backend.company_os_copilot.launch_mission", lambda *_a, **_k: False)


@pytest.mark.asyncio
async def test_answer_action_replies_without_creating_an_initiative(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")

    def fail_dispatch(*_a, **_k):
        raise AssertionError("answer action must not dispatch a new initiative")
    monkeypatch.setattr("backend.company_os_copilot.dispatch_intent", fail_dispatch)
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"action": "answer", "initiative_id": None, "reply": "Nothing's running yet -- what should I start?"}
    ))

    result = await coordinate_turn("acme", "what were the results")

    assert result["dispatch"] is None
    assert result["message"] == "Nothing's running yet -- what should I start?"
    state = company_os.get_company_os("acme")
    assert state["initiatives"] == []
    assert state["conversation"][-1]["message"] == result["message"]


@pytest.mark.asyncio
async def test_continue_without_a_valid_work_request_asks_for_clarification(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    first = company_os.create_initiative("acme", "Big Pharma ML consulting viability", department="research", director="research")
    initiative_id = first["initiative_id"]

    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"action": "continue", "initiative_id": initiative_id, "reply": "Digging further into that now."}
    ))

    result = await coordinate_turn("acme", "results")

    assert result["dispatch"] is None
    assert "Work request needs one clarification" in result["message"]
    state = company_os.get_company_os("acme")
    assert len(state["initiatives"]) == 1  # no duplicate or blocked squad spawned


@pytest.mark.asyncio
async def test_malformed_llm_output_does_not_create_unrouted_work(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "not json at all")

    result = await coordinate_turn("acme", "find out if a cookie clicker game can be monetized")

    assert result["dispatch"] is None
    assert "Work request needs one clarification" in result["message"]
    state = company_os.get_company_os("acme")
    assert state["initiatives"] == []


@pytest.mark.asyncio
async def test_ambiguous_new_work_asks_a_structured_question(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")

    def fake_generate(prompt, *, model=None, **_kwargs):
        if model == "fast":
            return json.dumps({"action": "new", "initiative_id": None, "reply": "On it."})
        return json.dumps({
            "objective": "Build the MVP", "deliverables": [], "acceptance_criteria": [], "constraints": [],
            "entities": [], "dependencies": [], "primary_capability": "website", "required_capabilities": ["website"],
            "risk": "internal", "clarification_question": "Which platform should the MVP target?",
            "clarification_options": ["iOS", "Android", "Both"], "confidence": 0.9,
        })
    monkeypatch.setattr("backend.tools._llm.generate", fake_generate)

    result = await coordinate_turn("acme", "build me an MVP")

    assert result["dispatch"] is None
    state = company_os.get_company_os("acme")
    last = state["conversation"][-1]
    assert last["kind"] == "question"
    assert last["question"] == "Which platform should the MVP target?"
    assert last["options"] == ["iOS", "Android", "Both"]
    assert state["initiatives"] == []  # nothing dispatched while awaiting the answer

    # The founder answers. Even if the (mocked, stubborn) model tries to ask
    # ANOTHER clarifying question on this reply, the copilot must never chain
    # a second round -- that's the exact interrogation loop that made a plain
    # "what is X" ask take three rounds of increasingly irrelevant questions
    # in production before any research squad ever formed.
    captured_intent = {}

    def stubborn_generate(prompt, *, model=None, **_kwargs):
        if model == "fast":
            return json.dumps({"action": "new", "initiative_id": None, "reply": "Building it now."})
        captured_intent["prompt"] = prompt
        return json.dumps({
            "objective": "Build an iOS MVP", "deliverables": [], "acceptance_criteria": [], "constraints": [],
            "entities": [], "dependencies": [], "primary_capability": "website", "required_capabilities": ["website"],
            "risk": "internal", "clarification_question": "Which audience is this for?",
            "clarification_options": ["Consumers", "Businesses"], "confidence": 0.9,
        })
    monkeypatch.setattr("backend.tools._llm.generate", stubborn_generate)
    company_os.append_message("acme", "iOS", author="founder", role="user")

    result = await coordinate_turn("acme", "iOS")

    assert result["dispatch"] is not None  # dispatched despite the model wanting to ask again
    state = company_os.get_company_os("acme")
    assert not any(m.get("kind") == "question" and m["message"] != last["message"] for m in state["conversation"])
    # The original objective ("build the MVP") was merged with the founder's
    # terse reply ("iOS") into one coherent intent, not sent bare.
    assert "Build the MVP" in captured_intent["prompt"]
    assert "iOS" in captured_intent["prompt"]


def test_direct_work_requests_bypass_the_answer_classifier(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "should not run")
    assert _classify_turn({}, "Compare Cofounder.co to AstraCreates.com")["action"] == "new"
    assert _classify_turn({}, "Make a website for a competing company")["action"] == "new"

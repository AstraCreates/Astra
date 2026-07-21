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
async def test_continue_action_reuses_the_named_initiative(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    from backend.company_os_dispatch import dispatch_intent
    first = dispatch_intent("acme", "is a Big Pharma ML consulting company viable")
    initiative_id = first["initiative"]["initiative_id"]

    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: json.dumps(
        {"action": "continue", "initiative_id": initiative_id, "reply": "Digging further into that now."}
    ))

    result = await coordinate_turn("acme", "results")

    assert result["dispatch"]["initiative"]["initiative_id"] == initiative_id
    state = company_os.get_company_os("acme")
    assert len(state["initiatives"]) == 1  # no duplicate spawned


@pytest.mark.asyncio
async def test_malformed_llm_output_falls_back_to_starting_new_work(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    _no_launch(monkeypatch)
    company_os.create_company_os("acme", "founder", "Acme")
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "not json at all")

    result = await coordinate_turn("acme", "find out if a cookie clicker game can be monetized")

    assert result["dispatch"] is not None
    state = company_os.get_company_os("acme")
    assert len(state["initiatives"]) == 1


def test_direct_work_requests_bypass_the_answer_classifier(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: "should not run")
    assert _classify_turn({}, "Compare Cofounder.co to AstraCreates.com")["action"] == "new"
    assert _classify_turn({}, "Make a website for a competing company")["action"] == "new"

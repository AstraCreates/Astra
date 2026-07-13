import asyncio
import sys
import types

import pytest


def test_register_session_visible_false_stays_out_of_index(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.core.session_store import list_sessions, register_session

    register_session("visible_run", "founder_1", "Visible goal", visible=True)
    register_session("hidden_run", "founder_1", "Hidden goal", visible=False, kind="shadow")

    session_ids = {item["session_id"] for item in list_sessions("founder_1")}
    assert "visible_run" in session_ids
    assert "hidden_run" not in session_ids


def test_maybe_compare_shadow_run_marks_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.config.settings.supabase_url", "", raising=False)
    monkeypatch.setattr("backend.config.settings.supabase_key", "", raising=False)
    from backend.control_plane.temporal.shadow_runtime import maybe_compare_shadow_run
    from backend.core.session_store import append_event, get_session_meta, merge_session_meta, register_session

    register_session("run_live", "founder_1", "Ship it", visible=True)
    register_session("run_live__shadow", "founder_1", "Ship it", visible=False, kind="shadow")

    merge_session_meta("run_live", shadow_comparison_status="pending")
    merge_session_meta("run_live__shadow", shadow_parent_run_id="run_live", shadow_mode=True)

    append_event("run_live", 1, {"type": "run_started"})
    append_event("run_live", 2, {"type": "goal_done"})
    append_event("run_live__shadow", 1, {"type": "run_started"})
    append_event("run_live__shadow", 2, {"type": "goal_done"})

    compared = maybe_compare_shadow_run("run_live", "run_live__shadow")

    meta = get_session_meta("run_live") or {}
    assert compared is True
    assert meta["shadow_comparison_status"] == "completed"
    assert meta["shadow_run_id"] == "run_live__shadow"
    assert "shadow_comparison_id" in meta


def test_maybe_compare_shadow_run_is_idempotent_after_first_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.config.settings.supabase_url", "", raising=False)
    monkeypatch.setattr("backend.config.settings.supabase_key", "", raising=False)
    from backend.control_plane.temporal.shadow_runtime import maybe_compare_shadow_run
    from backend.core.session_store import append_event, get_session_meta, merge_session_meta, register_session

    register_session("run_once", "founder_1", "Ship it", visible=True)
    register_session("run_once__shadow", "founder_1", "Ship it", visible=False, kind="shadow")

    merge_session_meta("run_once", shadow_comparison_status="pending")
    merge_session_meta("run_once__shadow", shadow_parent_run_id="run_once", shadow_mode=True)

    append_event("run_once", 1, {"type": "goal_done"})
    append_event("run_once__shadow", 1, {"type": "goal_done"})

    first = maybe_compare_shadow_run("run_once", "run_once__shadow")
    second = maybe_compare_shadow_run("run_once", "run_once__shadow")

    meta = get_session_meta("run_once") or {}
    assert first is True
    assert second is False
    assert meta["shadow_comparison_status"] == "completed"


@pytest.mark.asyncio
async def test_shadow_mode_blocks_external_tools():
    if sys.version_info < (3, 10):
        pytest.skip("backend.core.agent annotations require Python 3.10+")
    fake_openai = sys.modules.setdefault("openai", types.ModuleType("openai"))
    if not hasattr(fake_openai, "OpenAI"):
        fake_openai.OpenAI = object
    from backend.core.agent import Agent, AgentContext

    called = {"value": False}

    async def _should_not_run(**kwargs):
        called["value"] = True
        return {"ok": True}

    agent = Agent(name="web", role="web", tools={"vercel_deploy": _should_not_run})
    ctx = AgentContext(goal="ship", founder_id="founder_1", session_id="shadow_1", shadow_mode=True)

    result = await agent._execute_tool("vercel_deploy", {"project": "demo"}, ctx)

    assert called["value"] is False
    assert result["guardrail"] == "shadow_no_side_effects"
    assert result["shadow_mode"] is True

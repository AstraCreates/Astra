"""Regression test: start_continue_run() built its constraints dict without ever
setting unlimited_credits, unlike the initial start_run (which does), so
scale/beta founders lost their reservation bypass on every continuation run."""
import pytest

from backend.control_plane import start_run as start_run_mod


@pytest.mark.asyncio
async def test_continue_run_constraints_carry_unlimited_credits_for_scale_plan(monkeypatch):
    captured = {}

    def fake_merge_session_meta(session_id, **fields):
        captured.update(fields)

    monkeypatch.setattr("backend.core.session_store.get_session_meta", lambda sid: {"founder_id": "f1"})
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", fake_merge_session_meta)
    monkeypatch.setattr("backend.core.session_store.register_session", lambda **kw: None)
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda fid: {"plan": "scale"})

    try:
        await start_run_mod.start_continue_run(
            founder_id="f1",
            instruction="keep going",
            prior_session_id="s_prior",
            request=None,
            validate_prior=False,
        )
    except Exception:
        pass  # downstream dispatch isn't mocked -- only the constraints capture matters here

    assert captured.get("constraints", {}).get("unlimited_credits") is True


@pytest.mark.asyncio
async def test_continue_run_constraints_false_for_starter_plan(monkeypatch):
    captured = {}

    def fake_merge_session_meta(session_id, **fields):
        captured.update(fields)

    monkeypatch.setattr("backend.core.session_store.get_session_meta", lambda sid: {"founder_id": "f1"})
    monkeypatch.setattr("backend.core.session_store.merge_session_meta", fake_merge_session_meta)
    monkeypatch.setattr("backend.core.session_store.register_session", lambda **kw: None)
    monkeypatch.setattr("backend.accounts.get_or_create_org", lambda fid: {"plan": "starter"})

    try:
        await start_run_mod.start_continue_run(
            founder_id="f1",
            instruction="keep going",
            prior_session_id="s_prior",
            request=None,
            validate_prior=False,
        )
    except Exception:
        pass

    assert captured.get("constraints", {}).get("unlimited_credits") is False

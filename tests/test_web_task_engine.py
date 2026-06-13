import asyncio
import json

import pytest

from backend.tools.web_tasks.base import WebTaskAdapter
from backend.tools.web_tasks.engine import (
    _normalize_request,
    _run_composite_saas_task,
    create_web_task_session,
    resume_web_task_session,
    run_web_task,
)
from backend.tools.web_tasks.models import WebTaskRequest, WebTaskSnapshot
from backend.tools.web_tasks.store import load_snapshot, save_snapshot, snapshot_path


class _CompletedAdapter(WebTaskAdapter):
    service = "fake"
    supported_task_types = ("login_or_signup",)

    async def run(self, ctx):
        await ctx.add_check("completed")
        return await ctx.complete({"merged_credentials": dict(ctx.credentials)})


class _NeedsUserAdapter(WebTaskAdapter):
    service = "fake"
    supported_task_types = ("retrieve_api_key",)

    async def run(self, ctx):
        return await ctx.needs_user(
            "missing_credentials",
            "Need credentials",
            [{"key": "password", "label": "Password", "type": "password"}],
        )


class _UnverifiedAdapter(WebTaskAdapter):
    service = "fake"
    supported_task_types = ("qa_flow",)

    async def run(self, ctx):
        return await ctx.complete({"attempted": True})


def test_normalize_request_coerces_success_criteria_and_ids():
    request = _normalize_request(
        task_type="retrieve_api_key",
        service="vercel",
        goal="Get deploy token",
        success_criteria="deploy_token_extracted",
        session_id="",
        task_id="",
    )

    assert request.success_criteria == ["deploy_token_extracted"]
    assert request.task_id
    assert request.session_id == request.task_id


@pytest.mark.asyncio
async def test_run_web_task_merges_credentials_and_persists_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.tools.web_tasks.base.load_credentials", lambda founder_id, service: {"email": "stored@example.com", "password": "stored"})
    monkeypatch.setattr("backend.tools.web_tasks.engine.resolve_adapter", lambda service, task_type: _CompletedAdapter())

    result = await run_web_task(
        task_type="login_or_signup",
        service="fake",
        goal="Log in",
        success_criteria=["completed"],
        credentials={"password": "explicit", "username": "override-user"},
        founder_id="founder-1",
        session_id="session-1",
        task_id="task-1",
    )

    assert result["status"] == "completed"
    assert result["artifacts"]["merged_credentials"]["email"] == "stored@example.com"
    assert result["artifacts"]["merged_credentials"]["password"] == "explicit"
    assert result["artifacts"]["merged_credentials"]["username"] == "override-user"
    snapshot = load_snapshot("session-1", "task-1")
    assert snapshot is not None
    assert snapshot.status == "completed"
    assert snapshot_path("session-1", "task-1").exists()


@pytest.mark.asyncio
async def test_run_web_task_needs_user_persists_blocker(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.tools.web_tasks.base.load_credentials", lambda founder_id, service: {})
    monkeypatch.setattr("backend.tools.web_tasks.engine.resolve_adapter", lambda service, task_type: _NeedsUserAdapter())

    result = await run_web_task(
        task_type="retrieve_api_key",
        service="fake",
        goal="Get key",
        success_criteria=["api key"],
        founder_id="founder-2",
        session_id="session-2",
        task_id="task-2",
    )

    assert result["status"] == "needs_user"
    assert result["blocker"]["kind"] == "missing_credentials"
    snapshot = load_snapshot("session-2", "task-2")
    assert snapshot is not None
    assert snapshot.status == "needs_user"
    assert snapshot.blocker.kind == "missing_credentials"


@pytest.mark.asyncio
async def test_run_web_task_does_not_complete_without_required_checks(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr("backend.tools.web_tasks.base.load_credentials", lambda founder_id, service: {})
    monkeypatch.setattr("backend.tools.web_tasks.engine.resolve_adapter", lambda service, task_type: _UnverifiedAdapter())

    result = await run_web_task(
        task_type="qa_flow",
        service="fake",
        goal="Verify dashboard",
        success_criteria=["dashboard_verified"],
        founder_id="founder-unverified",
        session_id="session-unverified",
        task_id="task-unverified",
    )

    assert result["status"] == "blocked"
    assert "missing checks" in result["blocker"]["message"]


@pytest.mark.asyncio
async def test_resume_web_task_session_updates_snapshot_and_restarts(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    calls = {"ran": 0}

    async def fake_background_run(request):
        calls["ran"] += 1

    monkeypatch.setattr("backend.tools.web_tasks.engine._background_run", fake_background_run)

    request = WebTaskRequest(
        task_type="retrieve_api_key",
        service="fake",
        goal="Get key",
        success_criteria=["api key"],
        founder_id="founder-3",
        session_id="session-3",
        task_id="task-3",
    )
    snapshot = WebTaskSnapshot(task_id="task-3", request=request, status="needs_user")
    save_snapshot(snapshot)
    session = create_web_task_session("task-3")
    session["status"] = "needs_user"
    session["request"] = request
    session["last_result"] = {"status": "needs_user", "resume_token": "task-3"}

    assert resume_web_task_session("task-3", {"password": "resume-secret"}) is True
    await asyncio.sleep(0)

    resumed = load_snapshot("session-3", "task-3")
    assert resumed is not None
    assert resumed.credentials["password"] == "resume-secret"
    assert calls["ran"] == 1


@pytest.mark.asyncio
async def test_background_run_preserves_agent_context(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    captured = {}

    async def fake_run_web_task(**kwargs):
        captured.update(kwargs)
        return {
            "status": "completed",
            "service": kwargs["service"],
            "task_type": kwargs["task_type"],
            "artifacts": {},
            "evidence": {"final_url": "", "state": "", "checks_passed": [], "screenshots": [], "page_summary": ""},
            "blocker": {"kind": "", "message": "", "fields": []},
            "resume_token": kwargs["task_id"],
        }

    monkeypatch.setattr("backend.tools.web_tasks.engine.run_web_task", fake_run_web_task)

    request = WebTaskRequest(
        task_type="retrieve_api_key",
        service="fake",
        goal="Get key",
        founder_id="founder-3",
        session_id="session-3b",
        task_id="task-3b",
        agent="technical",
    )

    from backend.tools.web_tasks.engine import _background_run

    await _background_run(request)

    assert captured["agent"] == "technical"
    assert captured["session_id"] == "session-3b"


@pytest.mark.asyncio
async def test_composite_saas_task_returns_combined_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    async def fake_run_web_task(**kwargs):
        service = kwargs["service"]
        return {
            "status": "completed",
            "service": service,
            "task_type": kwargs["task_type"],
            "artifacts": {service: {"ok": True, "service": service}},
            "evidence": {"final_url": "", "state": "", "checks_passed": [], "screenshots": [], "page_summary": ""},
            "blocker": {"kind": "", "message": "", "fields": []},
            "resume_token": kwargs["task_id"],
        }

    monkeypatch.setattr("backend.tools.web_tasks.engine.run_web_task", fake_run_web_task)

    request = _normalize_request(
        task_type="provision_saas_build_stack",
        service="saas_build_stack",
        goal="Provision build stack",
        success_criteria=["github_authenticated", "deploy_token_extracted", "project_keys_extracted"],
        founder_id="founder-4",
        session_id="session-4",
        task_id="task-4",
    )
    snapshot = WebTaskSnapshot(task_id="task-4", request=request)
    from backend.tools.web_tasks.base import WebTaskContext

    ctx = WebTaskContext(request=request, snapshot=snapshot)
    result = await _run_composite_saas_task(ctx)

    assert result.status == "completed"
    assert result.artifacts["github"]["service"] == "github"
    assert result.artifacts["vercel"]["service"] == "vercel"
    assert result.artifacts["supabase"]["service"] == "supabase"

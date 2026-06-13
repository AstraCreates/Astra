from types import SimpleNamespace

import pytest

from backend.tools.web_tasks.models import WebTaskRequest, WebTaskSnapshot
from backend.tools.web_tasks.state_machine import run_generic_web_task


class _FakePage:
    def __init__(self, url: str, body_text: str):
        self.url = url
        self._body_text = body_text

    async def inner_text(self, selector: str):
        assert selector == "body"
        return self._body_text

    async def fill(self, *args, **kwargs):
        return None

    async def click(self, *args, **kwargs):
        return None


class _FakeCtx:
    def __init__(self, request: WebTaskRequest, page: _FakePage):
        self.request = request
        self.snapshot = WebTaskSnapshot(task_id=request.task_id, request=request, credentials=dict(request.credentials))
        self._page = page
        self.credentials = self.snapshot.credentials
        self.checks: list[str] = []
        self.completed = None

    async def goto(self, url: str, state=None):
        self._page.url = url

    async def page(self):
        return self._page

    async def detect_human_blocker(self):
        return None

    async def maybe_handle_email_verification(self):
        return False

    async def add_check(self, check: str):
        self.checks.append(check)

    async def complete(self, artifacts):
        self.completed = artifacts
        return SimpleNamespace(status="completed", artifacts=artifacts)

    async def needs_user(self, kind, message, fields):
        return SimpleNamespace(status="needs_user", blocker={"kind": kind, "message": message, "fields": fields})

    async def execute_vision_fallback(self, goal: str):
        return False

    async def set_state(self, state, note: str = ""):
        return None

    async def block(self, message: str):
        return SimpleNamespace(status="blocked", blocker={"message": message})


@pytest.mark.asyncio
async def test_generic_state_machine_extracts_secret_when_goal_requests_it():
    request = WebTaskRequest(
        task_type="generic",
        service="generic",
        goal="Log in and retrieve the API key",
        success_criteria=[],
        start_url="https://example.com/settings/api",
        task_id="generic-1",
    )
    page = _FakePage("https://example.com/settings/api", 'Your API key is {"token":"abcdefghijklmnopqrstuvwxyz1234567890ABCDE"}')
    ctx = _FakeCtx(request, page)

    result = await run_generic_web_task(ctx)

    assert result.status == "completed"
    assert "generic_token" in ctx.checks
    assert "extracted" in ctx.completed["generic"]


@pytest.mark.asyncio
async def test_generic_state_machine_accepts_authenticated_dashboard_without_explicit_criteria():
    request = WebTaskRequest(
        task_type="generic",
        service="generic",
        goal="Sign in and reach the dashboard",
        success_criteria=[],
        start_url="https://example.com/app",
        task_id="generic-2",
    )
    page = _FakePage("https://example.com/dashboard", "Welcome to your account dashboard")
    ctx = _FakeCtx(request, page)

    result = await run_generic_web_task(ctx)

    assert result.status == "completed"
    assert "authenticated_state_detected" in ctx.checks

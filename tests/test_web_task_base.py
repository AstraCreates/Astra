from types import SimpleNamespace

import pytest

from backend.tools.web_tasks.base import WebTaskContext
from backend.tools.web_tasks.models import WebTaskRequest, WebTaskSnapshot


class _FakeKeyboard:
    def __init__(self):
        self.pressed: list[str] = []

    async def press(self, key: str):
        self.pressed.append(key)


class _FakePage:
    def __init__(self, body_text: str):
        self.url = "https://example.com/challenge"
        self._body_text = body_text
        self.keyboard = _FakeKeyboard()
        self.filled: list[tuple[str, str]] = []
        self.injected_tokens: list[str] = []

    async def inner_text(self, selector: str):
        assert selector == "body"
        return self._body_text

    async def fill(self, selector: str, value: str, timeout: int | None = None):
        self.filled.append((selector, value))

    async def evaluate(self, script: str, arg=None):
        if arg is None:
            return "site-key-1234567890"
        self.injected_tokens.append(arg)
        return None


def _ctx_for(page: _FakePage, *, input_data: dict | None = None) -> WebTaskContext:
    request = WebTaskRequest(
        task_type="retrieve_deploy_token",
        service="vercel",
        goal="Get Vercel deploy token",
        founder_id="founder-test",
        session_id="session-test",
        task_id="task-test",
    )
    snapshot = WebTaskSnapshot(
        task_id="task-test",
        request=request,
        credentials=dict(input_data or {}),
        input_data=dict(input_data or {}),
    )
    browser = SimpleNamespace(_page=page, _started=False)
    return WebTaskContext(request=request, snapshot=snapshot, browser=browser)


@pytest.mark.asyncio
async def test_detect_human_blocker_uses_resumed_otp(monkeypatch):
    page = _FakePage("Enter your two-factor authentication code to continue.")
    ctx = _ctx_for(page, input_data={"otp_code": "123456"})

    async def fake_set_state(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ctx, "set_state", fake_set_state)

    blocker = await ctx.detect_human_blocker()

    assert blocker is None
    assert ("input[autocomplete='one-time-code']", "123456") in page.filled
    assert page.keyboard.pressed == ["Enter"]


@pytest.mark.asyncio
async def test_detect_human_blocker_solves_turnstile_when_capsolver_is_configured(monkeypatch):
    page = _FakePage("Please verify you are human before continuing.")
    ctx = _ctx_for(page)

    async def fake_set_state(*_args, **_kwargs):
        return None

    async def fake_to_thread(fn, *args, **kwargs):
        return "turnstile-token-123"

    monkeypatch.setattr(ctx, "set_state", fake_set_state)
    monkeypatch.setattr("backend.tools.web_tasks.base.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("backend.config.settings.capsolver_api_key", "capsolver-test-key")

    blocker = await ctx.detect_human_blocker()

    assert blocker is None
    assert page.injected_tokens == ["turnstile-token-123"]


@pytest.mark.asyncio
async def test_detect_human_blocker_reports_email_verification_inputs(monkeypatch):
    page = _FakePage("Check your email. We sent a code to continue.")
    ctx = _ctx_for(page)

    async def fake_maybe_handle_email_verification():
        return False

    monkeypatch.setattr(ctx, "maybe_handle_email_verification", fake_maybe_handle_email_verification)

    blocker = await ctx.detect_human_blocker()

    assert blocker is not None
    assert blocker.kind == "email_verification"
    assert [field["key"] for field in blocker.fields] == ["otp_code", "imap_password"]


@pytest.mark.asyncio
async def test_maybe_handle_email_verification_falls_back_to_gmail_webmail(monkeypatch):
    page = _FakePage("Check your email. We sent a code to continue.")
    ctx = _ctx_for(page, input_data={"email": "astratestingmail@gmail.com", "password": "Astra123!"})

    async def fake_check_email_for_verification(*_args, **_kwargs):
        return {"link": "", "code": ""}

    async def fake_webmail(email: str, password: str, service: str):
        assert email == "astratestingmail@gmail.com"
        assert password == "Astra123!"
        assert service == "vercel"
        return True

    monkeypatch.setattr("backend.tools.web_tasks.base.check_email_for_verification", fake_check_email_for_verification)
    monkeypatch.setattr(ctx, "_maybe_handle_gmail_webmail_verification", fake_webmail)

    handled = await ctx.maybe_handle_email_verification()

    assert handled is True


@pytest.mark.asyncio
async def test_maybe_handle_email_verification_prefers_gmail_api_result(monkeypatch):
    page = _FakePage("Check your email. We sent a code to continue.")
    ctx = _ctx_for(
        page,
        input_data={
            "email": "astratestingmail@gmail.com",
            "access_token": "ya29.token",
            "refresh_token": "refresh-token",
        },
    )
    async def fake_set_state(*_args, **_kwargs):
        return None

    monkeypatch.setattr("backend.tools.web_tasks.base.fetch_gmail_verification", lambda *args, **kwargs: {"code": "654321", "link": ""})
    monkeypatch.setattr(ctx, "set_state", fake_set_state)

    handled = await ctx.maybe_handle_email_verification()

    assert handled is True
    assert ("input[autocomplete='one-time-code'], input[name*='code' i], input[id*='code' i]", "654321") in page.filled

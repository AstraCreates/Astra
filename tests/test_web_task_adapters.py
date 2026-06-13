from types import SimpleNamespace

import pytest

from backend.tools.web_tasks.adapters.github import GitHubAdapter
from backend.tools.web_tasks.adapters.klaviyo import KlaviyoAdapter
from backend.tools.web_tasks.adapters.sendgrid import SendGridAdapter
from backend.tools.web_tasks.adapters.square_sandbox import SquareSandboxAdapter
from backend.tools.web_tasks.adapters.supabase import SupabaseAdapter
from backend.tools.web_tasks.adapters.vercel import VercelAdapter


class _FakeElement:
    def __init__(self, value: str = "", text: str = "", attrs: dict | None = None):
        self.value = value
        self.text = text
        self.attrs = attrs or {}

    async def get_attribute(self, name: str):
        if name == "value" and self.value:
            return self.value
        return self.attrs.get(name)

    async def inner_text(self):
        return self.text or self.value


class _FakePage:
    def __init__(self, url: str, body_text: str = "", elements: dict[str, _FakeElement | None] | None = None, evaluate_result=None):
        self.url = url
        self._body_text = body_text
        self.elements = elements or {}
        self._evaluate_result = evaluate_result or {}
        self.clicked: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.selected: list[tuple[str, str]] = []

    async def click(self, selector: str, timeout: int | None = None):
        self.clicked.append(selector)

    async def fill(self, selector: str, value: str, timeout: int | None = None):
        self.filled.append((selector, value))

    async def wait_for_load_state(self, state: str, timeout: int | None = None):
        return None

    async def select_option(self, selector: str, value=None, index=None, timeout: int | None = None):
        picked = value if value is not None else str(index)
        self.selected.append((selector, str(picked)))

    async def query_selector(self, selector: str):
        return self.elements.get(selector)

    async def inner_text(self, selector: str):
        assert selector == "body"
        return self._body_text

    async def evaluate(self, script: str):
        return self._evaluate_result


class _FakeCtx:
    def __init__(self, task_type: str, page: _FakePage, credentials: dict | None = None, metadata: dict | None = None):
        self.request = SimpleNamespace(task_type=task_type, metadata=metadata or {}, start_url="")
        self._page = page
        self.credentials = dict(credentials or {})
        self.checks: list[str] = []
        self.persisted: list[tuple[str, dict]] = []
        self.snapshot = SimpleNamespace(artifacts={}, current_url="", evidence=SimpleNamespace(final_url=""))

    async def page(self):
        return self._page

    async def goto(self, url: str, state=None):
        self._page.url = url
        self.snapshot.current_url = url

    async def add_check(self, check: str):
        self.checks.append(check)

    async def complete(self, artifacts: dict):
        return SimpleNamespace(status="completed", artifacts=artifacts)

    async def block(self, message: str):
        return SimpleNamespace(status="blocked", blocker={"message": message})

    async def needs_user(self, kind: str, message: str, fields: list[dict]):
        return SimpleNamespace(status="needs_user", blocker={"kind": kind, "message": message, "fields": fields})

    def persist_credentials(self, service: str, creds: dict):
        self.persisted.append((service, creds))

    async def detect_human_blocker(self):
        return None

    async def set_state(self, state, note: str = ""):
        return None


@pytest.mark.asyncio
async def test_github_adapter_extracts_personal_access_token(monkeypatch):
    adapter = GitHubAdapter()

    async def fake_submit_login_form(ctx, *args, **kwargs):
        ctx._page.url = "https://github.com/dashboard"

    monkeypatch.setattr(adapter, "_submit_login_form", fake_submit_login_form)

    page = _FakePage(
        "https://github.com/login",
        elements={
            "input[value^='github_pat_']": _FakeElement(value="github_pat_123456789012345678901234567890"),
        },
    )
    ctx = _FakeCtx("retrieve_api_key", page, credentials={"email": "founder@example.com", "password": "secret"})

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["github"]["token"].startswith("github_pat_")
    assert "github_token_extracted" in ctx.checks
    assert ctx.persisted == [("github", {"token": "github_pat_123456789012345678901234567890"})]


@pytest.mark.asyncio
async def test_vercel_adapter_extracts_deploy_token(monkeypatch):
    adapter = VercelAdapter()

    async def fake_ensure_logged_in(ctx):
        return None

    monkeypatch.setattr(adapter, "_ensure_logged_in", fake_ensure_logged_in)

    page = _FakePage(
        "https://vercel.com/account/tokens",
        elements={
            "input[readonly]": _FakeElement(value="vercel_token_123456789012345"),
        },
    )
    ctx = _FakeCtx("retrieve_deploy_token", page)

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["vercel"]["token"] == "vercel_token_123456789012345"
    assert "deploy_token_extracted" in ctx.checks
    assert ctx.persisted == [("vercel", {"token": "vercel_token_123456789012345"})]


@pytest.mark.asyncio
async def test_vercel_adapter_handles_email_then_password_login():
    adapter = VercelAdapter()
    page = _FakePage("https://vercel.com/login")
    ctx = _FakeCtx(
        "retrieve_deploy_token",
        page,
        credentials={"email": "founder@example.com", "password": "secret"},
    )

    await adapter._submit_vercel_login(ctx)

    assert ("input[type='email'], input[name='email']", "founder@example.com") in page.filled
    assert ("input[type='password']", "secret") in page.filled
    assert page.clicked[0].startswith("button:has-text('Continue with Email')")


@pytest.mark.asyncio
async def test_vercel_adapter_stops_after_email_code_prompt():
    adapter = VercelAdapter()
    page = _FakePage(
        "https://vercel.com/login",
        body_text="Check your email. We sent a code to continue.",
    )
    ctx = _FakeCtx(
        "retrieve_deploy_token",
        page,
        credentials={"email": "founder@example.com", "password": "secret"},
    )

    await adapter._submit_vercel_login(ctx)

    assert ("input[type='email'], input[name='email']", "founder@example.com") in page.filled
    assert ("input[type='password']", "secret") not in page.filled


@pytest.mark.asyncio
async def test_klaviyo_adapter_extracts_api_key(monkeypatch):
    adapter = KlaviyoAdapter()

    async def fake_ensure_logged_in(ctx):
        return None

    monkeypatch.setattr(adapter, "_ensure_logged_in", fake_ensure_logged_in)

    page = _FakePage(
        "https://www.klaviyo.com/account#api-keys-tab",
        elements={
            "input[value^='pk_']": _FakeElement(value="pk_12345678901234567890"),
        },
    )
    ctx = _FakeCtx("retrieve_api_key", page)

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["klaviyo"]["api_key"].startswith("pk_")
    assert "api_key_extracted" in ctx.checks
    assert ctx.persisted == [("klaviyo", {"api_key": "pk_12345678901234567890"})]


@pytest.mark.asyncio
async def test_sendgrid_adapter_needs_credentials_when_login_required():
    adapter = SendGridAdapter()
    page = _FakePage("https://app.sendgrid.com/login")
    ctx = _FakeCtx("retrieve_api_key", page, credentials={})

    result = await adapter._ensure_logged_in(ctx)

    assert result.status == "needs_user"
    assert result.blocker["kind"] == "missing_credentials"
    assert result.blocker["fields"][0]["key"] == "email"


@pytest.mark.asyncio
async def test_sendgrid_adapter_extracts_api_key(monkeypatch):
    adapter = SendGridAdapter()

    async def fake_ensure_logged_in(ctx):
        return None

    monkeypatch.setattr(adapter, "_ensure_logged_in", fake_ensure_logged_in)

    page = _FakePage(
        "https://app.sendgrid.com/settings/api_keys",
        elements={
            "[data-key-value]": _FakeElement(attrs={"data-key-value": "SG.abcdefghijklmnopqrstuv.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"}),
        },
    )
    ctx = _FakeCtx("retrieve_api_key", page)

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["sendgrid"]["api_key"].startswith("SG.")
    assert "api_key_extracted" in ctx.checks
    assert ctx.persisted[0][0] == "sendgrid"


@pytest.mark.asyncio
async def test_square_adapter_extracts_sandbox_token(monkeypatch):
    adapter = SquareSandboxAdapter()

    async def fake_ensure_logged_in(ctx):
        return None

    monkeypatch.setattr(adapter, "_ensure_logged_in", fake_ensure_logged_in)

    page = _FakePage(
        "https://developer.squareup.com/apps",
        elements={
            "input[value^='EAAAlb']": _FakeElement(value="EAAAlb123456789012345678901234567890"),
        },
    )
    ctx = _FakeCtx("retrieve_api_key", page)

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["square"]["access_token"].startswith("EAAAlb")
    assert "sandbox_token_extracted" in ctx.checks
    assert ctx.persisted == [("square", {"access_token": "EAAAlb123456789012345678901234567890", "environment": "sandbox"})]


@pytest.mark.asyncio
async def test_supabase_adapter_returns_project_artifacts_from_management_api(monkeypatch):
    adapter = SupabaseAdapter()

    monkeypatch.setattr(
        "backend.tools.web_tasks.adapters.supabase.supabase_create_project",
        lambda project_name: {
            "project_ref": "proj_123",
            "anon_key": "ey1234567890",
            "service_role_key": "ey_service_123456",
            "dashboard_url": "https://app.supabase.com/project/proj_123",
        },
    )

    page = _FakePage("https://app.supabase.com/")
    ctx = _FakeCtx("create_project", page, metadata={"project_name": "astra-app"})

    result = await adapter.run(ctx)

    assert result.status == "completed"
    assert result.artifacts["supabase"]["project_ref"] == "proj_123"
    assert "project_created" in ctx.checks
    assert "project_keys_extracted" in ctx.checks

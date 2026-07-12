import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from backend.main import app
from backend.api import routes
from backend.config import settings
from fastapi.testclient import TestClient
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_goal_endpoint_returns_session_id(mocker):
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value={"session_id": "abc123", "results": {}, "shared": {}})
    mocker.patch("backend.api.routes.get_orchestrator", return_value=mock_orch)
    mocker.patch("backend.api.routes.require_founder_access", return_value="f_001")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/goal", json={
            "founder_id": "f_001",
            "instruction": "Draft a founder agreement for AcmeCo",
            "constraints": {},
        })
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_goal_endpoint_dispatches_temporal_with_stable_session_id(monkeypatch):
    seen = {}

    async def fake_start_run(**kwargs):
        seen.update(kwargs)
        return {
            "workflow_id": f"astra-run/{kwargs['run_id']}",
            "run_id": kwargs["run_id"],
            "status": "started",
            "task_queue": "astra-runs-v1",
        }

    monkeypatch.setattr("backend.control_plane.start_run.assign_run_features", lambda *_args, **_kwargs: {"engine": "temporal"})
    monkeypatch.setattr("backend.control_plane.start_run._analyze_goal", lambda _instruction: ("", ""))
    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)
    monkeypatch.setattr("backend.control_plane.start_run.require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)
    monkeypatch.setattr("backend.control_plane.temporal.dispatch.start_run", fake_start_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/goal", json={
            "founder_id": "f_temporal",
            "instruction": "Implement a durable Temporal-backed run dispatch path for a founder operating workflow",
            "constraints": {"agents": ["technical"]},
        })

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "temporal"
    assert body["session_id"] == seen["run_id"]
    assert "goal" not in seen
    assert "constraints" not in seen

    from backend.core.session_store import get_session_meta

    meta = get_session_meta(body["session_id"])
    assert meta["engine"] == "temporal"
    assert meta["workflow_id"] == f"astra-run/{body['session_id']}"
    assert meta["constraints"]["agents"] == ["technical"]


@pytest.mark.asyncio
async def test_runs_endpoint_returns_canonical_run_response(monkeypatch):
    async def fake_start_run(body, request, *, run_id=None):
        return SimpleNamespace(
            to_response=lambda: {
                "run_id": "run_123",
                "session_id": "run_123",
                "status": "running",
                "engine": "temporal",
                "company_id": "company_1",
                "workspace_id": "workspace_1",
                "chapter_id": "chapter_1",
            }
        )

    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)
    monkeypatch.setattr("backend.control_plane.start_run.start_run", fake_start_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/runs", json={
            "founder_id": "founder_1",
            "instruction": "Build a durable run orchestration API",
            "constraints": {},
        })

    assert response.status_code == 200
    assert response.json()["run_id"] == "run_123"
    assert response.json()["session_id"] == "run_123"
    assert response.json()["engine"] == "temporal"


@pytest.mark.asyncio
async def test_runs_events_endpoint_returns_filtered_durable_events(monkeypatch):
    monkeypatch.setattr(routes, "_require_session_access", AsyncMock(return_value="founder_1"))
    monkeypatch.setattr(
        "backend.control_plane.projection.list_run_events",
        AsyncMock(return_value=[
            {"run_id": "run_123", "sequence": 3, "event_type": "run.created", "payload": {"type": "run.created"}},
            {"run_id": "run_123", "sequence": 4, "event_type": "agent_start", "payload": {"type": "agent_start"}},
        ]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/runs/run_123/events?after=2")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run_123"
    assert [event["sequence"] for event in body["events"]] == [3, 4]


@pytest.mark.asyncio
async def test_status_endpoint_returns_goal_info(mocker, monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    mocker.patch(
        "backend.api.routes.get_supabase",
        return_value=_mock_supabase_with_goal(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/status/g_abc123", headers={"x-astra-user-id": "f_001"})
    assert response.status_code == 200


def _mock_supabase_with_goal():
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g_abc123", "status": "in_progress", "instruction": "draft NDA", "founder_id": "f_001"}
    ]
    return mock


@pytest.mark.asyncio
async def test_stack_package_endpoint_compiles_goal_to_deployable_stack():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/stacks/package", json={
            "instruction": "Launch a waitlist SaaS with ICP research, pricing, landing page, and investor plan.",
            "company_stage": "idea",
            "company_name": "Astra",
        })

    assert response.status_code == 200
    body = response.json()
    assert body["stack_id"] == "idea_to_revenue"
    assert body["manifest"]["workflow"]["nodes"]
    assert body["execution_blueprint"]["execution_mode"] == "agent_department"
    assert body["proof"]["has_connector_plan"] is True


@pytest.mark.asyncio
async def test_gmail_oauth_url_returns_google_authorize_link(monkeypatch):
    access_calls = []

    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": access_calls.append((founder_id, min_role)) or founder_id)
    monkeypatch.setattr("backend.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("backend.config.settings.backend_url", "https://api.example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/gmail/oauth-url/founder-gmail")

    assert response.status_code == 200
    body = response.json()
    assert "accounts.google.com/o/oauth2/v2/auth" in body["url"]
    assert "access_type=offline" in body["url"]
    assert "prompt=consent" in body["url"]
    assert access_calls == [("founder-gmail", "admin")]


@pytest.mark.asyncio
async def test_gmail_callback_exchanges_code_and_stores_tokens(monkeypatch):
    stored = {}

    class _FakeHttpxClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None, timeout=None):
            return MagicMock(json=lambda: {
                "access_token": "ya29.access",
                "refresh_token": "refresh-123",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            })

        async def get(self, url, headers=None, timeout=None):
            return MagicMock(json=lambda: {"email": "founder@gmail.com"})

    monkeypatch.setattr("httpx.AsyncClient", _FakeHttpxClient)
    monkeypatch.setattr("backend.config.settings.google_client_id", "google-client-id")
    monkeypatch.setattr("backend.config.settings.google_client_secret", "google-client-secret")
    monkeypatch.setattr("backend.config.settings.backend_url", "https://api.example.com")
    monkeypatch.setattr("backend.config.settings.frontend_url", "https://app.example.com")
    monkeypatch.setattr("backend.provisioning.credentials_store.store_credentials", lambda founder_id, service, creds: stored.update({"founder_id": founder_id, "service": service, "creds": creds}))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/gmail/callback?code=oauth-code&state=founder-gmail")

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "https://app.example.com/integrations?gmail_connected=1"
    assert stored["founder_id"] == "founder-gmail"
    assert stored["service"] == "gmail"
    assert stored["creds"]["access_token"] == "ya29.access"
    assert stored["creds"]["refresh_token"] == "refresh-123"
    assert stored["creds"]["email"] == "founder@gmail.com"


@pytest.mark.asyncio
async def test_legacy_connector_routes_delegate_supported_services_to_web_task_engine(monkeypatch):
    calls = []

    async def fake_run_web_task_ws(websocket, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(routes, "_run_web_task_ws", fake_run_web_task_ws)

    sentinel_websocket = object()

    await routes.connect_github_stream(sentinel_websocket, "founder-1")
    await routes.connect_vercel_stream(sentinel_websocket, "founder-1")
    await routes.connect_sendgrid_stream(sentinel_websocket, "founder-1")
    await routes.connect_klaviyo_stream(sentinel_websocket, "founder-1")
    await routes.connect_printful_stream(sentinel_websocket, "founder-1")
    await routes.connect_yelp_stream(sentinel_websocket, "founder-1")
    await routes.connect_lemonsqueezy_stream(sentinel_websocket, "founder-1")
    await routes.connect_square_stream(sentinel_websocket, "founder-1")

    assert calls == [
        {
            "founder_id": "founder-1",
            "service": "github",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to GitHub and retrieve a personal access token.",
            "success_criteria": ["github_token_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "vercel",
            "task_type": "retrieve_deploy_token",
            "goal": "Sign in to Vercel and retrieve a deploy token.",
            "success_criteria": ["deploy_token_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "sendgrid",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to SendGrid and retrieve an API key.",
            "success_criteria": ["api_key_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "klaviyo",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to Klaviyo and retrieve an API key.",
            "success_criteria": ["api_key_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "printful",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to Printful and retrieve an API key.",
            "success_criteria": ["api_key_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "yelp",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to Yelp Fusion and retrieve an API key.",
            "success_criteria": ["api_key_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "lemonsqueezy",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to Lemon Squeezy and retrieve an API key.",
            "success_criteria": ["api_key_extracted"],
        },
        {
            "founder_id": "founder-1",
            "service": "square_sandbox",
            "task_type": "retrieve_api_key",
            "goal": "Sign in to Square Developer and retrieve a sandbox access token.",
            "success_criteria": ["sandbox_token_extracted"],
        },
    ]


@pytest.mark.asyncio
async def test_web_navigator_respond_resumes_with_session_access(monkeypatch):
    access_calls = []

    async def fake_require_session_access(request, session_id, min_role="viewer"):
        access_calls.append((session_id, min_role))
        return "founder-1"

    request_obj = MagicMock(session_id="session-real")
    snapshot = MagicMock()
    snapshot.request.session_id = "session-real"

    monkeypatch.setattr(routes, "_require_session_access", fake_require_session_access)
    monkeypatch.setattr("backend.tools.web_tasks.get_web_task_session", lambda task_id: {"request": request_obj})
    monkeypatch.setattr("backend.tools.web_tasks.store.load_snapshot", lambda session_id, task_id: snapshot)
    monkeypatch.setattr("backend.tools.web_tasks.resume_web_task_session", lambda task_id, fields: True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/web-navigator/respond/task-123",
            json={"fields": {"otp_code": "123456"}},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert access_calls == [("session-real", "viewer")]


@pytest.mark.asyncio
async def test_kill_session_requests_temporal_cancellation(monkeypatch):
    access_calls = []
    status_updates = []

    monkeypatch.setattr(
        routes,
        "require_founder_access",
        lambda request, founder_id, min_role="viewer": access_calls.append((founder_id, min_role)) or founder_id,
    )
    monkeypatch.setattr(
        "backend.core.session_store.get_session_meta",
        lambda session_id: {"founder_id": "founder-kill", "engine": "temporal"},
    )
    monkeypatch.setattr(
        "backend.core.session_store.update_session_status",
        lambda session_id, status: status_updates.append((session_id, status)),
    )
    monkeypatch.setattr("backend.core.cancellation.request_kill", lambda session_id: False)

    async def fake_cancel_temporal(session_id: str, meta) -> bool:
        assert meta["engine"] == "temporal"
        return session_id == "session-kill"

    monkeypatch.setattr(routes, "_cancel_temporal_session_if_needed", fake_cancel_temporal)
    monkeypatch.setattr(routes, "_reconcile_orphaned_agents", AsyncMock())
    monkeypatch.setattr(routes, "_teardown_workspace", AsyncMock())
    monkeypatch.setattr(routes, "publish", AsyncMock())

    result = await routes.kill_session("session-kill", MagicMock())

    assert result == {
        "ok": True,
        "killed": True,
        "session_id": "session-kill",
        "active_attempts_cancelled": True,
    }
    assert access_calls == [("founder-kill", "operator")]
    assert status_updates == [("session-kill", "killed")]


@pytest.mark.asyncio
async def test_web_navigator_respond_returns_404_when_task_is_not_waiting(monkeypatch):
    monkeypatch.setattr("backend.tools.web_tasks.get_web_task_session", lambda task_id: {})
    monkeypatch.setattr("backend.tools.web_tasks.store.load_snapshot", lambda session_id, task_id: None)
    monkeypatch.setattr("backend.tools.web_tasks.resume_web_task_session", lambda task_id, fields: False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/web-navigator/respond/task-404",
            json={"fields": {"otp_code": "123456"}},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_web_navigator_start_requires_founder_access_when_founder_id_present(monkeypatch):
    access_calls = []

    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": access_calls.append((founder_id, min_role)) or founder_id)
    monkeypatch.setattr("backend.tools.web_tasks.create_web_task_session", lambda task_id: {"task_id": task_id})
    monkeypatch.setattr(
        "backend.tools.web_tasks.start_web_task_background",
        lambda **kwargs: MagicMock(task_id=kwargs["task_id"]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/web-navigator/start",
            json={"goal": "Open dashboard", "founder_id": "founder-secure"},
        )

    assert response.status_code == 200
    assert access_calls == [("founder-secure", "viewer")]


@pytest.mark.asyncio
async def test_web_navigator_stream_requires_founder_access_when_session_has_founder(monkeypatch):
    access_calls = []
    session = {"event_queue": __import__("asyncio").Queue(), "request": MagicMock(founder_id="founder-stream")}
    await session["event_queue"].put(None)

    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": access_calls.append((founder_id, min_role)) or founder_id)
    monkeypatch.setattr("backend.tools.web_tasks.get_web_task_session", lambda task_id: session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/web-navigator/stream/task-stream")
        body = await response.aread()

    assert response.status_code == 200
    assert body == b""
    assert access_calls == [("founder-stream", "viewer")]


def test_web_task_websocket_reports_invalid_resume(monkeypatch):
    session = {"event_queue": __import__("asyncio").Queue()}
    session["event_queue"].put_nowait({
        "type": "web_task_needs_user",
        "task_id": "task-ws",
        "service": "sendgrid",
        "task_type": "retrieve_api_key",
        "blocker": {
            "kind": "2fa",
            "message": "Need a 2FA code",
            "fields": [{"key": "otp_code", "label": "2FA code", "type": "text"}],
        },
    })

    monkeypatch.setattr(
        "backend.tools.web_tasks.start_web_task_background",
        lambda **kwargs: MagicMock(task_id="task-ws"),
    )
    monkeypatch.setattr("backend.tools.web_tasks.get_web_task_session", lambda task_id: session)
    monkeypatch.setattr("backend.tools.web_tasks.resume_web_task_session", lambda task_id, fields: False)

    client = TestClient(app)
    with client.websocket_connect("/connect/sendgrid/stream/founder-1") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "interaction_needed"
        websocket.send_text('{"type":"founder_input","data":{"otp_code":"123456"}}')
        second = websocket.receive_json()
        assert second["type"] == "error"
        assert "not currently waiting" in second["message"]


@pytest.mark.asyncio
async def test_setup_service_normalizes_alias_and_merges_existing_credentials(monkeypatch):
    stored = {}
    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)
    monkeypatch.setattr("backend.provisioning.credentials_store.load_credentials", lambda founder_id, service: {"refresh_token": "keep-me"})
    monkeypatch.setattr(routes, "store_credentials", lambda founder_id, service, creds: stored.update({"founder_id": founder_id, "service": service, "creds": creds}))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/setup/service",
            json={"founder_id": "founder-1", "service": "googledocs", "credentials": {"access_token": "  token-1  ", "ignored": "x"}},
        )

    assert response.status_code == 200
    assert response.json()["service"] == "google_docs"
    assert stored == {
        "founder_id": "founder-1",
        "service": "google_docs",
        "creds": {"refresh_token": "keep-me", "access_token": "token-1"},
    }


@pytest.mark.asyncio
async def test_setup_service_rejects_empty_supported_credentials(monkeypatch):
    monkeypatch.setattr(routes, "require_founder_access", lambda request, founder_id, min_role="viewer": founder_id)
    monkeypatch.setattr("backend.provisioning.credentials_store.load_credentials", lambda founder_id, service: {})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/setup/service",
            json={"founder_id": "founder-1", "service": "resend", "credentials": {"api_key": "   "}},
        )

    assert response.status_code == 400
    assert "supported credential field" in response.json()["detail"]

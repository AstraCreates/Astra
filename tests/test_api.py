import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from backend.main import app
from backend.api import routes
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_goal_endpoint_returns_session_id(mocker):
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value={"session_id": "abc123", "results": {}, "shared": {}})
    mocker.patch("backend.api.routes.get_orchestrator", return_value=mock_orch)

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
async def test_status_endpoint_returns_goal_info(mocker):
    mocker.patch(
        "backend.api.routes.get_supabase",
        return_value=_mock_supabase_with_goal(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/status/g_abc123")
    assert response.status_code == 200


def _mock_supabase_with_goal():
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g_abc123", "status": "in_progress", "instruction": "draft NDA"}
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

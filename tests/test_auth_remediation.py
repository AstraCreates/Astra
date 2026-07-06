import json
import time

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.main import app


@pytest.fixture(autouse=True)
def strict_header_auth(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)


@pytest.mark.asyncio
async def test_deployment_routes_require_record_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.deployments.store import record_deployment

    record_deployment("session-secure", "founder_owner", "https://preview.vercel.app")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.get(
            "/deployments/session-secure",
            headers={"x-astra-user-id": "other_founder"},
        )
        allowed = await client.get(
            "/deployments/session-secure",
            headers={"x-astra-user-id": "founder_owner"},
        )

    assert blocked.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["founder_id"] == "founder_owner"


@pytest.mark.asyncio
async def test_deployment_list_dependency_rejects_cross_founder_and_allows_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.deployments.store import record_deployment

    record_deployment("session-list-secure", "founder_owner", "https://preview.vercel.app")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.get(
            "/deployments?founder_id=founder_owner",
            headers={"x-astra-user-id": "other_founder"},
        )
        allowed = await client.get(
            "/deployments?founder_id=founder_owner",
            headers={"x-astra-user-id": "founder_owner"},
        )

    assert blocked.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["deployments"][0]["session_id"] == "session-list-secure"


@pytest.mark.asyncio
async def test_model_settings_rejects_cross_founder_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/model-settings",
            json={
                "founder_id": "founder_owner",
                "agent_key": "research",
                "model": "deepseek/deepseek-v4-pro",
            },
            headers={"x-astra-user-id": "other_founder"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_model_settings_dependency_rejects_missing_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/model-settings?founder_id=founder_owner")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_model_settings_dependency_allows_valid_actor_update(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/model-settings",
            json={
                "founder_id": "founder_owner",
                "agent_key": "research",
                "model": "deepseek/deepseek-v4-pro",
            },
            headers={"x-astra-user-id": "founder_owner"},
        )

    assert response.status_code == 200
    assert response.json()["founder_id"] == "founder_owner"

    from backend.model_settings.store import get_model_override

    assert get_model_override("founder_owner", "research") == "deepseek/deepseek-v4-pro"


@pytest.mark.asyncio
async def test_teams_routes_authorize_claimed_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/teams",
            json={"name": "Secure Team", "founder_id": "founder_owner"},
            headers={"x-astra-user-id": "founder_owner"},
        )
        team_id = created.json()["team"]["id"]
        blocked = await client.post(
            f"/teams/{team_id}/invites",
            json={"founder_id": "founder_owner", "email": "new@example.com"},
            headers={"x-astra-user-id": "other_founder"},
        )

    assert created.status_code == 200
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_get_invite_does_not_mark_expired_invite(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.api.teams_routes import _load_store, _save_store

    expired_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    store = {
        "teams": {"team_1": {"id": "team_1", "name": "Secure Team", "members": []}},
        "invites": {
            "token_1": {
                "token": "token_1",
                "team_id": "team_1",
                "invited_by": "founder_owner",
                "email": "",
                "expires_at": expired_at,
                "status": "pending",
            }
        },
    }
    _save_store(store)

    from backend.api.teams_routes import get_invite

    with pytest.raises(HTTPException) as exc:
        await get_invite("token_1")

    assert exc.value.status_code == 410
    assert _load_store()["invites"]["token_1"]["status"] == "pending"


@pytest.mark.asyncio
async def test_status_route_requires_goal_owner(monkeypatch):
    class _Result:
        def __init__(self, data):
            self.data = data

    class _Query:
        def __init__(self, data):
            self._data = data

        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def execute(self):
            return _Result(self._data)

    class _DB:
        def table(self, name):
            if name == "goals":
                return _Query([{"id": "goal_1", "founder_id": "founder_owner"}])
            return _Query([])

    monkeypatch.setattr("backend.api.routes.get_supabase", lambda: _DB())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/status/goal_1",
            headers={"x-astra-user-id": "other_founder"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mcp_mutation_without_caller_rejects_instead_of_default_founder(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "astra_submit_goal",
                    "arguments": {"goal": "Build a launch plan"},
                },
            }),
        )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Unauthorized"


@pytest.mark.asyncio
async def test_mcp_sync_mutation_without_caller_rejects(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "astra_approve",
                    "arguments": {"session_id": "sess_1", "action_key": "deploy"},
                },
            }),
        )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Unauthorized"

import hashlib
import hmac
import json
import sys
import types

import pytest
from httpx import ASGITransport, AsyncClient

from backend.connector_sync_ledger import get_connector_sync_status
from backend.connector_webhooks import ingest_connector_webhook, normalize_connector_webhook_payload, verify_connector_webhook
from backend.tools.company_brain import get_company_brain


def test_connector_webhook_verifies_hmac_signature(monkeypatch):
    founder_id = "founder_webhook_verify"
    body = b'{"event_id":"evt_1"}'
    secret = "whsec_test"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(
        "backend.connector_webhooks.load_credentials",
        lambda fid, service: {"webhook_secret": secret} if fid == founder_id and service == "slack" else None,
    )

    verified = verify_connector_webhook(founder_id, "slack", body, {"x-astra-signature": signature})
    assert verified == {"ok": True, "method": "hmac_sha256"}


def test_connector_webhook_normalizes_slack_event():
    normalized = normalize_connector_webhook_payload("slack", {
        "event_id": "evt_slack_1",
        "event": {
            "type": "message",
            "channel": "C1",
            "ts": "123.456",
            "thread_ts": "123.000",
            "user": "U1",
            "text": "Engineering shipped the connector sync ledger.",
        },
    })

    assert normalized["event_id"] == "evt_slack_1"
    assert normalized["cursor"] == "123.456"
    assert normalized["records"][0]["title"] == "Slack #C1 123.456"
    assert normalized["records"][0]["thread_ts"] == "123.000"


def test_connector_webhook_ingests_and_records_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_webhook_ingest"

    result = ingest_connector_webhook(founder_id, "discord", {
        "event_id": "evt_discord_1",
        "message": {
            "id": "200",
            "content": "Design team finalized the new onboarding flow.",
            "channel_name": "design",
            "guild_name": "Astra HQ",
            "author": {"username": "maya"},
            "timestamp": "2026-05-02T00:00:00Z",
        },
    })

    assert result["ok"] is True
    assert result["records"] == 1
    brain = get_company_brain(founder_id)
    assert any("onboarding flow" in record["content"] for record in brain["records"])
    status = get_connector_sync_status(founder_id)
    assert status["sources"]["discord"]["mode"] == "webhook"
    assert status["sources"]["discord"]["webhook_events"] == 1
    assert status["sources"]["discord"]["cursor"] == "200"


@pytest.mark.asyncio
async def test_connector_webhook_route_ingests_verified_payload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = _test_app(monkeypatch)
    founder_id = "founder_webhook_route"
    secret = "whsec_route"
    monkeypatch.setattr(
        "backend.connector_webhooks.load_credentials",
        lambda fid, service: {"webhook_secret": secret} if fid == founder_id and service == "slack" else None,
    )
    payload = {
        "event_id": "evt_route_1",
        "event": {
            "type": "message",
            "channel": "C1",
            "ts": "300.1",
            "user": "U1",
            "text": "Sales stack needs CRM handoff.",
        },
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/brain/{founder_id}/webhooks/slack",
            content=body,
            headers={"x-astra-signature": signature, "content-type": "application/json"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["verification"]["method"] == "hmac_sha256"
    brain = get_company_brain(founder_id)
    assert any("CRM handoff" in record["content"] for record in brain["records"])


@pytest.mark.asyncio
async def test_connector_ingest_route_records_sync_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = _test_app(monkeypatch)
    founder_id = "founder_ingest_route"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/brain/{founder_id}/ingest",
            json={
                "source": "notion",
                "records": [{
                    "title": "Launch plan",
                    "content": "Notion contains the launch milestones and owner map.",
                    "kind": "page",
                    "canonical": True,
                }],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["ingested"] == 1
    status = get_connector_sync_status(founder_id)
    notion = status["sources"]["notion"]
    assert notion["status"] == "ok"
    assert notion["mode"] == "ingest"
    assert notion["last_imported"] == 1
    assert notion["history"][0]["mode"] == "ingest"


@pytest.mark.asyncio
async def test_connector_webhook_route_rejects_missing_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = _test_app(monkeypatch)
    monkeypatch.setattr("backend.connector_webhooks.load_credentials", lambda fid, service: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/brain/founder_missing/webhooks/slack", json={"event_id": "evt"})

    assert response.status_code == 409


def _test_app(monkeypatch):
    fake_db = types.ModuleType("backend.db.client")
    fake_db.get_supabase = lambda: None
    fake_db.get_outreach_db = lambda: None
    fake_db.update_task_status = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "backend.db.client", fake_db)
    sys.modules.pop("backend.api.routes", None)
    sys.modules.pop("backend.main", None)
    from backend.main import app
    return app

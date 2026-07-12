import asyncio
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(headers=None, query_string=b""):
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "headers": raw_headers, "query_string": query_string})


def test_pii_receipt_survives_simulated_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.core import pii_vault

    pii_vault.record_ssn_receipt("founder_1", "session_1")
    assert pii_vault.get_audit_report()[0]["session_id"] == "session_1"

    # A fresh module-level read represents a worker restart; data lives on disk.
    assert pii_vault._load_receipts()["founder_1:ssn"]["founder_id"] == "founder_1"
    receipts = pii_vault._load_receipts()
    receipts["founder_1:ssn"]["delete_by"] = time.time() - 1
    pii_vault._save_receipts(receipts)
    assert pii_vault.purge_expired() == 1
    assert pii_vault.get_audit_report() == []


def test_preview_requires_owner_or_valid_signed_token(monkeypatch):
    from backend.api import preview_proxy
    from backend.config import settings

    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    monkeypatch.setattr(preview_proxy, "_preview_owner", lambda slug: ("owner_1", "company_1"))
    calls = []
    # Import is inside the helper, so replace the canonical auth helper.
    monkeypatch.setattr("backend.tenant_auth.require_company_access", lambda *args, **kwargs: calls.append(args))
    preview_proxy._authorize_preview("demo", _request({"x-astra-user-id": "owner_1"}))
    assert calls

    monkeypatch.setenv("ASTRA_PREVIEW_SIGNING_SECRET", "preview-secret")
    import base64, hashlib, hmac
    expiry = int(time.time()) + 60
    signature = base64.urlsafe_b64encode(hmac.new(b"preview-secret", f"demo.{expiry}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
    preview_proxy._authorize_preview("demo", _request(query_string=f"preview_token={expiry}.{signature}".encode()))

    monkeypatch.setattr(preview_proxy, "_preview_owner", lambda slug: None)
    with pytest.raises(HTTPException) as exc:
        preview_proxy._authorize_preview("missing", _request())
    assert exc.value.status_code == 403


async def test_autoheal_lease_allows_only_one_concurrent_claim(vault, monkeypatch):
    from backend.monitoring import scheduler

    class FakeRedis:
        def __init__(self): self.values = {}
        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.values: return False
            self.values[key] = value
            return True
        def get(self, key): return self.values.get(key)
        def delete(self, key): self.values.pop(key, None)

    redis = FakeRedis()
    monkeypatch.setattr("backend.core.events._redis", lambda: redis)
    first, second = await asyncio.gather(
        asyncio.to_thread(scheduler._claim_autoheal_lease, "f", "c", "artifact"),
        asyncio.to_thread(scheduler._claim_autoheal_lease, "f", "c", "artifact"),
    )
    assert sum(item is not None for item in (first, second)) == 1


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    return tmp_path


def test_nginx_bootstrap_uses_generated_certificate():
    text = open("deploy/nginx.conf").read()
    compose = open("docker-compose.yml").read()
    assert "/etc/nginx/certs/tls.crt" in text
    assert "openssl req -x509" in compose
    assert "/etc/letsencrypt/live/178.105.231.73.nip.io/fullchain.pem;" not in text


def test_metrics_is_private_and_avoids_expensive_audits(monkeypatch):
    from backend import main
    from backend import platform_status as status
    from backend.config import settings

    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.metrics(_request()))
    assert exc.value.status_code == 401

    monkeypatch.setattr(status, "_check_stack_templates", lambda: (_ for _ in ()).throw(AssertionError("catalog audit")))
    monkeypatch.setattr(status, "_check_objective_readiness", lambda: (_ for _ in ()).throw(AssertionError("objective audit")))
    monkeypatch.setattr(status, "_check_redis", lambda: {"ok": True})
    monkeypatch.setattr(status, "_check_company_brain_scheduler", lambda: {"ok": True})
    assert "astra_redis_up 1" in status.prometheus_metrics()

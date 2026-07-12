import pytest
import jwt
from fastapi import HTTPException
from starlette.requests import Request

from backend.accounts import get_or_create_org, upsert_member
from backend.billing import fake_signed_payload, verify_stripe_signature
from backend.config import settings
from backend.tenant_auth import (
    actor_or_body,
    normalize_email_to_founder_id,
    require_current_founder,
    require_founder_access,
    require_company_access,
    require_org_access,
    require_platform_admin,
)


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "headers": raw_headers, "query_string": b""})


def test_tenant_auth_allows_owner_and_rejects_missing_auth_in_strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    assert require_founder_access(_request({"x-astra-user-id": "founder_1"}), "founder_1", "admin") == "founder_1"

    with pytest.raises(HTTPException) as exc:
        actor_or_body(_request())
    assert exc.value.status_code == 401


def test_current_founder_preserves_local_dev_missing_auth(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)

    actor = require_current_founder(_request(), "founder_1", "admin")

    assert actor.actor_id == "founder_1"
    assert actor.founder_id == "founder_1"
    assert actor.min_role == "admin"


def test_tenant_auth_enforces_org_role_rank(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    get_or_create_org("owner_1", "org_1")
    upsert_member("org_1", actor_id="owner_1", user_id="operator_1", role="operator")

    request = _request({"x-astra-user-id": "operator_1"})
    assert require_org_access(request, "org_1", "operator") == "operator_1"
    with pytest.raises(HTTPException) as exc:
        require_org_access(request, "org_1", "admin")
    assert exc.value.status_code == 403


def test_tenant_auth_supports_dev_bearer_identity(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_allow_dev_auth", True)
    request = _request({"authorization": "Bearer dev_founder_2"})
    assert require_founder_access(request, "founder_2", "viewer") == "founder_2"


def test_tenant_auth_verifies_hs256_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_jwt_secret", "test-secret")
    monkeypatch.setattr(settings, "astra_jwt_issuer", "https://issuer.example")
    monkeypatch.setattr(settings, "astra_jwt_audience", "astra-api")
    token = jwt.encode(
        {"sub": "founder_jwt", "iss": "https://issuer.example", "aud": "astra-api"},
        "test-secret",
        algorithm="HS256",
    )
    request = _request({"authorization": f"Bearer {token}"})
    assert require_founder_access(request, "founder_jwt", "viewer") == "founder_jwt"


def test_tenant_auth_rejects_untrusted_header_in_strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    with pytest.raises(HTTPException) as exc:
        require_founder_access(_request({"x-astra-user-id": "founder_header"}), "founder_header", "viewer")
    assert exc.value.status_code == 401


def test_company_access_resolves_target_company_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    from backend.core.workspace_store import create_workspace
    company = create_workspace("owner_1", "Acme", "Build Acme")

    owner_request = _request({"x-astra-user-id": "owner_1"})
    assert require_company_access(owner_request, "owner_1", company["company_id"]) == "owner_1"

    with pytest.raises(HTTPException) as exc:
        require_company_access(owner_request, "owner_1", "ws_not_owned")
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        require_company_access(owner_request, "owner_1", create_workspace("owner_2", "Other", "Other")["company_id"])
    assert exc.value.status_code == 403


def test_admin_router_requires_auth_dependency():
    from backend.api.admin import require_admin_actor, router

    dependencies = [dependency.dependency for dependency in router.dependencies]
    assert require_admin_actor in dependencies


def test_platform_admin_requires_explicit_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    monkeypatch.setattr(settings, "astra_platform_admins", "admin_1,admin_2")

    assert require_platform_admin(_request({"x-astra-user-id": "admin_1"})) == "admin_1"
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(_request({"x-astra-user-id": "operator_1"}))
    assert exc.value.status_code == 403


def test_platform_admin_local_dev_allowed_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "astra_platform_admins", "")
    assert require_platform_admin(_request()) == "local_dev"


def test_stripe_signature_verifier_accepts_valid_and_rejects_invalid_secret():
    body, signature = fake_signed_payload({"id": "evt_1", "type": "invoice.paid"}, "whsec_valid")
    assert verify_stripe_signature(body, signature, "whsec_valid") is True
    assert verify_stripe_signature(body, signature, "whsec_wrong") is False


def test_normalize_email_to_founder_id_matches_frontend_transform():
    # Must match frontend/lib/auth.ts normalizeEmailToFounderId exactly —
    # that's what actually lands in the JWT's sub claim.
    assert normalize_email_to_founder_id("Astra.Testing+Mail@Gmail.com") == "google_astra_testing_mail_gmail_com"
    assert normalize_email_to_founder_id("  founder@example.com  ") == "google_founder_example_com"


def test_beta_allowlist_rejects_non_allowlisted_email(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_jwt_secret", "test-secret-long-enough-for-hs256")
    monkeypatch.setattr(settings, "astra_beta_allowlist", "tester@example.com")

    allowed_sub = normalize_email_to_founder_id("tester@example.com")
    blocked_sub = normalize_email_to_founder_id("stranger@example.com")
    allowed_token = jwt.encode({"sub": allowed_sub}, "test-secret-long-enough-for-hs256", algorithm="HS256")
    blocked_token = jwt.encode({"sub": blocked_sub}, "test-secret-long-enough-for-hs256", algorithm="HS256")

    assert require_founder_access(_request({"authorization": f"Bearer {allowed_token}"}), allowed_sub, "viewer") == allowed_sub

    with pytest.raises(HTTPException) as exc:
        require_founder_access(_request({"authorization": f"Bearer {blocked_token}"}), blocked_sub, "viewer")
    assert exc.value.status_code == 403
    assert "waitlist" in exc.value.detail.lower()
    assert exc.value.headers.get("X-Astra-Beta-Gate") == "1"


def test_beta_allowlist_empty_allows_everyone(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    monkeypatch.setattr(settings, "astra_beta_allowlist", "")

    assert require_founder_access(_request({"x-astra-user-id": "anyone_at_all"}), "anyone_at_all", "viewer") == "anyone_at_all"

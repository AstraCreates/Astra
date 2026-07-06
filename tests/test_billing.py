from backend.accounts import get_or_create_org, update_subscription
from backend.billing import billing_config_status, create_checkout_session, create_customer_portal_session, verify_stripe_signature
from backend.config import settings


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_billing_config_reports_missing_stripe_setup(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "stripe_price_starter", "")
    monkeypatch.setattr(settings, "stripe_price_team", "")
    monkeypatch.setattr(settings, "stripe_price_scale", "")

    status = billing_config_status()

    assert status["stripe_configured"] is False
    assert status["checkout_available"] is False
    assert set(status["missing_price_ids"]) == {"starter", "team", "scale"}


def test_stripe_signature_verifier_rejects_missing_secret():
    assert verify_stripe_signature(b'{"id":"evt_1"}', "t=1,v1=abc", "") is False


def test_checkout_session_creates_customer_session_and_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    monkeypatch.setattr(settings, "stripe_price_team", "price_team")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    calls: list[tuple[str, dict]] = []

    def fake_post(url, data, auth, timeout):
        calls.append((url, data))
        if url.endswith("/customers"):
            return _FakeResponse({"id": "cus_123"})
        if url.endswith("/checkout/sessions"):
            return _FakeResponse({"id": "cs_123", "url": "https://checkout.stripe.com/cs_123"})
        return _FakeResponse({"error": {"message": "unexpected"}}, 400)

    monkeypatch.setattr("backend.billing.requests.post", fake_post)

    result = create_checkout_session("org_billing", actor_id="owner_1", plan="team", customer_email="founder@example.com")
    org = get_or_create_org("org_billing", "org_billing")

    assert result["ok"] is True
    assert result["url"] == "https://checkout.stripe.com/cs_123"
    assert org["subscription"]["stripe_customer_id"] == "cus_123"
    assert any(event["action"] == "billing.checkout.created" for event in org["audit_log"])
    checkout_call = calls[-1][1]
    assert checkout_call["line_items[0][price]"] == "price_team"
    assert checkout_call["subscription_data[metadata][org_id]"] == "org_billing"


def test_customer_portal_requires_existing_customer_and_creates_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    get_or_create_org("org_portal", "org_portal")

    missing = create_customer_portal_session("org_portal", actor_id="owner_1")
    assert missing["ok"] is False
    assert "no Stripe customer" in missing["error"]

    update_subscription("org_portal", actor_id="stripe", stripe_customer_id="cus_portal")

    def fake_post(url, data, auth, timeout):
        assert url.endswith("/billing_portal/sessions")
        assert data["customer"] == "cus_portal"
        return _FakeResponse({"id": "bps_123", "url": "https://billing.stripe.com/p/session"})

    monkeypatch.setattr("backend.billing.requests.post", fake_post)

    result = create_customer_portal_session("org_portal", actor_id="owner_1", return_url="https://astra.test/settings")

    assert result["ok"] is True
    assert result["kind"] == "portal"
    assert result["url"] == "https://billing.stripe.com/p/session"

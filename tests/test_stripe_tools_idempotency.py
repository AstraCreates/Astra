"""Regression tests for the Stripe idempotency-key fix.

backend/tools/stripe_tools.py used to call requests.post() directly with no
idempotency protection for 4 side-effecting Stripe calls (create product,
create price, create payment link, register webhook). If a Temporal activity
retried after a timeout, that could create duplicate Stripe objects in a
founder's account.

These tests exercise the fix from the outside: they mock only the HTTP layer
(requests.post) and Astra's control-plane repo bundle (using the same
Fake*Repository classes backend/control_plane/action_executor.py's own tests
use, per tests/test_control_plane_contracts.py), then call a stripe_tools
function twice with identical idempotency-relevant args and assert:
  1. Stripe's Idempotency-Key HTTP header is set to Astra's computed key.
  2. The second call replays the durable receipt instead of hitting the
     network again (requests.post is called exactly once).
  3. Exactly one Action row and one ActionReceipt row are persisted.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import stripe_tools


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


def test_create_stripe_product_twice_replays_receipt_and_sets_idempotency_header(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers})
        return _FakeResponse(200, {"id": "prod_123", "name": data["name"]})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        access_token="sk_test_abc",
        name="Founder Plan",
        description="Monthly plan",
        run_id="run_1",
        step_id="step_1",
    )

    first = stripe_tools.create_stripe_product(**kwargs)
    second = stripe_tools.create_stripe_product(**kwargs)

    # Same external behavior/return shape both times.
    assert first == {"product_id": "prod_123", "name": "Founder Plan", "created": True}
    assert second == first

    # Only ONE real HTTP call was made -- the second call replayed the receipt.
    assert len(calls) == 1

    # The Idempotency-Key header was set to a real, non-empty value.
    idem_key = calls[0]["headers"]["Idempotency-Key"]
    assert idem_key

    # Exactly one Action row and one ActionReceipt row were persisted, and the
    # receipt is keyed by the same idempotency key sent to Stripe.
    assert len(bundle.action_repo._by_id) == 1
    assert len(bundle.receipt_repo._by_id) == 1
    receipt = next(iter(bundle.receipt_repo._by_id.values()))
    assert receipt.idempotency_key == idem_key


def test_create_stripe_product_without_run_id_still_sets_header_but_skips_durable_receipt(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        calls.append(headers)
        return _FakeResponse(200, {"id": "prod_999", "name": data["name"]})

    monkeypatch.setattr("requests.post", fake_post)

    result = stripe_tools.create_stripe_product(
        access_token="sk_test_abc", name="No Run Context", description="",
    )

    assert result == {"product_id": "prod_999", "name": "No Run Context", "created": True}
    # Stripe still gets a real idempotency key even with no Astra run context.
    assert calls[0]["Idempotency-Key"]
    # But with no run_id, there's nothing to key a durable receipt to, so no
    # Action/Receipt rows are created (documented fallback behavior).
    assert len(bundle.action_repo._by_id) == 0
    assert len(bundle.receipt_repo._by_id) == 0


def test_create_stripe_price_twice_replays_receipt_and_sets_idempotency_header(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        calls.append(headers)
        return _FakeResponse(200, {"id": "price_123"})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        access_token="sk_test_abc", product_id="prod_1", amount=2500, currency="usd",
        interval="month", run_id="run_1", step_id="step_1",
    )
    first = stripe_tools.create_stripe_price(**kwargs)
    second = stripe_tools.create_stripe_price(**kwargs)

    assert first == second == {
        "price_id": "price_123", "amount": 2500, "currency": "usd",
        "interval": "month", "created": True,
    }
    assert len(calls) == 1
    assert calls[0]["Idempotency-Key"]
    assert len(bundle.action_repo._by_id) == 1
    assert len(bundle.receipt_repo._by_id) == 1


def test_create_stripe_payment_link_twice_replays_receipt_and_sets_idempotency_header(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        calls.append(headers)
        return _FakeResponse(200, {"id": "plink_123", "url": "https://pay.stripe.com/x", "active": True})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(access_token="sk_test_abc", price_id="price_1", run_id="run_1", step_id="step_1")
    first = stripe_tools.create_stripe_payment_link(**kwargs)
    second = stripe_tools.create_stripe_payment_link(**kwargs)

    assert first == second == {"url": "https://pay.stripe.com/x", "payment_link_id": "plink_123", "active": True}
    assert len(calls) == 1
    assert calls[0]["Idempotency-Key"]
    assert len(bundle.action_repo._by_id) == 1
    assert len(bundle.receipt_repo._by_id) == 1


def test_register_stripe_webhook_twice_replays_receipt_and_sets_idempotency_header(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        calls.append(headers)
        return _FakeResponse(200, {"id": "we_123", "secret": "whsec_x", "url": data["url"]})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        access_token="sk_test_abc", endpoint_url="https://astra.dev/hooks/f1",
        run_id="run_1", step_id="step_1",
    )
    first = stripe_tools.register_stripe_webhook(**kwargs)
    second = stripe_tools.register_stripe_webhook(**kwargs)

    assert first == second == {
        "webhook_id": "we_123", "secret": "whsec_x",
        "url": "https://astra.dev/hooks/f1", "registered": True,
    }
    assert len(calls) == 1
    assert calls[0]["Idempotency-Key"]
    assert len(bundle.action_repo._by_id) == 1
    assert len(bundle.receipt_repo._by_id) == 1


def test_create_product_with_payment_link_full_chain_preserves_shape_and_uses_distinct_keys_per_step(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    posts = []

    def fake_post(url, data=None, auth=None, headers=None, timeout=None):
        posts.append({"url": url, "headers": headers})
        if "products" in url:
            return _FakeResponse(200, {"id": "prod_1", "name": data["name"]})
        if "prices" in url:
            return _FakeResponse(200, {"id": "price_1"})
        return _FakeResponse(200, {"id": "plink_1", "url": "https://pay.stripe.com/y", "active": True})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        name="Pro Plan", description="desc", amount=1000, access_token="sk_test_abc",
        currency="usd", interval="month", run_id="run_1", step_id="setup",
    )

    first = stripe_tools.create_product_with_payment_link(**kwargs)
    assert first == {
        "product_id": "prod_1", "price_id": "price_1", "payment_link_url": "https://pay.stripe.com/y",
        "name": "Pro Plan", "amount": 1000, "currency": "usd", "interval": "month", "created": True,
    }
    assert len(posts) == 3  # product, price, payment_link -- one real call each

    # The 3 sub-steps are distinct actions -- distinct idempotency keys -- even
    # though they share the same run_id/base step_id.
    keys = [p["headers"]["Idempotency-Key"] for p in posts]
    assert len(set(keys)) == 3
    assert len(bundle.action_repo._by_id) == 3
    assert len(bundle.receipt_repo._by_id) == 3

    # Retrying the whole chain (same run_id/step_id/args, e.g. a Temporal
    # activity retry) replays all 3 receipts instead of re-hitting Stripe.
    second = stripe_tools.create_product_with_payment_link(**kwargs)
    assert second == first
    assert len(posts) == 3
    assert len(bundle.action_repo._by_id) == 3
    assert len(bundle.receipt_repo._by_id) == 3

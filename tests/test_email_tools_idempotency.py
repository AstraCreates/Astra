"""Regression tests for the Gmail/Resend idempotency-key fix.

backend/tools/gmail_api.py's gmail_send_email() and backend/tools/resend_tools.py's
resend_send_email() used to call requests.post() directly with no idempotency
protection. If a Temporal activity retried after a timeout (e.g. the send
succeeded but the activity result wasn't durably recorded before the retry),
the same email could get sent twice to a real recipient.

These tests exercise the fix from the outside, mirroring
tests/test_stripe_tools_idempotency.py's pattern: mock only the HTTP layer and
Astra's control-plane repo bundle (using the same Fake*Repository classes
backend/control_plane/action_executor.py's own tests use), then call each
function twice with identical idempotency-relevant args and assert the second
call replays the durable receipt instead of hitting the network again.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import gmail_api, resend_tools


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict, ok: bool | None = None):
        self.status_code = status_code
        self._body = body
        self.ok = ok if ok is not None else (200 <= status_code < 300)
        self.text = str(body)

    def json(self) -> dict:
        return self._body


def test_gmail_send_email_twice_with_run_id_replays_receipt(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    monkeypatch.setattr(
        gmail_api, "get_gmail_api_credentials", lambda founder_id, inline_credentials=None: {"access_token": "tok_abc"}
    )

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse(200, {"id": "msg_123"})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        founder_id="founder_1", to="user@example.com", subject="Hello", body="World",
        run_id="run_1", step_id="step_1",
    )

    first = gmail_api.gmail_send_email(**kwargs)
    second = gmail_api.gmail_send_email(**kwargs)

    assert first == {"ok": True, "message_id": "msg_123", "to": "user@example.com", "subject": "Hello"}
    assert second == first
    # Only ONE real HTTP call -- the second call replayed the durable receipt.
    assert len(calls) == 1

    actions = list(bundle.action_repo._by_id.values()) if hasattr(bundle.action_repo, "_by_id") else None
    if actions is not None:
        assert len(actions) == 1


def test_gmail_send_email_without_run_id_sends_directly_each_time(monkeypatch):
    # No run_id available (e.g. a manual/direct call outside any run) --
    # Gmail's API has no native idempotency mechanism, so there's genuinely no
    # protection possible; confirm we don't crash and don't silently invent a
    # fake run_id that would misattribute a durable receipt.
    monkeypatch.setattr(
        gmail_api, "get_gmail_api_credentials", lambda founder_id, inline_credentials=None: {"access_token": "tok_abc"}
    )
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _FakeResponse(200, {"id": "msg_456"})

    monkeypatch.setattr("requests.post", fake_post)

    result = gmail_api.gmail_send_email(founder_id="founder_1", to="user@example.com", subject="Hi", body="Body")
    assert result["ok"] is True
    assert len(calls) == 1


def test_resend_send_email_twice_with_run_id_replays_receipt_and_sets_idempotency_header(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)
    monkeypatch.setattr(resend_tools.settings, "resend_api_key", "re_test_key", raising=False)

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(200, {"id": "email_123"})

    monkeypatch.setattr("requests.post", fake_post)

    kwargs = dict(
        to="user@example.com", from_email="noreply@astracreates.com", subject="Welcome", html="<p>hi</p>",
        run_id="run_1", step_id="step_1",
    )

    first = resend_tools.resend_send_email(**kwargs)
    second = resend_tools.resend_send_email(**kwargs)

    assert first == {"sent": True, "id": "email_123", "status": 200}
    assert second == first
    assert len(calls) == 1
    assert "Idempotency-Key" in calls[0]["headers"]
    assert calls[0]["headers"]["Idempotency-Key"]


def test_resend_send_email_without_run_id_still_sets_content_derived_idempotency_key(monkeypatch):
    monkeypatch.setattr(resend_tools.settings, "resend_api_key", "re_test_key", raising=False)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"headers": headers})
        return _FakeResponse(200, {"id": "email_456"})

    monkeypatch.setattr("requests.post", fake_post)

    result = resend_tools.resend_send_email(
        to="user@example.com", from_email="noreply@astracreates.com", subject="Hi", html="<p>hi</p>",
    )
    assert result["sent"] is True
    assert len(calls) == 1
    assert calls[0]["headers"]["Idempotency-Key"]

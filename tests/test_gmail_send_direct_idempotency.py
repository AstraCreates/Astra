"""Regression test for the Gmail send idempotency fix.

sales.py and ops.py both expose gmail_send_direct AND composio_gmail_send as
separate tools on the same agent -- composio_gmail_send calls gmail_send_direct
internally as its first step, so a model that calls one and then (confused, or
retrying) calls the other sends a real duplicate email to the same recipient.
Neither had any idempotency key or dedup. This tests
_send_gmail_with_idempotency directly (the extracted helper the real send now
routes through) rather than mocking the full Gmail OAuth/token-refresh flow
end to end.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import composio_tools


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


def test_gmail_send_replays_receipt_on_retry_with_same_run_and_step(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = {"count": 0}

    def send_call():
        calls["count"] += 1
        return {"ok": True, "message_id": "msg_123"}

    args = {"founder_id": "f1", "to": "prospect@acme.com", "subject": "Hi", "body": "b"}

    first = composio_tools._send_gmail_with_idempotency(
        run_id="run_1", step_id="gmail_send_direct", args=args, send_call=send_call,
    )
    second = composio_tools._send_gmail_with_idempotency(
        run_id="run_1", step_id="gmail_send_direct", args=args, send_call=send_call,
    )

    assert first == second == {"ok": True, "message_id": "msg_123"}
    # Only ONE real email sent -- the retry replayed the durable receipt.
    assert calls["count"] == 1


def test_gmail_send_without_run_id_calls_directly_each_time():
    calls = {"count": 0}

    def send_call():
        calls["count"] += 1
        return {"ok": True, "message_id": f"msg_{calls['count']}"}

    result = composio_tools._send_gmail_with_idempotency(
        run_id="", step_id="", args={}, send_call=send_call,
    )
    assert result["message_id"] == "msg_1"
    assert calls["count"] == 1


def test_gmail_send_direct_and_composio_gmail_send_share_the_same_idempotency_key(monkeypatch):
    """The real duplicate-send risk: a model calls gmail_send_direct (succeeds),
    then calls composio_gmail_send with the same args, thinking it's a distinct
    fallback tool. composio_gmail_send calls gmail_send_direct internally, so
    with the same run_id/args this must replay instead of sending twice."""
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    monkeypatch.setattr(
        composio_tools, "load_credentials",
        lambda founder_id, kind: {"connected_via": "google_oauth", "access_token": "tok"},
        raising=False,
    )

    send_calls = {"count": 0}

    class _FakeResponse:
        status_code = 200

        def json(self):
            send_calls["count"] += 1
            return {"id": f"msg_{send_calls['count']}"}

    monkeypatch.setattr("backend.provisioning.credentials_store.load_credentials",
                        lambda founder_id, kind: {"connected_via": "google_oauth", "access_token": "tok"})
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeResponse())

    args = dict(founder_id="f1", to="prospect@acme.com", subject="Hi", body="b", session_id="run_1")

    first = composio_tools.gmail_send_direct(**args)
    second = composio_tools.composio_gmail_send(founder_id="f1", to="prospect@acme.com", subject="Hi", body="b", session_id="run_1")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["message_id"] == second["message_id"]
    # Only ONE real Gmail API call across both "tools" -- the second replayed the receipt.
    assert send_calls["count"] == 1

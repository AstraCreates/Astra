"""Regression test for the Meta ad creation idempotency fix.

generate_meta_ad's _create_meta_ad_draft POSTs directly to Meta's Graph API
with no idempotency key field and no dedup against retries -- a retried/
re-called generate_meta_ad previously created a second real (paused) ad
object on the live account every time. This tests
_create_meta_ad_with_idempotency directly (the extracted helper the real
ad-creation call now routes through) rather than mocking the full Meta
Graph API HTTP flow end to end.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import social_content


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


def test_meta_ad_creation_replays_receipt_on_retry_with_same_run_and_step(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = {"count": 0}

    def create_call():
        calls["count"] += 1
        return {"posted": True, "meta_ad_id": "act_123"}

    args = {"ad_name": "Acme -- Best headline", "headline": "h", "body": "b"}

    first = social_content._create_meta_ad_with_idempotency(
        run_id="run_1", step_id="generate_meta_ad:Acme", args=args, create_call=create_call,
    )
    second = social_content._create_meta_ad_with_idempotency(
        run_id="run_1", step_id="generate_meta_ad:Acme", args=args, create_call=create_call,
    )

    assert first == second == {"posted": True, "meta_ad_id": "act_123"}
    # Only ONE real ad created on the live account -- the retry replayed the receipt.
    assert calls["count"] == 1


def test_meta_ad_creation_without_run_id_calls_directly_each_time():
    calls = {"count": 0}

    def create_call():
        calls["count"] += 1
        return {"posted": True, "meta_ad_id": f"act_{calls['count']}"}

    result = social_content._create_meta_ad_with_idempotency(
        run_id="", step_id="", args={}, create_call=create_call,
    )
    assert result["meta_ad_id"] == "act_1"
    assert calls["count"] == 1

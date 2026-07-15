"""Regression test for the Vercel deploy-trigger idempotency fix.

backend/tools/vercel_deploy.py's vercel_deploy_from_github() triggered a
production deployment via a direct requests.post() with no idempotency
protection. A Temporal activity retry after a timeout (deploy trigger
succeeded, activity result not durably recorded before the retry) could
trigger a second production deploy.

This tests _deploy_trigger_with_idempotency directly (the extracted helper
the real deploy call now routes through) rather than mocking the full
multi-step OAuth/project/env/deploy/poll flow end to end.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import vercel_deploy


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


def test_deploy_trigger_replays_receipt_on_retry_with_same_run_and_step(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = {"count": 0}

    def deploy_call():
        calls["count"] += 1
        return {"ok": True, "status_code": 200, "text": "", "body": {"id": "dpl_123", "url": "proj-abc.vercel.app"}}

    args = {"deploy_url": "https://api.vercel.com/v13/deployments", "deploy_payload": {"name": "proj"}}

    first = vercel_deploy._deploy_trigger_with_idempotency(
        run_id="run_1", step_id="vercel_deploy:attempt_1", args=args, deploy_call=deploy_call,
    )
    second = vercel_deploy._deploy_trigger_with_idempotency(
        run_id="run_1", step_id="vercel_deploy:attempt_1", args=args, deploy_call=deploy_call,
    )

    assert first == second
    assert first["body"]["id"] == "dpl_123"
    # Only ONE real deploy call -- the retry replayed the durable receipt.
    assert calls["count"] == 1


def test_deploy_trigger_treats_different_attempt_numbers_as_distinct(monkeypatch):
    # Internal build-retry attempts (a genuine NEW deploy after a build
    # failure) must NOT be collapsed into the same receipt as attempt 1 --
    # only a Temporal-level re-invocation of the SAME attempt should replay.
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = {"count": 0}

    def deploy_call():
        calls["count"] += 1
        return {"ok": True, "status_code": 200, "text": "", "body": {"id": f"dpl_{calls['count']}", "url": "proj-abc.vercel.app"}}

    args = {"deploy_url": "https://api.vercel.com/v13/deployments", "deploy_payload": {"name": "proj"}}

    first = vercel_deploy._deploy_trigger_with_idempotency(
        run_id="run_1", step_id="vercel_deploy:attempt_1", args=args, deploy_call=deploy_call,
    )
    second = vercel_deploy._deploy_trigger_with_idempotency(
        run_id="run_1", step_id="vercel_deploy:attempt_2", args=args, deploy_call=deploy_call,
    )

    assert first["body"]["id"] == "dpl_1"
    assert second["body"]["id"] == "dpl_2"
    assert calls["count"] == 2


def test_deploy_trigger_without_run_id_calls_directly_each_time():
    calls = {"count": 0}

    def deploy_call():
        calls["count"] += 1
        return {"ok": True, "status_code": 200, "text": "", "body": {"id": "dpl_x"}}

    result = vercel_deploy._deploy_trigger_with_idempotency(
        run_id="", step_id="", args={}, deploy_call=deploy_call,
    )
    assert result["body"]["id"] == "dpl_x"
    assert calls["count"] == 1

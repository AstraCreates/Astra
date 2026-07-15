"""Regression tests for the automation-graph Slack/SendGrid/Gmail idempotency fix.

backend/tools/automation_graph.py's _execute_slack_node/_execute_email_node made
direct requests.post() calls with no idempotency protection. A Temporal retry
of the automation run could re-post the same Slack message or re-send the same
email to every subscriber.
"""
from __future__ import annotations

import pytest

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import automation_graph


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_slack_node_twice_with_run_id_replays_receipt(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)
    monkeypatch.setattr("backend.tools.url_safety.validate_url", lambda url: None)

    calls = []

    def fake_post(url, json=None, timeout=None, allow_redirects=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse(200)

    monkeypatch.setattr("requests.post", fake_post)

    node = {"id": "n1", "type": "slack"}
    cfg = {"webhook_url": "https://hooks.slack.com/services/x", "message": "hello team"}

    first = await automation_graph._execute_slack_node(node, cfg, run_id="run_1", node_id="n1")
    second = await automation_graph._execute_slack_node(node, cfg, run_id="run_1", node_id="n1")

    assert first == second
    assert "error" not in first
    # Only ONE real HTTP call -- the second call replayed the durable receipt.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_slack_node_without_run_id_posts_directly(monkeypatch):
    monkeypatch.setattr("backend.tools.url_safety.validate_url", lambda url: None)
    calls = []

    def fake_post(url, json=None, timeout=None, allow_redirects=None):
        calls.append(1)
        return _FakeResponse(200)

    monkeypatch.setattr("requests.post", fake_post)

    result = await automation_graph._execute_slack_node(
        {"id": "n1", "type": "slack"}, {"webhook_url": "https://hooks.slack.com/services/x", "message": "hi"},
    )
    assert "error" not in result
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_email_node_twice_with_run_id_replays_receipt(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)
    monkeypatch.setattr(
        "backend.provisioning.credentials_store.load_credentials",
        lambda founder_id, service: {"api_key": "sg_test_key"},
    )

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse(202)

    monkeypatch.setattr("requests.post", fake_post)

    node = {"id": "n2", "type": "email"}
    cfg = {"to": "user@example.com", "subject": "Hi", "body": "Body"}

    first = await automation_graph._execute_email_node(node, cfg, "founder_1", run_id="run_1", node_id="n2")
    second = await automation_graph._execute_email_node(node, cfg, "founder_1", run_id="run_1", node_id="n2")

    assert first == second
    assert "error" not in first
    assert len(calls) == 1

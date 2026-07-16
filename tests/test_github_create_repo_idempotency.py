"""Regression test for the GitHub repo-creation idempotency fix.

github_create_repo() always appended a random uuid suffix to guarantee a
unique repo name, which meant a Temporal retry of this step previously
created a genuinely new, orphaned, duplicate repo every time -- the exact
opposite of idempotent. This tests _create_repo_with_idempotency directly
(the extracted helper the real repo-creation call now routes through)
rather than mocking the full GitHub HTTP flow end to end.
"""
from __future__ import annotations

import backend.control_plane.action_executor as action_executor
from backend.control_plane.action_executor import ControlPlaneRepoBundle
from backend.control_plane.fakes import (
    FakeActionReceiptRepository,
    FakeActionRepository,
    FakeApprovalRequestRepository,
)
from backend.tools import github_scaffold


def _fresh_bundle() -> ControlPlaneRepoBundle:
    return ControlPlaneRepoBundle(
        action_repo=FakeActionRepository(),
        receipt_repo=FakeActionReceiptRepository(),
        approval_repo=FakeApprovalRequestRepository(),
    )


def _patch_repo_bundle(monkeypatch, bundle: ControlPlaneRepoBundle) -> None:
    monkeypatch.setattr(action_executor, "get_default_repo_bundle", lambda: bundle)


def test_repo_creation_replays_receipt_on_retry_with_same_run_and_step(monkeypatch):
    bundle = _fresh_bundle()
    _patch_repo_bundle(monkeypatch, bundle)

    calls = {"count": 0}

    def create_call():
        calls["count"] += 1
        return {"repo_name": "acme-app-abc123", "repo_url": "https://github.com/x/acme-app-abc123"}

    args = {"repo_name": "acme-app", "description": "d", "private": True}

    first = github_scaffold._create_repo_with_idempotency(
        run_id="run_1", step_id="github_create_repo", args=args, create_call=create_call,
    )
    second = github_scaffold._create_repo_with_idempotency(
        run_id="run_1", step_id="github_create_repo", args=args, create_call=create_call,
    )

    assert first["repo_url"] == second["repo_url"] == "https://github.com/x/acme-app-abc123"
    assert first["_replayed"] is False
    assert second["_replayed"] is True
    # Only ONE real repo created -- the retry replayed the durable receipt.
    assert calls["count"] == 1


def test_repo_creation_without_run_id_calls_directly_each_time():
    calls = {"count": 0}

    def create_call():
        calls["count"] += 1
        return {"repo_name": f"repo-{calls['count']}", "repo_url": f"https://github.com/x/repo-{calls['count']}"}

    result = github_scaffold._create_repo_with_idempotency(
        run_id="", step_id="", args={}, create_call=create_call,
    )
    assert result["repo_name"] == "repo-1"
    assert "_replayed" not in result
    assert calls["count"] == 1


def test_github_create_repo_skips_scaffold_push_on_replay(monkeypatch):
    """A replayed receipt means an earlier attempt already pushed the scaffold --
    re-pushing would hit GitHub's "sha required to update an existing file" error."""
    from backend.config import settings

    monkeypatch.setattr(settings, "github_token", "gh_test_token", raising=False)

    class _FakeResponse:
        def __init__(self, json_data):
            self._json = json_data

        def raise_for_status(self):
            pass

        def json(self):
            return self._json

    put_calls = {"count": 0}

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse({"login": "acme-user"})

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"html_url": "https://github.com/acme-user/acme-app-abc123"})

    def fake_put(url, headers=None, json=None, timeout=None):
        put_calls["count"] += 1
        return _FakeResponse({})

    monkeypatch.setattr(github_scaffold.requests, "get", fake_get)
    monkeypatch.setattr(github_scaffold.requests, "post", fake_post)
    monkeypatch.setattr(github_scaffold.requests, "put", fake_put)
    monkeypatch.setattr(
        github_scaffold,
        "_create_repo_with_idempotency",
        lambda **kw: {"repo_name": "acme-app-abc123", "repo_url": "https://github.com/acme-user/acme-app-abc123", "_replayed": True},
    )

    result = github_scaffold.github_create_repo(repo_name="acme-app", session_id="run_1")

    assert result["created"] is True
    assert result["replayed"] is True
    assert result["files_pushed"] == []
    assert put_calls["count"] == 0

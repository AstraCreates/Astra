import pytest
from starlette.requests import Request

from backend.api import routes
from backend.api.schemas import StackApprovalDecisionRequest


@pytest.mark.asyncio
async def test_stack_approval_passes_actual_admin_role_to_workflow(monkeypatch):
    captured = {}

    monkeypatch.setattr(routes, "require_founder_access", lambda *_args, **_kwargs: "admin_1")

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(routes, "publish", publish)

    from backend import accounts
    from backend import approval_workflows
    from backend.core import events

    monkeypatch.setattr(accounts, "get_or_create_org", lambda *_args: {"members": {"admin_1": {"role": "admin"}}})
    monkeypatch.setattr(accounts, "record_usage", lambda *_args, **_kwargs: None)

    def decide(*_args, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "requests": [{"id": "approval_1"}]}

    monkeypatch.setattr(approval_workflows, "decide_approval_request", decide)
    monkeypatch.setattr(events, "approval_decision_push", lambda *_args, **_kwargs: None)

    request = Request({"type": "http", "headers": []})
    body = StackApprovalDecisionRequest(
        session_id="session_1", founder_id="founder_1", gate_key="production_publish", decision="approved",
        approval_id="approval_1", expected_action_digest="digest_1",
    )

    result = await routes.decide_stack_approval(body, request)

    assert captured["actor_role"] == "admin"
    assert captured["request_id"] == "approval_1"
    assert result["requests"] == [{"id": "approval_1"}]

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes
from backend.api.schemas import RunApprovalDecisionRequest, StackApprovalDecisionRequest
from backend.control_plane.models import ApprovalRequest, Run


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


@pytest.mark.asyncio
async def test_stack_approval_mirrors_existing_durable_request(monkeypatch):
    monkeypatch.setattr(routes, "actor_or_body", lambda _request: "owner_1")

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(routes, "publish", publish)

    from backend import approval_workflows
    from backend.core import events

    monkeypatch.setattr(approval_workflows, "decide_approval_request", lambda *_args, **_kwargs: {
        "ok": True,
        "requests": [{
            "id": "approval_2",
            "approval_id": "approval_2",
            "action_digest": "digest_2",
        }],
    })
    monkeypatch.setattr(events, "approval_decision_push", lambda *_args, **_kwargs: None)

    class _DurableRepo:
        def get(self, request_id):
            return ApprovalRequest(
                id=request_id,
                run_id="session_2",
                gate_key="outbound_send",
                action_digest="digest_2",
                status="pending",
            )

        def decide(self, request_id, status, *, decided_by, note=None):
            return ApprovalRequest(
                id=request_id,
                run_id="session_2",
                gate_key="outbound_send",
                action_digest="digest_2",
                status=status,
                decided_by=decided_by,
                decision_note=note,
            )

    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseApprovalRequestRepository", _DurableRepo)

    request = Request({"type": "http", "headers": []})
    body = StackApprovalDecisionRequest(
        session_id="session_2",
        gate_key="outbound_send",
        decision="approved",
        approval_id="approval_2",
        expected_action_digest="digest_2",
        note="looks good",
    )

    result = await routes.decide_stack_approval(body, request)

    assert result["durable_approval"]["status"] == "approved"
    assert result["durable_approval"]["decided_by"] == "owner_1"


@pytest.mark.asyncio
async def test_run_approval_updates_durable_row_and_signals_temporal(monkeypatch):
    approval = ApprovalRequest(
        id="approval_1",
        run_id="run_1",
        gate_key="production_publish",
        action_digest="digest_1",
        status="pending",
    )
    decided_calls = []
    signaled = []

    class _ApprovalRepo:
        def get(self, request_id):
            assert request_id == "approval_1"
            return approval

        def decide(self, request_id, status, *, decided_by, note=None):
            decided_calls.append((request_id, status, decided_by, note))
            return approval.model_copy(update={"status": status, "decided_by": decided_by, "decision_note": note})

    class _RunRepo:
        def get(self, run_id):
            assert run_id == "run_1"
            return Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="g", engine="temporal", metadata={"workflow_id": "astra-run/run_1"})

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    async def _decide_stack_approval(*_args, **_kwargs):
        return {"ok": True, "requests": [{"id": "approval_1"}]}

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr(routes, "actor_or_body", lambda _request: "admin_1")
    monkeypatch.setattr(routes, "decide_stack_approval", _decide_stack_approval)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseApprovalRequestRepository", _ApprovalRepo)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)

    async def _send_approval_decision(run_id, **kwargs):
        signaled.append((run_id, kwargs))
        return True

    monkeypatch.setattr("backend.control_plane.temporal.dispatch.send_approval_decision", _send_approval_decision)

    request = Request({"type": "http", "headers": []})
    body = RunApprovalDecisionRequest(decision="approved", expected_action_digest="digest_1", note="ship it")

    result = await routes.decide_run_approval("run_1", "approval_1", body, request)

    assert decided_calls == [("approval_1", "approved", "admin_1", "ship it")]
    assert signaled == [("run_1", {
        "approval_id": "approval_1",
        "action_digest": "digest_1",
        "decision": "approved",
        "policy_version": "v1",
        "decided_by": "admin_1",
        "note": "ship it",
    })]
    assert result["approval"]["status"] == "approved"
    assert result["temporal_signaled"] is True


@pytest.mark.asyncio
async def test_run_approval_resolves_founder_id_from_run_owner_when_body_omits_it(monkeypatch):
    # Regression test for a real incident: RunApprovalDecisionRequest.founder_id is
    # never populated by the frontend's decideApproval() call (it only sends
    # decision/note/expected_action_digest). Without a fallback, decide_stack_approval
    # -> _approval_actor_role(None, actor_id) hits its `if not founder_id: return
    # "viewer"` branch unconditionally, so every real approval decision through this
    # endpoint (the one the UI's own Approve button uses) failed "actor role does not
    # satisfy the approval requirement" for every founder, on every run -- confirmed
    # live in production. This test exercises the REAL decide_stack_approval (not
    # mocked, unlike the sibling test above) so the actor_role resolution path is
    # actually covered.
    from backend import accounts

    approval = ApprovalRequest(
        id="approval_1", run_id="run_1", gate_key="phase_gate_diagnose",
        action_digest="digest_1", status="pending", required_role="owner",
    )

    class _ApprovalRepo:
        def get(self, request_id):
            return approval

        def decide(self, request_id, status, *, decided_by, note=None):
            return approval.model_copy(update={"status": status, "decided_by": decided_by})

    class _RunRepo:
        def get(self, run_id):
            return Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="g", engine="legacy")

    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    monkeypatch.setattr(routes, "actor_or_body", lambda _request: "founder_1")
    monkeypatch.setattr(routes, "require_founder_access", lambda *_args, **_kwargs: "founder_1")
    monkeypatch.setattr(accounts, "get_or_create_org", lambda *_args: {"members": {"founder_1": {"role": "owner"}}})
    monkeypatch.setattr(accounts, "record_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseApprovalRequestRepository", _ApprovalRepo)
    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseRunRepository", _RunRepo)

    from backend import approval_workflows
    from backend.core import events

    captured = {}

    def decide(session_id, gate_key, decision, *, request_id, actor_id, actor_role, note, expected_action_digest):
        captured["actor_role"] = actor_role
        if actor_role != "owner":
            return {"ok": False, "error": "actor role does not satisfy the approval requirement", "requests": []}
        return {"ok": True, "requests": [{"id": request_id, "approval_id": request_id, "action_digest": expected_action_digest}]}

    monkeypatch.setattr(approval_workflows, "decide_approval_request", decide)
    monkeypatch.setattr(events, "approval_decision_push", lambda *_args, **_kwargs: None)

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(routes, "publish", publish)

    request = Request({"type": "http", "headers": []})
    body = RunApprovalDecisionRequest(decision="approved", expected_action_digest="digest_1")

    result = await routes.decide_run_approval("run_1", "approval_1", body, request)

    assert captured["actor_role"] == "owner"
    assert result["ok"] is True
    assert result["approval"]["status"] == "approved"


@pytest.mark.asyncio
async def test_run_approval_rejects_non_pending_or_mismatched_digest(monkeypatch):
    async def _require_session_access(*_args, **_kwargs):
        return "founder_1"

    monkeypatch.setattr(routes, "_require_session_access", _require_session_access)
    request = Request({"type": "http", "headers": []})

    class _ApprovalRepoDone:
        def get(self, _request_id):
            return ApprovalRequest(
                id="approval_done",
                run_id="run_1",
                gate_key="production_publish",
                action_digest="digest_1",
                status="approved",
            )

    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseApprovalRequestRepository", _ApprovalRepoDone)
    with pytest.raises(HTTPException) as exc:
        await routes.decide_run_approval("run_1", "approval_done", RunApprovalDecisionRequest(decision="approved"), request)
    assert exc.value.status_code == 409
    assert "already approved" in exc.value.detail

    class _ApprovalRepoPending:
        def get(self, _request_id):
            return ApprovalRequest(
                id="approval_pending",
                run_id="run_1",
                gate_key="production_publish",
                action_digest="digest_good",
                status="pending",
            )

    monkeypatch.setattr("backend.control_plane.supabase_repositories.SupabaseApprovalRequestRepository", _ApprovalRepoPending)
    with pytest.raises(HTTPException) as exc:
        await routes.decide_run_approval(
            "run_1",
            "approval_pending",
            RunApprovalDecisionRequest(decision="approved", expected_action_digest="digest_bad"),
            request,
        )
    assert exc.value.status_code == 409
    assert "expected_action_digest" in exc.value.detail

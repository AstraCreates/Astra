from backend.approval_workflows import (
    create_approval_request,
    decide_approval_request,
    expire_approval_requests,
    get_approval_workflow,
)


def test_approval_workflow_supports_rejection_and_request_targeting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    first = create_approval_request(
        "session_reject",
        "outbound_send",
        action_id="email_1",
        title="Send first outbound",
        required_role="admin",
    )
    second = create_approval_request(
        "session_reject",
        "outbound_send",
        action_id="email_2",
        title="Send second outbound",
        required_role="admin",
    )

    decision = decide_approval_request(
        "session_reject",
        "outbound_send",
        "rejected",
        request_id=first["id"],
        actor_id="admin_1",
        actor_role="admin",
        note="Needs narrower targeting.",
        expected_action_digest=first["action_digest"],
    )
    workflow = get_approval_workflow("session_reject")
    by_id = {request["id"]: request for request in workflow["requests"]}

    assert decision["ok"] is True
    assert len(decision["requests"]) == 1
    assert by_id[first["id"]]["status"] == "rejected"
    assert by_id[first["id"]]["history"][-1]["event"] == "rejected"
    assert by_id[second["id"]]["status"] == "pending"


def test_approval_workflow_rejects_insufficient_actor_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    request = create_approval_request(
        "session_role",
        "public_deploy",
        action_id="deploy_1",
        required_role="owner",
    )

    decision = decide_approval_request(
        "session_role",
        "public_deploy",
        "approved",
        request_id=request["id"],
        actor_id="operator_1",
        actor_role="operator",
        expected_action_digest=request["action_digest"],
    )
    workflow = get_approval_workflow("session_role")
    stored = workflow["requests"][0]

    assert decision["ok"] is False
    assert "role does not satisfy" in decision["error"]
    assert stored["status"] == "pending"
    assert stored["history"][-1]["event"] == "decision_rejected"
    assert stored["history"][-1]["note"] == "requires owner"


def test_admin_cannot_clear_an_owner_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    request = create_approval_request("session_owner_gate", "production_publish", action_id="publish_1", required_role="owner")

    decision = decide_approval_request(
        "session_owner_gate", "production_publish", "approved", request_id=request["id"], actor_id="admin_1",
        actor_role="admin", expected_action_digest=request["action_digest"],
    )

    assert decision["ok"] is False
    assert get_approval_workflow("session_owner_gate")["requests"][0]["status"] == "pending"


def test_approval_workflow_expires_stale_requests(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_approval_request(
        "session_expire",
        "paid_spend",
        action_id="ad_budget_1",
        required_role="owner",
        expires_at="2026-01-01T00:00:00Z",
    )

    expired = expire_approval_requests("session_expire", now="2026-01-02T00:00:00Z")
    workflow = get_approval_workflow("session_expire")

    assert expired["expired_count"] == 1
    assert workflow["requests"][0]["status"] == "expired"
    assert workflow["requests"][0]["history"][-1]["event"] == "expired"


def test_approval_workflow_rejects_invalid_decision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_approval_request("session_invalid", "legal_publish", action_id="legal_1")

    decision = decide_approval_request("session_invalid", "legal_publish", "maybe", actor_id="owner_1", actor_role="owner")

    assert decision["ok"] is False
    assert "decision must be one of" in decision["error"]


def test_approval_workflow_persists_phase_gate_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    create_approval_request(
        "session_phase",
        "phase_gate_design",
        title="Design Phase Complete",
        agent="orchestrator",
        metadata={
            "is_phase_gate": True,
            "phase": "design",
            "next_phase": "deploy",
            "artifacts": [{"key": "brand_direction", "title": "Brand direction"}],
        },
    )

    workflow = get_approval_workflow("session_phase")
    req = workflow["requests"][0]

    assert req["is_phase_gate"] is True
    assert req["phase"] == "design"
    assert req["next_phase"] == "deploy"
    assert req["artifacts"][0]["key"] == "brand_direction"


def test_approval_workflow_rejects_unknown_or_already_resolved_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    missing = decide_approval_request(
        "session_missing",
        "phase_gate_design",
        "approved",
        actor_id="owner_1",
        actor_role="owner",
    )
    assert missing["ok"] is False
    assert "no approval request found" in missing["error"]

    created = create_approval_request(
        "session_done",
        "phase_gate_design",
        agent="orchestrator",
    )
    first = decide_approval_request(
        "session_done",
        "phase_gate_design",
        "approved",
        request_id=created["id"],
        actor_id="owner_1",
        actor_role="owner",
        expected_action_digest=created["action_digest"],
    )
    second = decide_approval_request(
        "session_done",
        "phase_gate_design",
        "approved",
        request_id=created["id"],
        actor_id="owner_1",
        actor_role="owner",
        expected_action_digest=created["action_digest"],
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert "no pending approval request found" in second["error"]


def test_same_gate_requests_require_a_request_id_and_remain_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = create_approval_request("session_independent", "outbound_send", action_id="email_1", required_role="admin")
    second = create_approval_request("session_independent", "outbound_send", action_id="email_2", required_role="admin")

    ambiguous = decide_approval_request(
        "session_independent", "outbound_send", "approved", actor_id="admin_1", actor_role="admin",
        expected_action_digest=first["action_digest"],
    )
    approved = decide_approval_request(
        "session_independent", "outbound_send", "approved", request_id=first["approval_id"],
        actor_id="admin_1", actor_role="admin", expected_action_digest=first["action_digest"],
    )
    requests = {item["id"]: item for item in get_approval_workflow("session_independent")["requests"]}

    assert ambiguous["ok"] is False
    assert "request_id is required" in ambiguous["error"]
    assert approved["ok"] is True
    assert requests[first["id"]]["status"] == "approved"
    assert requests[second["id"]]["status"] == "pending"


def test_rejected_refresh_creates_revision_and_rejects_stale_digest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = create_approval_request("session_refresh", "public_deploy", action_id="deploy_1")
    rejected = decide_approval_request(
        "session_refresh", "public_deploy", "rejected", request_id=original["id"], actor_id="owner_1",
        actor_role="owner", expected_action_digest=original["action_digest"],
    )
    refreshed = create_approval_request("session_refresh", "public_deploy", action_id="deploy_1")
    stale = decide_approval_request(
        "session_refresh", "public_deploy", "approved", request_id=refreshed["id"], actor_id="owner_1",
        actor_role="owner", expected_action_digest=original["action_digest"],
    )
    approved = decide_approval_request(
        "session_refresh", "public_deploy", "approved", request_id=refreshed["id"], actor_id="owner_1",
        actor_role="owner", expected_action_digest=refreshed["action_digest"],
    )

    assert rejected["ok"] is True
    assert refreshed["status"] == "pending"
    assert refreshed["revision"] == 2
    assert refreshed["refreshed_from"] == original["id"]
    assert refreshed["history"][-1]["event"] == "refreshed"
    assert stale["ok"] is False
    assert "does not match" in stale["error"]
    assert approved["ok"] is True

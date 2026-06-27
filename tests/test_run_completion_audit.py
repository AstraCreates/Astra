from backend.run_completion_audit import build_run_completion_audit
from backend.stacks import build_stack_execution_blueprint, get_stack_template
from backend.tools.company_brain import add_company_brain_record
from backend.workflow_state import build_session_state


def _artifact_result(key: str) -> str:
    return f"{key} contains concrete production-ready handoff content with enough detail for downstream execution."


def test_run_completion_audit_passes_complete_stack_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_id = "session_complete"
    founder_id = "founder_complete"
    stack = get_stack_template("sales")
    blueprint = build_stack_execution_blueprint(stack, "Build outbound pipeline", "Astra")
    events = [
        (1, {"type": "goal_start", "goal": "Build outbound pipeline", "founder_id": founder_id}),
        (2, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (3, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (4, {"type": "stack_approval_queue", "approval_queue": [{"key": "send_outbound", "status": "armed", "triggered_by": None}]}),
    ]
    event_id = 5
    for lane in blueprint["lanes"]:
        artifact_keys = [deliverable["artifact_key"] for deliverable in lane["deliverables"]]
        for artifact_key in artifact_keys:
            events.append((event_id, {"type": "stack_artifact", "artifact": {
                "key": artifact_key,
                "title": artifact_key,
                "owner_agent": lane["agent"],
                "required": True,
                "status": "ready",
                "task_id": lane["id"],
                "preview": _artifact_result(artifact_key),
            }}))
            event_id += 1
        events.append((event_id, {"type": "stack_artifact_verification", "verification": {
            "task_id": lane["id"],
            "lane_id": lane["id"],
            "agent": lane["agent"],
            "status": "passed",
            "required_missing": [],
            "required_weak": [],
        }}))
        event_id += 1
        events.append((event_id, {"type": "stack_lane_status", "lane_id": lane["id"], "agent": lane["agent"], "status": "done"}))
        event_id += 1
    events.append((event_id, {"type": "goal_done", "results": {}}))
    add_company_brain_record(
        founder_id=founder_id,
        source="astra",
        title=f"Run Digest - Astra - {session_id}",
        content="Completed sales stack handoff.",
        kind="run_digest",
        metadata={"session_id": session_id},
    )

    state = build_session_state(session_id, events)
    audit = build_run_completion_audit(session_id, state)

    assert audit["ok"] is True
    assert state["completion_audit"]["ok"] is True
    assert not audit["failed"]


def test_run_completion_audit_flags_missing_artifacts_and_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_id = "session_incomplete"
    founder_id = "founder_incomplete"
    stack = get_stack_template("sales")
    blueprint = build_stack_execution_blueprint(stack, "Build outbound pipeline", "Astra")
    first_lane = blueprint["lanes"][0]
    events = [
        (1, {"type": "goal_start", "goal": "Build outbound pipeline", "founder_id": founder_id}),
        (2, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (3, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (4, {"type": "stack_artifact_verification", "verification": {
            "task_id": first_lane["id"],
            "lane_id": first_lane["id"],
            "agent": first_lane["agent"],
            "status": "blocked",
            "required_missing": [first_lane["deliverables"][0]["artifact_key"]],
            "required_weak": [],
        }}),
        (5, {"type": "stack_lane_status", "lane_id": first_lane["id"], "agent": first_lane["agent"], "status": "blocked"}),
        (6, {"type": "goal_done", "results": {}}),
    ]

    state = build_session_state(session_id, events)
    audit = build_run_completion_audit(session_id, state)
    failed_keys = {check["key"] for check in audit["failed"]}

    assert audit["ok"] is False
    assert "lanes_complete" in failed_keys
    assert "company_brain_handoff" in failed_keys


def test_run_completion_audit_flags_failed_deployment_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_id = "session_deploy_broken"
    founder_id = "founder_deploy_broken"
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Launch landing page", "Astra")
    events = [
        (1, {"type": "goal_start", "goal": "Launch landing page", "founder_id": founder_id}),
        (2, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (3, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (4, {"type": "agent_done", "agent": "web", "result": {"deploy_url": "https://broken.example.com"}}),
        (5, {"type": "deployment_check_failed", "agent": "web", "url": "https://broken.example.com", "status": "404"}),
        (6, {"type": "goal_done", "results": {}}),
    ]

    add_company_brain_record(
        founder_id=founder_id,
        source="astra",
        title=f"Run Digest - Astra - {session_id}",
        content="Landing page launch handoff.",
        kind="run_digest",
        metadata={"session_id": session_id},
    )

    state = build_session_state(session_id, events)
    audit = build_run_completion_audit(session_id, state)
    failed_keys = {check["key"] for check in audit["failed"]}

    assert audit["ok"] is False
    assert "deployment_health" in failed_keys

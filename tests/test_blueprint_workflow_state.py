from backend.stacks import build_stack_execution_blueprint, get_stack_template
from backend.workflow_state import build_session_state
from backend.workboard import build_session_workboard


def test_workflow_state_persists_execution_blueprint_and_lane_status():
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Build a waitlist SaaS", "Astra")
    events = [
        (1, {"type": "goal_start", "goal": "Build a waitlist SaaS", "founder_id": "founder_1"}),
        (2, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (3, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (4, {
            "type": "stack_lane_status",
            "lane_id": "t_research",
            "agent": "research",
            "status": "running",
            "phase": "diagnose",
            "title": "Market foundation",
            "next_actor": "agent",
        }),
        (5, {
            "type": "stack_lane_status",
            "lane_id": "t_research",
            "agent": "research",
            "status": "done",
            "summary": "Market foundation complete",
            "ready_artifacts": ["market_brief"],
            "next_actor": "founder_review",
        }),
    ]

    state = build_session_state("session_blueprint", events)

    assert state["execution_blueprint"]["stack_id"] == "idea_to_revenue"
    assert state["lane_status"][0]["lane_id"] == "t_research"
    assert state["lane_status"][0]["status"] == "done"
    assert state["workboard"]["items"][0]["steps"]
    assert state["workboard"]["items"][0]["phase"] == "diagnose"


def test_workflow_state_marks_terminal_agent_without_goal_done_as_stalled():
    events = [
        (1, {"type": "goal_start", "goal": "Build", "founder_id": "founder_1"}),
        (2, {"type": "agent_start", "agent": "research", "task_id": "t1"}),
        (3, {"type": "agent_done", "agent": "research", "result": {"summary": "done"}}),
    ]

    state = build_session_state("session_stalled", events)

    assert state["status"] == "stalled"


def test_workflow_state_marks_done_with_failed_completion_audit_as_stalled():
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Build a waitlist SaaS", "Astra")
    events = [
        (1, {"type": "goal_start", "goal": "Build a waitlist SaaS", "founder_id": "founder_1"}),
        (2, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (3, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (4, {"type": "agent_start", "agent": "design", "task_id": "t_design"}),
        (5, {"type": "goal_done", "results": {}}),
    ]

    state = build_session_state("session_done_but_incomplete", events)

    assert state["status"] == "stalled"
    assert state["completion_audit"]["ok"] is False


def test_workboard_uses_blueprint_lane_packets_without_operating_plan():
    stack = get_stack_template("sales")
    blueprint = build_stack_execution_blueprint(stack, "Build outbound pipeline", "Astra")
    events = [
        (1, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (2, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (3, {
            "type": "stack_lane_status",
            "lane_id": "s_sales",
            "agent": "sales",
            "status": "blocked",
            "phase": "deploy",
            "title": "Pipeline system",
            "blockers": ["Approval needed: Send outbound"],
            "next_actor": "founder",
        }),
    ]

    workboard = build_session_workboard("session_workboard", events)
    sales_item = next(item for item in workboard["items"] if item["agent"] == "sales")

    assert sales_item["status"] == "blocked"
    assert sales_item["next_actor"] == "founder"
    assert sales_item["steps"]
    assert sales_item["connector_dependencies"]
    assert "Approval needed: Send outbound" in sales_item["blockers"]
    assert workboard["execution_blueprint"]["stack_id"] == "sales"


def test_workflow_state_merges_durable_approval_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from backend.approval_workflows import create_approval_request, decide_approval_request

    create_approval_request(
        "session_approvals",
        "outbound_send",
        title="Approve outbound campaign",
        reason="Founder must approve live outreach.",
        action_id="action_1",
        tool="send_email_campaign",
        agent="sales",
        risk_level="high",
    )
    decide_approval_request(
        "session_approvals",
        "outbound_send",
        "approved",
        actor_id="founder_1",
        actor_role="owner",
        note="Looks good.",
    )
    events = [
        (1, {"type": "goal_start", "goal": "Build outbound pipeline", "founder_id": "founder_1"}),
    ]

    state = build_session_state("session_approvals", events)

    assert state["approval_workflow"]["requests"][0]["status"] == "approved"
    approval = next(item for item in state["approvals"] if item["key"] == "outbound_send")
    assert approval["status"] == "approved"
    assert approval["triggered_by"] == "action_1"
    assert approval["required_role"] == "owner"
    assert approval["history"][-1]["event"] == "approved"

from backend.stacks import build_stack_execution_blueprint, get_stack_template, verify_task_artifacts
from backend.workflow_state import build_session_state
from backend.workboard import build_session_workboard


def test_verify_task_artifacts_passes_specific_deliverables():
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Build a creator SaaS", "Astra")
    task = {"id": "t_research", "agent": "research", "expected_artifacts": ["market_brief", "icp_brief"]}
    result = {
        "market_brief": "Creator SaaS market has specific buyer pain around monetization, workflow fragmentation, and launch uncertainty.",
        "icp_brief": "Primary ICP is solo creator operators selling digital products who need a faster path from audience to revenue.",
    }

    verification = verify_task_artifacts(task, result, blueprint)

    assert verification["status"] == "passed"
    assert verification["passed_count"] == 2
    assert verification["missing_count"] == 0


def test_verify_task_artifacts_blocks_missing_required_deliverables():
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Build a creator SaaS", "Astra")
    task = {"id": "t_research", "agent": "research", "expected_artifacts": ["market_brief", "icp_brief"]}
    result = {"summary": ""}

    verification = verify_task_artifacts(task, result, blueprint)

    assert verification["status"] == "blocked"
    assert set(verification["required_missing"]) == {"market_brief", "icp_brief"}


def test_verify_task_artifacts_flags_generic_placeholder_output():
    stack = get_stack_template("sales")
    blueprint = build_stack_execution_blueprint(stack, "Build outbound pipeline", "Astra")
    task = {"id": "s_sales", "agent": "sales", "expected_artifacts": ["crm_pipeline"]}
    result = {"crm_pipeline": "Plan details will appear here."}

    verification = verify_task_artifacts(task, result, blueprint)

    assert verification["status"] == "needs_review"
    assert verification["required_weak"] == ["crm_pipeline"]


def test_verify_task_artifacts_blocks_empty_design_deliverable():
    stack = get_stack_template("idea_to_revenue")
    blueprint = build_stack_execution_blueprint(stack, "Build a creator SaaS", "Astra")
    task = {"id": "t_design", "agent": "design", "expected_artifacts": ["brand_direction"]}
    result = {}

    verification = verify_task_artifacts(task, result, blueprint)

    assert verification["status"] == "blocked"
    assert verification["required_missing"] == ["brand_direction"]


def test_workflow_state_and_workboard_surface_artifact_verification():
    stack = get_stack_template("sales")
    blueprint = build_stack_execution_blueprint(stack, "Build outbound pipeline", "Astra")
    verification = {
        "task_id": "s_sales",
        "lane_id": "s_sales",
        "agent": "sales",
        "status": "blocked",
        "required_missing": ["crm_pipeline"],
        "summary": "Missing required artifacts: crm_pipeline",
        "artifacts": [],
    }
    events = [
        (1, {"type": "stack_selected", "stack": stack.to_public_dict()}),
        (2, {"type": "stack_execution_blueprint", "execution_blueprint": blueprint}),
        (3, {"type": "stack_artifact_verification", "verification": verification}),
        (4, {
            "type": "stack_lane_status",
            "lane_id": "s_sales",
            "agent": "sales",
            "status": "blocked",
            "blockers": ["crm_pipeline"],
            "artifact_verification": verification,
        }),
    ]

    state = build_session_state("session_verify", events)
    workboard = build_session_workboard("session_verify", events)
    sales_item = next(item for item in workboard["items"] if item["agent"] == "sales")

    assert state["artifact_verifications"][0]["status"] == "blocked"
    assert sales_item["artifact_verification"]["required_missing"] == ["crm_pipeline"]
    assert "Missing artifact: crm_pipeline" in sales_item["blockers"]

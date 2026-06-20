from backend.missions.goal_engine import _infer_stage


def test_infer_stage_does_not_require_24h_after_launch_for_traction():
    goal = {
        "goals": [
            {"title": "Build and deploy the MVP", "status": "done", "created_at": "2026-06-20T10:00:00Z"},
            {"title": "Get first 10 real users", "status": "done", "created_at": "2026-06-20T10:05:00Z"},
        ]
    }

    assert _infer_stage(goal) == "first_traction"


def test_infer_stage_wont_jump_to_traction_before_product_is_built():
    goal = {
        "goals": [
            {"title": "Get first 10 real users", "status": "done", "created_at": "2026-06-20T10:05:00Z"},
        ]
    }

    assert _infer_stage(goal) == "pre_launch"

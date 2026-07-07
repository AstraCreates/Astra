from backend.specialists import research


def test_starter_research_defaults_to_normal_mode():
    role = research._build_research_role("research", "SEARCH PLAN", "starter")

    assert "NORMAL RESEARCH MODE" in role
    assert "one focused run_research_pipeline pass" in role
    assert "5-8 distinct cited sources" in role
    assert "SUPER DEEP RESEARCH MODE" not in role
    assert research._research_max_iterations("starter") == 22


def test_team_research_does_not_get_super_deep_mode():
    role = research._build_research_role("research", "SEARCH PLAN", "team")

    assert "NORMAL RESEARCH MODE" in role
    assert research._is_max_research_plan("team") is False
    assert research._research_max_iterations("team") == 22


def test_scale_and_beta_get_super_deep_research_mode():
    for plan in ("scale", "beta"):
        role = research._build_research_role("research", "SEARCH PLAN", plan)

        assert "SUPER DEEP RESEARCH MODE" in role
        assert "15+ distinct cited sources" in role
        assert research._is_max_research_plan(plan) is True
        assert research._research_max_iterations(plan) == 40


def test_explicit_max_iterations_override_entitlement_default():
    assert research._research_max_iterations("starter", requested=7) == 7
    assert research._research_max_iterations("scale", requested=7) == 7


def test_explicit_research_depth_overrides_plan_default():
    quick_role = research._build_research_role("research", "SEARCH PLAN", "beta", "quick")
    normal_role = research._build_research_role("research", "SEARCH PLAN", "beta", "normal")
    max_role = research._build_research_role("research", "SEARCH PLAN", "starter", "max")

    assert "QUICK RESEARCH MODE" in quick_role
    assert "NORMAL RESEARCH MODE" in normal_role
    assert "SUPER DEEP RESEARCH MODE" in max_role
    assert research._research_max_iterations("beta", requested_depth="quick") == 14
    assert research._research_max_iterations("beta", requested_depth="normal") == 22
    assert research._research_max_iterations("starter", requested_depth="max") == 40


def test_research_depth_aliases_normalize():
    assert research._normalize_research_depth("fast") == "quick"
    assert research._normalize_research_depth("deep") == "max"
    assert research._normalize_research_depth("standard") == "normal"
    assert research._normalize_research_depth("nonsense") == ""

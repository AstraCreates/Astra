from backend.specialists import research


def test_starter_research_defaults_to_fast_mode():
    role = research._build_research_role("research", "SEARCH PLAN", "starter")

    assert "FAST RESEARCH MODE" in role
    assert "one focused run_research_pipeline pass" in role
    assert "5-8 distinct cited sources" in role
    assert "SUPER DEEP RESEARCH MODE" not in role
    assert research._research_max_iterations("starter") == 22


def test_team_research_does_not_get_super_deep_mode():
    role = research._build_research_role("research", "SEARCH PLAN", "team")

    assert "FAST RESEARCH MODE" in role
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

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


def test_founder_chosen_depth_override_beats_plan_tier():
    """A starter-plan founder who explicitly asks for research_depth=deep should
    get SUPER DEEP mode; a scale-plan founder who asks for fast should get FAST
    mode — the override is independent of billing tier in both directions."""
    starter_deep = research._build_research_role("research", "SEARCH PLAN", "starter", depth_override="deep")
    assert "SUPER DEEP RESEARCH MODE" in starter_deep
    assert research._research_max_iterations("starter", depth_override="deep") == research._research_max_iterations("scale")

    scale_fast = research._build_research_role("research", "SEARCH PLAN", "scale", depth_override="fast")
    assert "FAST RESEARCH MODE" in scale_fast
    assert research._research_max_iterations("scale", depth_override="fast") == research._research_max_iterations("starter")

    # No override: plan tier still decides, unchanged from before.
    assert research._effective_is_deep("starter", None) is False
    assert research._effective_is_deep("scale", None) is True

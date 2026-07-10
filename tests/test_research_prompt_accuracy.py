from backend.specialists import research


def test_role_prompt_does_not_claim_pipeline_calls_deep_research():
    """Real bug: the role prompt told the model run_research_pipeline 'runs
    deep_research in parallel' / 'deep_research handles content fetching
    internally' — false. run_research_pipeline only calls build_research_queries
    + batch_search (shallow snippets). In a real production session the model
    took the prompt at face value and never called deep_research at all,
    getting shallow/garbage research as a result."""
    role = research._build_research_role("research", "SEARCH PLAN", "starter")
    assert "runs deep_research in parallel" not in role
    assert "handles fetching internally" not in role
    assert "handles content fetching internally" not in role


def test_focus_roles_still_instruct_deep_research_escalation_after_pipeline():
    """deep_research used to be mandated unconditionally after run_research_pipeline;
    it's now an escalation used only when coverage gaps remain (cuts a redundant
    research pass per lane — see perf(cost) commit). This test now guards the
    weaker-but-still-real invariant: the prompt must still tell the model to call
    deep_research when the first pass is thin, not silently drop it."""
    market_role = research._FOCUS_ROLES["research"]
    competitors_role = research._FOCUS_ROLES["research_competitors"]
    assert "sonar_research handles fetching internally" not in market_role
    assert "deep_research handles content fetching internally" not in competitors_role
    assert "deep_research(" in competitors_role
    assert "coverage gaps" in competitors_role

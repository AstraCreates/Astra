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


def test_focus_roles_require_deep_research_after_pipeline():
    market_role = research._FOCUS_ROLES["research"]
    competitors_role = research._FOCUS_ROLES["research_competitors"]
    assert "sonar_research handles fetching internally" not in market_role
    assert "deep_research handles content fetching internally" not in competitors_role
    assert "You MUST also call deep_research" in competitors_role

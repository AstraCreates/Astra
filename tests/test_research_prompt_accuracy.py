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


def test_focus_roles_still_instruct_pipeline_escalation_on_coverage_gaps():
    """deep_research (a standalone escalation tool) was removed from these lanes'
    toolsets entirely when research was redirected through provider-native
    grounded search inside run_research_pipeline itself (no separate scrape+
    synthesize pass needed). This guards the surviving invariant: the prompt
    must still tell the model to call run_research_pipeline AGAIN with refined
    queries when coverage gaps remain, not silently give up after one pass."""
    market_role = research._FOCUS_ROLES["research"]
    competitors_role = research._FOCUS_ROLES["research_competitors"]
    assert "sonar_research handles fetching internally" not in market_role
    assert "deep_research handles content fetching internally" not in competitors_role
    assert "deep_research(" not in competitors_role
    assert "coverage gaps" in competitors_role


def test_customer_and_gtm_roles_start_with_pipeline_before_deep_escalation():
    customers_role = research._FOCUS_ROLES["research_customers"]
    gtm_role = research._FOCUS_ROLES["research_gtm"]

    assert "run_research_pipeline(topic='{topic}', focus='customers')" in customers_role
    assert "run_research_pipeline returns coverage.ready=true" in customers_role
    assert "run_research_pipeline(topic='{topic}', focus='gtm')" in gtm_role
    assert "run_research_pipeline returns coverage.ready=true" in gtm_role


def test_research_focus_role_is_market_only_while_sibling_roles_stay_scoped():
    market_role = research._FOCUS_ROLES["research"]
    competitors_role = research._FOCUS_ROLES["research_competitors"]
    customers_role = research._FOCUS_ROLES["research_customers"]
    gtm_role = research._FOCUS_ROLES["research_gtm"]

    assert "MARKET" in market_role
    assert "TAM/SAM/SOM" in market_role
    assert "COMPETITORS (named companies" not in market_role
    assert "CUSTOMERS (ICP" not in market_role
    assert "GTM (acquisition channels" not in market_role

    assert "COMPETITOR INTELLIGENCE" in competitors_role
    assert "named companies, pricing, features, weaknesses" in competitors_role
    assert "CUSTOMER & ICP INTELLIGENCE" in customers_role
    assert "buyer demographics, job-to-be-done, willingness to pay" in customers_role
    assert "GO-TO-MARKET & DISTRIBUTION INTELLIGENCE" in gtm_role
    assert "how competitors acquire customers, CAC benchmarks" in gtm_role

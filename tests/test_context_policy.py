import json

from backend.core.context_policy import RunContextPolicy, compact_agent_result


def test_run_context_policy_injects_goal_and_cached_brain_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_context_policy"

    from backend.missions.company_goal import reset_for_new_launch, start_goal
    from backend.tools.company_brain import add_company_brain_record

    add_company_brain_record(
        founder_id=founder_id,
        source="manual",
        title="Canonical pricing",
        content="Use founder-led pricing with an enterprise tier.",
        canonical=True,
        stale_risk="low",
    )
    reset_for_new_launch(founder_id, "root_session", "Grow enterprise revenue", "Operate toward revenue")
    start_goal(
        founder_id,
        "Close first enterprise customer",
        [{"title": "Build enterprise GTM", "owner_agents": ["sales"]}],
        kind="planner",
    )

    policy = RunContextPolicy(
        session_id="session_1",
        founder_id=founder_id,
        constraints={"context_policy": {"max_brain_retrievals": 1, "max_context_chars": 8000}},
    )
    task = {"id": "task_1", "agent": "sales", "instruction": "Create sales plan for enterprise pricing"}
    shared = policy.build_agent_shared(base_shared={}, agent_name="sales", task=task, dep_results={})
    shared_again = policy.build_agent_shared(base_shared={}, agent_name="sales", task=task, dep_results={})

    assert "run_context_pack" in shared
    assert shared["current_company_goal"]["current_goal_title"] == "Close first enterprise customer"
    assert shared["current_company_goal"]["agent_goal_tasks"][0]["title"] == "Build enterprise GTM"
    assert "Canonical pricing" in shared["company_brain_context"]
    assert shared_again["run_context_pack"]["policy"]["brain_cache_hit"] is True


def test_policy_writeback_compacts_agent_output_without_raw_blobs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_writeback"
    policy = RunContextPolicy(session_id="session_1", founder_id=founder_id, constraints={})

    raw_html = "<!DOCTYPE html>" + ("x" * 20_000)
    raw_b64 = "A" * 20_000
    result = {
        "summary": "Built landing page and identified next actions.",
        "html": raw_html,
        "base64": raw_b64,
        "sources": [{"content": "raw fetched page"}],
        "repo_url": "https://github.com/acme/app",
        "next_actions": ["Review deploy"],
    }

    compact = compact_agent_result(result)
    assert "html" not in compact
    assert "base64" not in compact
    assert "sources" not in compact

    persisted = policy.persist_agent_result(agent_name="web", task={"id": "w1", "instruction": "build"}, result=result)
    assert persisted["ok"] is True

    from backend.tools.company_brain import get_company_brain

    records = get_company_brain(founder_id)["records"]
    content = json.dumps(records)
    assert "Built landing page" in content
    assert raw_html not in content
    assert raw_b64 not in content


def test_goal_chain_budget_respects_low_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_budget_caps"

    from backend.missions.company_goal import chain_allowed, get_company_goal, reset_for_new_launch

    reset_for_new_launch(founder_id, "root_session", "North star", "Company goal")
    goal = get_company_goal(founder_id)
    goal["budget"] = {
        "max_runs_per_day": 0,
        "max_chained_goals_per_day": 0,
        "max_chained_runs_per_root_session": 1,
        "max_cost_usd_per_run": 0.01,
        "estimated_next_run_cost_usd": 1.0,
    }

    assert chain_allowed(goal) is False


def test_build_agent_shared_compacts_dep_results_per_dependency(tmp_path, monkeypatch):
    """Real bug: prior_results used to be a blind _compact_value(dep_results, 4000)
    char-truncation of the WHOLE combined dep dict — could cut off a useful summary
    while keeping an earlier raw field intact, depending on dict iteration order.
    Now each dependency is run through compact_agent_result (the same extractor
    already trusted for company_brain persistence), so summary-shaped fields always
    survive and raw payloads are always dropped, regardless of size or order."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_dep_results"

    policy = RunContextPolicy(session_id="session_1", founder_id=founder_id, constraints={})
    dep_results = {
        "research": {
            "summary": "Enterprise buyers want SSO and audit logs.",
            "key_findings": ["SSO is a hard requirement", "Audit logs expected by month 2"],
            "raw": "x" * 50_000,
            "sources": [{"url": f"https://example.com/{i}"} for i in range(200)],
        },
        "design": {
            "summary": "Landing page uses a dark hero with a single CTA.",
            "screenshot": "data:image/png;base64," + ("A" * 20_000),
        },
    }
    shared = policy.build_agent_shared(
        base_shared={}, agent_name="sales",
        task={"id": "t1", "instruction": "close a deal"},
        dep_results=dep_results,
    )

    prior = shared["prior_results"]
    assert prior["research"]["summary"] == "Enterprise buyers want SSO and audit logs."
    assert "SSO is a hard requirement" in prior["research"]["key_findings"]
    assert "raw" not in prior["research"]
    assert "sources" not in prior["research"]
    assert prior["design"]["summary"] == "Landing page uses a dark hero with a single CTA."
    assert "screenshot" not in prior["design"]

    # The whole thing should be dramatically smaller than the raw input.
    raw_size = len(json.dumps(dep_results))
    compact_size = len(json.dumps(prior))
    assert compact_size < raw_size * 0.05

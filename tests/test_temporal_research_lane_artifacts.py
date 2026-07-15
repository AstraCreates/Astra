from backend.control_plane.temporal.execution import _derive_step_specs_from_stack


def test_fanned_research_lanes_have_no_individual_artifact_requirement():
    # Regression test for a real incident: _derive_step_specs_from_stack() fans the
    # single legacy "research" task (artifacts=["market_brief","icp_brief",
    # "pricing_hypothesis"]) into several focused parallel lanes (market/competitors/
    # customers/gtm, see core/orchestrator.py's parallel_research_tasks -- the pattern
    # this mirrors) and was cloning that full artifact list onto every fanned lane.
    # Each lane's focus only covers part of the requirement (see _RESEARCH_LANE_FOCUS),
    # so 3 of 4 lanes could never satisfy it and stayed permanently "blocked", looping
    # on every restart. The legacy fan-out never puts `artifacts` on these lanes at all
    # -- match that.
    meta = {"goal": "Build a cap table SaaS for startups", "stack_id": "idea_to_revenue"}

    specs = _derive_step_specs_from_stack(meta)
    research_specs = {tid: spec for tid, spec in specs.items() if str(spec.get("agent", "")).startswith("research")}

    assert research_specs, "expected at least one fanned research lane"
    for tid, spec in research_specs.items():
        assert spec.get("expected_artifacts") == [], f"{tid} ({spec.get('agent')}) should have no per-lane artifact requirement"

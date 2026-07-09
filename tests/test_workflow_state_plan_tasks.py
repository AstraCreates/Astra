from backend.workflow_state import build_session_state


def test_workflow_state_surfaces_plan_tasks_for_page_reload():
    """Real bug: the frontend's live SSE handler stored plan_done's tasks, but
    the /sessions/{id}/state REST snapshot (used on page load/reload, and for
    any session viewed after the planning moment already passed — i.e. almost
    every real session) never carried that data at all, so the "View Plan"
    button only ever appeared if you happened to load the page during the
    exact planning instant. build_session_state must reconstruct plan_tasks
    from the historical event log."""
    events = [
        (1, {"type": "goal_start", "goal": "Launch a company", "founder_id": "f1"}),
        (2, {
            "type": "plan_done",
            "tasks": [
                {"id": "t1", "agent": "research", "instruction": "Research the market"},
                {"id": "t2", "agent": "design", "instruction": "Design the brand"},
            ],
            "planner_model": "moonshotai/kimi-k2.7-code",
        }),
        (3, {"type": "agent_done", "agent": "research", "result": {}}),
        # A second plan_done pass (e.g. research finishes, rest of the plan
        # comes in) only carries its own agents — must merge, not replace.
        (4, {
            "type": "plan_done",
            "tasks": [{"id": "t3", "agent": "marketing", "instruction": "Write launch copy"}],
            "planner_model": "moonshotai/kimi-k2.7-code",
        }),
    ]

    state = build_session_state("session-plan", events)

    assert state["planner_model"] == "moonshotai/kimi-k2.7-code"
    agents = {t["agent"] for t in state["plan_tasks"]}
    assert agents == {"research", "design", "marketing"}


def test_workflow_state_plan_tasks_empty_when_no_plan_done():
    events = [(1, {"type": "goal_start", "goal": "x", "founder_id": "f1"})]
    state = build_session_state("session-no-plan", events)
    assert state["plan_tasks"] == []
    assert state["planner_model"] == ""

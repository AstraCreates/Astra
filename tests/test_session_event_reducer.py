from backend.session_digest import build_session_digest, build_subteam_report
from backend.session_event_reducer import fold_session_events
from backend.workboard import build_session_workboard


def _events():
    return [
        (1, {"type": "company_genome", "genome": {"company_name": "Acme"}}),
        (2, {"type": "stack_selected", "stack": {"name": "Launch Stack", "primary_outcome": "Revenue"}}),
        (3, {
            "type": "stack_operating_plan",
            "operating_plan": {
                "stack_name": "Launch Stack",
                "outcome": "Revenue",
                "lanes": [{"id": "research_lane", "agent": "research", "title": "Research", "mission": "Map buyers"}],
            },
        }),
        (4, {"type": "plan_done", "tasks": [
            {"id": "research_task", "agent": "research", "instruction": "Map buyers"},
            {"id": "sales_task", "agent": "sales", "instruction": "Draft outreach"},
        ]}),
        (5, {"type": "stack_approval_queue", "approval_queue": [
            {"key": "send_outreach", "title": "Send outreach", "status": "armed", "is_phase_gate": True}
        ]}),
        (6, {"type": "agent_start", "agent": "research", "instruction": "Map buyers"}),
        (7, {"type": "agent_done", "agent": "research", "result": {"summary": "Found three segments."}}),
        (8, {"type": "stack_artifact", "artifact": {
            "key": "market_map",
            "owner_agent": "research",
            "status": "ready",
        }}),
        (9, {"type": "outcome_recorded", "outcome": {"agent": "research", "value": 2}}),
        (10, {"type": "saferun_action", "action": {
            "id": "act_1",
            "agent": "research",
            "approval_gate": "send_outreach",
            "approval_required": True,
        }}),
    ]


def test_fold_session_events_collects_shared_reporting_state():
    folded = fold_session_events(_events())

    assert folded.stack["name"] == "Launch Stack"
    assert folded.genome["company_name"] == "Acme"
    assert folded.latest_plan[1]["agent"] == "sales"
    assert folded.agent_state["research"]["status"] == "done"
    assert folded.artifacts_by_agent["research"][0]["key"] == "market_map"
    assert folded.outcomes_by_agent["research"][0]["value"] == 2
    assert folded.saferun_by_agent["research"][0]["id"] == "act_1"
    assert folded.approvals_by_gate["send_outreach"]["status"] == "triggered"


def test_migrated_digest_and_workboard_preserve_public_report_shapes():
    events = _events()

    digest = build_session_digest("sess_report", events)
    workboard = build_session_workboard("sess_report", events)
    research_item = next(item for item in workboard["items"] if item["agent"] == "research")
    sales_item = next(item for item in workboard["items"] if item["agent"] == "sales")

    assert digest["session_id"] == "sess_report"
    assert digest["company_name"] == "Acme"
    assert digest["counts"]["planned_agents"] == 2
    assert digest["counts"]["done_agents"] == 1
    assert digest["counts"]["ready_artifacts"] == 1
    assert digest["counts"]["triggered_approvals"] == 1
    assert digest["next_actions"][:2] == [
        "Decide approval gate: Send outreach",
        "Start pending lane: sales",
    ]

    assert workboard["session_id"] == "sess_report"
    assert workboard["counts"]["total"] == 2
    assert workboard["counts"]["done"] == 1
    assert workboard["counts"]["queued"] == 1
    assert workboard["pending_approvals"][0]["key"] == "send_outreach"
    assert research_item["ready_artifacts"][0]["key"] == "market_map"
    assert research_item["blockers"] == ["Approval needed: Send outreach"]
    assert sales_item["next_actor"] == "agent"


def test_subteam_report_uses_folded_session_state_without_changing_shape():
    events = _events() + [
        (11, {"type": "agent_start", "agent": "sales", "instruction": "Draft outreach"}),
        (12, {"type": "agent_error", "agent": "sales", "error": "Mailbox token expired"}),
        (13, {"type": "saferun_action", "action": {
            "id": "act_2",
            "agent": "sales",
            "approval_gate": "send_discount",
            "approval_required": True,
            "reason": "Discount exceeds default threshold",
        }}),
    ]

    report = build_subteam_report("sess_report", events, "sales")

    assert report["session_id"] == "sess_report"
    assert report["team"] == "sales"
    assert report["agents"] == ["marketing", "research", "sales"]
    assert report["completed"] == [{"agent": "research", "summary": "Found three segments."}]
    assert report["active"] == []
    assert report["pending"] == []
    assert report["outcomes"][0]["agent"] == "research"
    assert [item["id"] for item in report["approvals"]] == ["act_1", "act_2"]
    assert report["blockers"] == [
        "sales: Mailbox token expired",
        "Approval needed for send_outreach: None",
        "Approval needed for send_discount: Discount exceeds default threshold",
    ]
    assert report["next_actions"][0] == "Resolve approval or error blockers before this subteam can safely continue."

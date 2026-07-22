"""Focused tests for deterministic Company OS meeting orchestration."""
from backend import company_os_meetings as meetings


MISSION = {"mission_id": "m1", "squad_id": "s1", "initiative_id": "i1", "name": "Launch", "department": "growth"}
TASK = {"task_id": "t1", "name": "Draft campaign", "owner": "Writer"}


def _store(monkeypatch):
    squad_meetings = []
    monkeypatch.setattr(meetings, "get_company_os", lambda _company_id: {"squad_meetings": squad_meetings})

    def create(_company_id, squad_id, name, **data):
        entry = {"meeting_id": f"meeting-{len(squad_meetings)}", "squad_id": squad_id, "name": name, **data}
        squad_meetings.append(entry)
        return entry

    def update(_company_id, meeting_id, **changes):
        entry = next(item for item in squad_meetings if item["meeting_id"] == meeting_id)
        entry.update(changes)
        return {"meeting_id": meeting_id, **changes}

    monkeypatch.setattr(meetings, "create_squad_meeting", create)
    monkeypatch.setattr(meetings, "update_squad_meeting", update)
    return squad_meetings


def test_creation_is_idempotent_per_squad_mission_task_and_phase(monkeypatch):
    squad_meetings = _store(monkeypatch)

    first = meetings.task_start("co", MISSION, TASK)
    second = meetings.task_start("co", MISSION, TASK)
    other_phase = meetings.review("co", MISSION, TASK)

    assert first == second
    assert len(squad_meetings) == 2
    assert first["meeting_key"] == "s1:m1:t1:task_start"
    assert other_phase["meeting_key"] == "s1:m1:t1:review"


def test_trigger_meetings_covers_lifecycle_and_conditional_checkpoint(monkeypatch):
    squad_meetings = _store(monkeypatch)
    blocked = {**TASK, "state": "blocked", "blocked_reason": "Source access denied"}
    done = {**TASK, "state": "done"}

    assert [item["phase"] for item in meetings.trigger_meetings("co", MISSION, event="before_work")] == ["kickoff"]
    assert [item["phase"] for item in meetings.trigger_meetings("co", MISSION, TASK, event="task_start")] == ["task_start"]
    assert meetings.trigger_meetings("co", MISSION, TASK, event="checkpoint") == []
    assert [item["phase"] for item in meetings.trigger_meetings("co", MISSION, blocked, event="checkpoint")] == ["checkpoint"]
    assert [item["phase"] for item in meetings.trigger_meetings("co", MISSION, TASK, event="pre_synthesis")] == ["review"]
    assert [item["phase"] for item in meetings.trigger_meetings("co", MISSION, done, event="closeout")] == ["closeout"]
    assert len(squad_meetings) == 5


def test_fallback_record_is_structured_role_scoped_and_bounded(monkeypatch):
    _store(monkeypatch)
    poor_evidence = {**TASK, "evidence_validation": {"ok": False, "reason": "x" * 500}}

    record = meetings.checkpoint("co", MISSION, poor_evidence)
    meeting = record

    assert meeting["phase"] == "checkpoint"
    assert meeting["agenda"] and meeting["decisions"] and meeting["blockers"] and meeting["next_actions"]
    assert [participant["role"] for participant in meeting["participants"]] == ["Growth Lead", "Writer"]
    assert len(meeting["lead_summary"]) <= 280
    assert all(len(participant["summary"]) <= 280 for participant in meeting["participants"])


def test_runner_facing_hold_meeting_preserves_supplied_blockers(monkeypatch):
    _store(monkeypatch)

    record = meetings.hold_meeting("co", MISSION, phase="closeout", blockers=["Dependency failed"])

    assert record["phase"] == "closeout"
    assert record["blockers"] == ["Dependency failed"]

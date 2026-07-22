"""Deterministic, bounded meeting orchestration for Company OS work.

Meetings are durable first-class Company OS squad-meeting records.  The module
stays on the public store boundary while retaining structured agendas,
decisions, blockers, and actions for a future presentation layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.company_os import create_squad_meeting, get_company_os, update_squad_meeting

PHASES = ("kickoff", "task_start", "checkpoint", "review", "closeout")
MEETING_PHASES = PHASES
_TERMINAL_STATES = {"done", "complete", "completed", "blocked", "failed", "cancelled"}
_MAX_SUMMARY_LENGTH = 280


def create_meeting(
    company_id: str,
    phase: str,
    mission: Mapping[str, Any],
    task: Mapping[str, Any] | None = None,
    *,
    company: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Create one deterministic meeting for a squad/mission/task/phase.

    Repeated calls return the existing durable record.  No model is invoked:
    a runner can safely call this at every lifecycle boundary without adding
    chatter or nondeterministic state.
    """
    if phase not in PHASES:
        raise ValueError(f"unknown meeting phase: {phase}")
    mission_id = _required_id(mission, "mission_id")
    squad_id = _required_id(mission, "squad_id")
    task_id = str(task.get("task_id") or "") if task else ""
    meeting_key = f"{squad_id}:{mission_id}:{task_id or '-'}:{phase}"
    company = company or _get_company(company_id, root=root)
    record = _fallback_record(phase, mission, task, meeting_key)
    existing = next((entry for entry in company.get("squad_meetings", [])
                     if entry.get("meeting_key") == meeting_key), None)
    if existing:
        # A repeated lifecycle signal can carry newly surfaced blockers. Keep
        # one meeting identity while refreshing its deterministic contents.
        updated = _update_squad_meeting(company_id, str(existing["meeting_id"]), root=root, **record)
        return {**existing, **updated}
    return _create_squad_meeting(
        company_id,
        squad_id,
        _meeting_name(phase, mission, task),
        state="completed",
        mission_id=mission_id,
        task_id=task_id or None,
        participant_role_ids=_participant_role_ids(company, squad_id, mission, task),
        **record,
        root=root,
    )


def kickoff(company_id: str, mission: Mapping[str, Any], *, company: Mapping[str, Any] | None = None,
            root: str | Path | None = None) -> dict[str, Any]:
    """Record the required squad kickoff before mission work begins."""
    return create_meeting(company_id, "kickoff", mission, company=company, root=root)


def task_start(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any], *,
               company: Mapping[str, Any] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    """Record the task-start alignment meeting."""
    return create_meeting(company_id, "task_start", mission, task, company=company, root=root)


def checkpoint(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any], *,
               company: Mapping[str, Any] | None = None, root: str | Path | None = None) -> dict[str, Any] | None:
    """Create a checkpoint only for a material work-health signal."""
    if not needs_checkpoint(task):
        return None
    return create_meeting(company_id, "checkpoint", mission, task, company=company, root=root)


def review(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any], *,
           company: Mapping[str, Any] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    """Record the pre-synthesis review meeting."""
    return create_meeting(company_id, "review", mission, task, company=company, root=root)


def closeout(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any] | None = None, *,
             company: Mapping[str, Any] | None = None, root: str | Path | None = None) -> dict[str, Any] | None:
    """Record terminal done/blocked outcomes, and nothing for active work."""
    subject = task or mission
    if str(subject.get("state") or "").lower() not in _TERMINAL_STATES:
        return None
    return create_meeting(company_id, "closeout", mission, task, company=company, root=root)


def trigger_meetings(
    company_id: str,
    mission: Mapping[str, Any],
    task: Mapping[str, Any] | None = None,
    *,
    event: str,
    company: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Runner-facing lifecycle trigger with a deliberately small event surface."""
    if event == "before_work":
        return [kickoff(company_id, mission, company=company, root=root)]
    if event == "task_start" and task:
        return [task_start(company_id, mission, task, company=company, root=root)]
    if event == "checkpoint" and task:
        record = checkpoint(company_id, mission, task, company=company, root=root)
        return [record] if record else []
    if event == "pre_synthesis" and task:
        return [review(company_id, mission, task, company=company, root=root)]
    if event == "closeout":
        record = closeout(company_id, mission, task, company=company, root=root)
        return [record] if record else []
    raise ValueError(f"unknown or incomplete meeting trigger: {event}")


def hold_meeting(
    company_id: str,
    mission: Mapping[str, Any],
    *,
    phase: str,
    task: Mapping[str, Any] | None = None,
    blockers: list[str] | tuple[str, ...] | None = None,
    company: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Compatibility façade for lifecycle callers such as the mission runner.

    Callers already know why they are convening a checkpoint or closeout, so
    supplied blockers are made durable even before a task/mission transition
    has been persisted.
    """
    if phase not in PHASES:
        raise ValueError(f"unknown meeting phase: {phase}")
    supplied_blockers = [str(item) for item in (blockers or []) if str(item).strip()]
    subject = dict(task or mission)
    if supplied_blockers and not subject.get("blocked_reason"):
        subject["blocked_reason"] = "; ".join(supplied_blockers)
    return create_meeting(
        company_id,
        phase,
        mission,
        subject if task is not None or supplied_blockers else None,
        company=company,
        root=root,
    )


def needs_checkpoint(task: Mapping[str, Any]) -> bool:
    """Return whether a blocked, evidence, or dependency signal needs review."""
    if str(task.get("state") or "").lower() in {"blocked", "failed"} or task.get("blocked_reason"):
        return True
    validation = task.get("evidence_validation")
    if isinstance(validation, Mapping):
        status = str(validation.get("status") or "").lower()
        if validation.get("ok") is False or status in {"failed", "invalid", "insufficient", "poor"}:
            return True
    dependency_state = str(task.get("dependency_state") or task.get("dependencies_status") or "").lower()
    return dependency_state in {"blocked", "failed", "unavailable", "missing"} or bool(task.get("dependency_failure"))


def _fallback_record(phase: str, mission: Mapping[str, Any], task: Mapping[str, Any] | None, meeting_key: str) -> dict[str, Any]:
    subject = str((task or mission).get("name") or "work item")
    mission_name = str(mission.get("name") or "mission")
    blockers = _blockers(task or mission)
    decision = _decision_for(phase, subject, blockers)
    next_action = _next_action_for(phase, subject, blockers)
    return {
        "meeting_key": meeting_key,
        "phase": phase,
        "agenda": _agenda_for(phase, subject),
        "decisions": [decision],
        "blockers": blockers,
        "next_actions": [next_action],
        "lead_summary": _short(f"{mission_name}: {decision} Next: {next_action}"),
        "participants": _participant_summaries(mission, task, decision, next_action),
    }


def _agenda_for(phase: str, subject: str) -> list[str]:
    purpose = {
        "kickoff": "Align mission scope, owner, and success criteria",
        "task_start": "Confirm task inputs and execution handoff",
        "checkpoint": "Resolve the active work-health signal",
        "review": "Check evidence and output before synthesis",
        "closeout": "Confirm outcome, residual blockers, and follow-through",
    }[phase]
    return [purpose, _short(f"Review: {subject}")]


def _decision_for(phase: str, subject: str, blockers: list[str]) -> str:
    if blockers:
        return _short(f"Hold {subject} until the listed blocker is resolved.")
    if phase == "closeout":
        return _short(f"Record {subject} as complete and retain its outcome.")
    return _short(f"Proceed with {subject} under the current mission scope.")


def _next_action_for(phase: str, subject: str, blockers: list[str]) -> str:
    if blockers:
        return _short(f"Owner resolves: {blockers[0]}")
    actions = {"kickoff": "Start the first eligible task.", "task_start": "Execute the assigned task.",
               "checkpoint": "Continue once the checkpoint is clear.", "review": "Synthesize the reviewed evidence.",
               "closeout": "Publish the concise mission update."}
    return _short(f"{actions[phase]} ({subject})")


def _blockers(subject: Mapping[str, Any]) -> list[str]:
    values = [subject.get("blocked_reason"), subject.get("dependency_failure")]
    dependency_state = str(subject.get("dependency_state") or subject.get("dependencies_status") or "").lower()
    if dependency_state in {"blocked", "failed", "unavailable", "missing"}:
        values.append(f"Dependency is {dependency_state}.")
    validation = subject.get("evidence_validation")
    if isinstance(validation, Mapping) and (validation.get("ok") is False or str(validation.get("status") or "").lower() in {"failed", "invalid", "insufficient", "poor"}):
        values.append(str(validation.get("reason") or "Evidence quality requires review."))
    return [_short(str(value)) for value in values if str(value or "").strip()]


def _participant_summaries(mission: Mapping[str, Any], task: Mapping[str, Any] | None,
                           decision: str, next_action: str) -> list[dict[str, str]]:
    department = str(mission.get("department") or "operations").replace("_", " ").title()
    owner = str((task or {}).get("owner") or mission.get("owner") or f"{department} Lead")
    return [
        {"role": f"{department} Lead", "summary": _short(f"Decision: {decision}")},
        {"role": owner, "summary": _short(f"Action: {next_action}")},
    ]


def _meeting_name(phase: str, mission: Mapping[str, Any], task: Mapping[str, Any] | None) -> str:
    subject = str((task or mission).get("name") or "work item")
    return _short(f"{phase.replace('_', ' ').title()}: {subject}")


def _participant_role_ids(company: Mapping[str, Any], squad_id: str, mission: Mapping[str, Any],
                          task: Mapping[str, Any] | None) -> list[str]:
    candidates = [
        (task or {}).get("role_id"),
        mission.get("lead_role_id"),
        mission.get("role_id"),
    ]
    available = {str(role.get("role_id")) for role in company.get("squad_roles", [])
                 if role.get("squad_id") == squad_id and role.get("role_id")}
    return [str(role_id) for role_id in candidates if role_id and str(role_id) in available]


def _short(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:_MAX_SUMMARY_LENGTH]


def _required_id(record: Mapping[str, Any], key: str) -> str:
    value = str(record.get(key) or "")
    if not value:
        raise ValueError(f"meeting mission is missing {key}")
    return value


def _get_company(company_id: str, *, root: str | Path | None) -> Mapping[str, Any]:
    company = get_company_os(company_id, **({"root": root} if root is not None else {}))
    if company is None:
        raise KeyError(f"unknown company: {company_id}")
    return company


def _create_squad_meeting(company_id: str, squad_id: str, name: str, *, root: str | Path | None,
                          **data: Any) -> dict[str, Any]:
    return create_squad_meeting(company_id, squad_id, name, **data, **({"root": root} if root is not None else {}))


def _update_squad_meeting(company_id: str, meeting_id: str, *, root: str | Path | None,
                          **changes: Any) -> dict[str, Any]:
    return update_squad_meeting(company_id, meeting_id, **changes, **({"root": root} if root is not None else {}))

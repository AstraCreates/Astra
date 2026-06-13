from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WebTaskState(str, Enum):
    START = "start"
    SIGNUP = "signup"
    LOGIN = "login"
    VERIFY_EMAIL = "verify_email"
    DASHBOARD = "dashboard"
    SETTINGS = "settings"
    API_KEYS = "api_keys"
    RESOURCE_CREATE = "resource_create"
    QA_FLOW = "qa_flow"
    NEEDS_USER = "needs_user"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


@dataclass
class WebTaskBlocker:
    kind: str = ""
    message: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "fields": list(self.fields),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WebTaskBlocker":
        payload = payload or {}
        return cls(
            kind=str(payload.get("kind") or ""),
            message=str(payload.get("message") or ""),
            fields=list(payload.get("fields") or []),
        )


@dataclass
class WebTaskEvidence:
    final_url: str = ""
    state: str = ""
    checks_passed: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    page_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_url": self.final_url,
            "state": self.state,
            "checks_passed": list(self.checks_passed),
            "screenshots": list(self.screenshots),
            "page_summary": self.page_summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WebTaskEvidence":
        payload = payload or {}
        return cls(
            final_url=str(payload.get("final_url") or ""),
            state=str(payload.get("state") or ""),
            checks_passed=list(payload.get("checks_passed") or []),
            screenshots=list(payload.get("screenshots") or []),
            page_summary=str(payload.get("page_summary") or ""),
        )


@dataclass
class WebTaskRequest:
    task_type: str
    service: str
    goal: str
    success_criteria: list[str] = field(default_factory=list)
    credentials: dict[str, Any] = field(default_factory=dict)
    founder_id: str = ""
    session_id: str = ""
    task_id: str = ""
    agent: str = ""
    start_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "service": self.service,
            "goal": self.goal,
            "success_criteria": list(self.success_criteria),
            "credentials": dict(self.credentials),
            "founder_id": self.founder_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "agent": self.agent,
            "start_url": self.start_url,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WebTaskRequest":
        criteria = payload.get("success_criteria") or []
        if isinstance(criteria, str):
            criteria = [criteria]
        return cls(
            task_type=str(payload.get("task_type") or ""),
            service=str(payload.get("service") or ""),
            goal=str(payload.get("goal") or ""),
            success_criteria=[str(item) for item in criteria if str(item).strip()],
            credentials=dict(payload.get("credentials") or {}),
            founder_id=str(payload.get("founder_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            agent=str(payload.get("agent") or ""),
            start_url=str(payload.get("start_url") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class WebTaskResult:
    status: str
    service: str
    task_type: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    evidence: WebTaskEvidence = field(default_factory=WebTaskEvidence)
    blocker: WebTaskBlocker = field(default_factory=WebTaskBlocker)
    resume_token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "service": self.service,
            "task_type": self.task_type,
            "artifacts": dict(self.artifacts),
            "evidence": self.evidence.to_dict(),
            "blocker": self.blocker.to_dict(),
            "resume_token": self.resume_token,
        }


@dataclass
class WebTaskSnapshot:
    task_id: str
    request: WebTaskRequest
    state: WebTaskState = WebTaskState.START
    status: str = "running"
    artifacts: dict[str, Any] = field(default_factory=dict)
    evidence: WebTaskEvidence = field(default_factory=WebTaskEvidence)
    blocker: WebTaskBlocker = field(default_factory=WebTaskBlocker)
    credentials: dict[str, Any] = field(default_factory=dict)
    input_data: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    current_url: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "request": self.request.to_dict(),
            "state": self.state.value,
            "status": self.status,
            "artifacts": dict(self.artifacts),
            "evidence": self.evidence.to_dict(),
            "blocker": self.blocker.to_dict(),
            "credentials": dict(self.credentials),
            "input_data": dict(self.input_data),
            "notes": list(self.notes),
            "current_url": self.current_url,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WebTaskSnapshot":
        state_raw = str(payload.get("state") or WebTaskState.START.value)
        try:
            state = WebTaskState(state_raw)
        except ValueError:
            state = WebTaskState.START
        return cls(
            task_id=str(payload.get("task_id") or ""),
            request=WebTaskRequest.from_dict(dict(payload.get("request") or {})),
            state=state,
            status=str(payload.get("status") or "running"),
            artifacts=dict(payload.get("artifacts") or {}),
            evidence=WebTaskEvidence.from_dict(payload.get("evidence")),
            blocker=WebTaskBlocker.from_dict(payload.get("blocker")),
            credentials=dict(payload.get("credentials") or {}),
            input_data=dict(payload.get("input_data") or {}),
            notes=list(payload.get("notes") or []),
            current_url=str(payload.get("current_url") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )

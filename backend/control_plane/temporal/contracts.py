"""Shared Temporal control-plane contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TASK_QUEUE = "astra-runs-v1"
WORKFLOW_NAME = "AstraRun"
WORKFLOW_ID_PREFIX = "astra-run"


def workflow_id_for_run(run_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}/{run_id}"


@dataclass
class RunInput:
    """Workflow input for durable run execution."""

    run_id: str
    goal: str
    founder_id: str
    company_id: str = ""
    constraints: Optional[dict] = None
    workspace_id: str = ""
    chapter_id: str = ""


@dataclass
class RunResult:
    """Workflow result for a completed run."""

    run_id: str
    status: str
    error: Optional[str] = None
    session_id: Optional[str] = None

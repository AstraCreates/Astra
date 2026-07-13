import asyncio
import sys
import types

import pytest

from backend.control_plane.temporal import dispatch
from backend.control_plane.temporal.contracts import RunInput, TASK_QUEUE, workflow_id_for_run
from backend.control_plane.temporal.execution import execute_orchestrator_run


@pytest.mark.asyncio
async def test_start_run_uses_ids_only_workflow_input(monkeypatch):
    started: dict[str, object] = {}

    class _FakeClient:
        async def start_workflow(self, workflow_run, workflow_input, *, id, task_queue):
            started["workflow_run"] = workflow_run
            started["workflow_input"] = workflow_input
            started["workflow_id"] = id
            started["task_queue"] = task_queue
            return object()

    async def _fake_get_client():
        return _FakeClient()

    fake_workflows = types.ModuleType("backend.control_plane.temporal.workflows")
    fake_workflows.AstraRunWorkflow = types.SimpleNamespace(run="workflow-run")

    monkeypatch.setattr(dispatch, "_get_client", _fake_get_client)
    monkeypatch.setitem(sys.modules, "backend.control_plane.temporal.workflows", fake_workflows)

    result = await dispatch.start_run(
        run_id="run_123",
        founder_id="founder_1",
        company_id="company_1",
        workspace_id="workspace_1",
        chapter_id="chapter_1",
    )

    workflow_input = started["workflow_input"]
    assert isinstance(workflow_input, RunInput)
    assert workflow_input.run_id == "run_123"
    assert not hasattr(workflow_input, "founder_id")
    assert not hasattr(workflow_input, "company_id")
    assert not hasattr(workflow_input, "workspace_id")
    assert not hasattr(workflow_input, "chapter_id")
    assert not hasattr(workflow_input, "goal")
    assert not hasattr(workflow_input, "constraints")
    assert started["workflow_id"] == workflow_id_for_run("run_123")
    assert started["task_queue"] == TASK_QUEUE
    assert result == {
        "workflow_id": workflow_id_for_run("run_123"),
        "run_id": "run_123",
        "status": "started",
        "task_queue": TASK_QUEUE,
    }


@pytest.mark.asyncio
async def test_execute_orchestrator_run_reuses_run_id_as_session_id():
    orchestrator_call: dict[str, object] = {}
    registered: dict[str, object] = {}
    heartbeats: list[str] = []

    class _FakeOrchestrator:
        async def run(self, *, goal, founder_id, constraints, session_id):
            orchestrator_call["goal"] = goal
            orchestrator_call["founder_id"] = founder_id
            orchestrator_call["constraints"] = constraints
            orchestrator_call["session_id"] = session_id
            await asyncio.sleep(0)
            return {"ok": True}

    def _register_task(session_id, task, *, attempt_id=None, agent_name=""):
        registered["session_id"] = session_id
        registered["attempt_id"] = attempt_id
        registered["task"] = task
        return attempt_id

    result = await execute_orchestrator_run(
        RunInput(
            run_id="run_456",
        ),
        heartbeat=heartbeats.append,
        heartbeat_interval_seconds=0.001,
        get_orchestrator_fn=_FakeOrchestrator,
        get_session_meta_fn=lambda _session_id: {
            "goal": "Launch the company",
            "founder_id": "founder_store",
            "company_id": "company_1",
            "workspace_id": "workspace_1",
            "chapter_id": "chapter_1",
            "constraints": {"stack_id": "idea_to_revenue", "exclude_agents": ["technical"]},
        },
        register_task_fn=_register_task,
        request_kill_fn=lambda _session_id: False,
        is_killed_fn=lambda _session_id: False,
    )

    assert orchestrator_call == {
        "goal": "Launch the company",
        "founder_id": "founder_store",
            "constraints": {
                "stack_id": "idea_to_revenue",
                "exclude_agents": ["technical"],
                "company_id": "company_1",
                "workspace_id": "workspace_1",
            "chapter_id": "chapter_1",
        },
        "session_id": "run_456",
    }
    assert registered["session_id"] == "run_456"
    assert registered["attempt_id"] == "temporal-run:run_456"
    assert result["session_id"] == "run_456"
    assert result["run_id"] == "run_456"
    assert result["status"] == "completed"
    assert "state=starting" in heartbeats[0]
    assert heartbeats[-1] == "run=run_456 state=completed"


@pytest.mark.asyncio
async def test_execute_orchestrator_run_requests_kill_when_durable_status_flips():
    state = {
        "goal": "Ship the product",
        "founder_id": "founder_1",
        "status": "running",
    }
    registered: dict[str, object] = {}
    kill_requests: list[str] = []

    class _FakeOrchestrator:
        async def run(self, *, goal, founder_id, constraints, session_id):
            await asyncio.sleep(0.02)
            return {"ok": True}

    def _register_task(session_id, task, *, attempt_id=None, agent_name=""):
        registered["task"] = task
        return attempt_id

    def _request_kill(session_id: str) -> bool:
        kill_requests.append(session_id)
        task = registered.get("task")
        if task is not None:
            task.cancel()
        return True

    async def _run_and_flip():
        task = asyncio.create_task(
            execute_orchestrator_run(
                RunInput(run_id="run_789"),
                heartbeat_interval_seconds=0.001,
                get_orchestrator_fn=_FakeOrchestrator,
                get_session_meta_fn=lambda _session_id: dict(state),
                register_task_fn=_register_task,
                request_kill_fn=_request_kill,
                is_killed_fn=lambda _session_id: False,
            )
        )
        await asyncio.sleep(0.005)
        state["status"] = "killed"
        return await task

    with pytest.raises(asyncio.CancelledError):
        await _run_and_flip()

    assert kill_requests
    assert kill_requests[0] == "run_789"


@pytest.mark.asyncio
async def test_execute_orchestrator_run_reports_waiting_approval_state(monkeypatch):
    observed_states = []
    heartbeat_states = []
    state = {
        "goal": "Review phase gate",
        "founder_id": "founder_1",
        "status": "running",
    }

    class _FakeOrchestrator:
        async def run(self, *, goal, founder_id, constraints, session_id):
            await asyncio.sleep(0.02)
            return {"ok": True}

    monkeypatch.setattr("backend.core.cancellation.clear", lambda _session_id: None)
    monkeypatch.setattr(
        "backend.control_plane.temporal.execution._extract_waiting_approval",
        lambda _session_id: {"approval_id": "approval_1", "gate_key": "phase_gate"},
    )

    result = await execute_orchestrator_run(
        RunInput(run_id="run_waiting"),
        heartbeat=heartbeat_states.append,
        heartbeat_interval_seconds=0.001,
        get_orchestrator_fn=_FakeOrchestrator,
        get_session_meta_fn=lambda _session_id: dict(state),
        register_task_fn=lambda *args, **kwargs: None,
        request_kill_fn=lambda _session_id: False,
        is_killed_fn=lambda _session_id: False,
        observe_state_fn=observed_states.append,
    )

    assert result["status"] == "completed"
    assert observed_states[0]["workflow_status"] == "running"
    assert any(s["workflow_status"] == "awaiting_approval" for s in observed_states)
    assert observed_states[-1]["workflow_status"] == "succeeded"
    assert any("state=running" in beat for beat in heartbeat_states)


@pytest.mark.asyncio
async def test_dispatch_query_workflow_state_uses_named_queries(monkeypatch):
    queried = []

    class _FakeHandle:
        async def query(self, name):
            queried.append(name)
            return {
                "workflow_status": "running",
                "active_step": "legacy_orchestrator",
                "waiting_approval": {"approval_id": "approval_1"},
                "cancellation_state": {"requested": False},
            }[name]

    class _FakeClient:
        def get_workflow_handle(self, workflow_id):
            assert workflow_id == workflow_id_for_run("run_query")
            return _FakeHandle()

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(dispatch, "_get_client", _fake_get_client)
    result = await dispatch.query_workflow_state("run_query")

    assert queried == ["workflow_status", "active_step", "waiting_approval", "cancellation_state"]
    assert result["workflow_status"] == "running"
    assert result["active_step"] == "legacy_orchestrator"
    assert result["waiting_approval"] == {"approval_id": "approval_1"}


@pytest.mark.asyncio
async def test_dispatch_signals_approval_and_retry(monkeypatch):
    signal_calls = []

    class _FakeHandle:
        async def signal(self, name, arg=None):
            signal_calls.append((name, arg))

    class _FakeClient:
        def get_workflow_handle(self, workflow_id):
            assert workflow_id == workflow_id_for_run("run_signal")
            return _FakeHandle()

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(dispatch, "_get_client", _fake_get_client)

    approved = await dispatch.send_approval_decision(
        "run_signal",
        approval_id="approval_1",
        action_digest="digest_1",
        decision="approved",
        decided_by="owner_1",
    )
    retried = await dispatch.retry_step("run_signal", step_key="research", requested_by="owner_1", note="again")

    assert approved is True
    assert retried is True
    assert signal_calls[0][0] == "approval_decision"
    assert signal_calls[0][1].approval_id == "approval_1"
    assert signal_calls[1][0] == "retry_step"
    assert signal_calls[1][1].step_key == "research"

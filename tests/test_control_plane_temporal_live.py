import asyncio
from pathlib import Path

import pytest

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    temporalio = None

if temporalio is not None:
    from temporalio import workflow


def _install_live_test_activities(monkeypatch, *, execute_impl, observe_impl=None):
    import backend.control_plane.temporal.activities as activities_mod

    @activities_mod.activity.defn(name="PublishEventActivity.publish")
    async def _publish(_run_id: str, _event_type: str, _payload: dict) -> bool:
        return True

    @activities_mod.activity.defn(name="UpdateRunStatusActivity.update")
    async def _update(_run_id: str, _status: str, _error: str | None = None) -> bool:
        return True

    @activities_mod.activity.defn(name="ObserveRunActivity.record")
    async def _observe(_run_id: str, state: dict) -> bool:
        if observe_impl is not None:
            return await observe_impl(_run_id, state)
        return True

    @activities_mod.activity.defn(name="ExecuteOrchestratorActivity.execute")
    async def _execute(_input) -> dict:
        return await execute_impl(_input)

    monkeypatch.setattr(activities_mod.PublishEventActivity, "publish", _publish)
    monkeypatch.setattr(activities_mod.UpdateRunStatusActivity, "update", _update)
    monkeypatch.setattr(activities_mod.ObserveRunActivity, "record", _observe)
    monkeypatch.setattr(activities_mod.ExecuteOrchestratorActivity, "execute", _execute)
    return activities_mod, [_execute, _observe, _publish, _update]


def _install_phase_gate_test_activities(monkeypatch, *, create_impl, expire_impl=None):
    import backend.control_plane.temporal.activities as activities_mod

    @activities_mod.activity.defn(name="CreatePhaseApprovalActivity.create")
    async def _create(run_id: str, gate_key: str, phase_name: str, next_phase: str, artifacts: list[dict]) -> dict:
        return await create_impl(run_id, gate_key, phase_name, next_phase, artifacts)

    @activities_mod.activity.defn(name="ExpireApprovalActivity.expire")
    async def _expire(run_id: str, approval_id: str, action_digest: str, note: str = "") -> bool:
        if expire_impl is not None:
            return await expire_impl(run_id, approval_id, action_digest, note=note)
        return True

    monkeypatch.setattr(activities_mod.CreatePhaseApprovalActivity, "create", _create)
    monkeypatch.setattr(activities_mod.ExpireApprovalActivity, "expire", _expire)
    return activities_mod, [_create, _expire]


if temporalio is not None:
    @workflow.defn(name="Wave3ServerRestartProbe")
    class _ServerRestartProbeWorkflow:
        def __init__(self) -> None:
            self._released = False

        @workflow.signal(name="release")
        async def release(self) -> None:
            self._released = True

        @workflow.run
        async def run(self) -> str:
            await workflow.wait_condition(lambda: self._released)
            return "released"


    @workflow.defn(name="Wave3VersionedProbe")
    class _VersionedProbeWorkflowV1:
        def __init__(self) -> None:
            self._released = False

        @workflow.signal(name="release")
        async def release(self) -> None:
            self._released = True

        @workflow.run
        async def run(self) -> str:
            await workflow.wait_condition(lambda: self._released)
            return "old-path"


    @workflow.defn(name="Wave3VersionedProbe")
    class _VersionedProbeWorkflowV2:
        def __init__(self) -> None:
            self._released = False

        @workflow.signal(name="release")
        async def release(self) -> None:
            self._released = True

        @workflow.run
        async def run(self) -> str:
            await workflow.wait_condition(lambda: self._released)
            if workflow.patched("wave3-versioned-probe-v2"):
                return "new-path"
            return "old-path"


@pytest.mark.asyncio
async def test_live_workflow_handles_query_signal_and_cancel(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import (
        ApprovalDecisionInput,
        RetryStepInput,
        RunInput,
        TASK_QUEUE,
        workflow_id_for_run,
    )
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    observed_states = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def _observe(_run_id: str, state: dict) -> bool:
        observed_states.append(dict(state))
        return True

    async def _execute(_input) -> dict:
        started.set()
        await release.wait()
        return {"session_id": getattr(_input, "run_id", "run_live")}

    _, activities = _install_live_test_activities(monkeypatch, execute_impl=_execute, observe_impl=_observe)

    async with local_workflow_environment() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        ):
            handle = await env.client.start_workflow(
                AstraRunWorkflow.run,
                RunInput(run_id="run_live"),
                id=workflow_id_for_run("run_live"),
                task_queue=TASK_QUEUE,
            )

            await started.wait()

            assert await handle.query("workflow_status") == "running"
            assert await handle.query("active_step") == "legacy_orchestrator"

            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="approval_1",
                action_digest="digest_1",
                decision="approved",
                decided_by="owner_1",
            ))
            await handle.signal("retry_step", RetryStepInput(step_key="research", requested_by="owner_1"))
            await handle.signal("cancel")

            for _ in range(50):
                cancellation_state = await handle.query("cancellation_state")
                if cancellation_state == {"requested": True}:
                    break
                await asyncio.sleep(0.02)
            result = await handle.result()

    assert result.status == "cancelled"
    flattened = [state.get("metadata", {}) for state in observed_states]
    assert any("approval_decision" in meta for meta in flattened)
    assert any("retry_request" in meta for meta in flattened)


@pytest.mark.asyncio
async def test_live_signals_sent_during_worker_outage_are_processed_after_worker_starts(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import (
        ApprovalDecisionInput,
        RetryStepInput,
        RunInput,
        TASK_QUEUE,
        workflow_id_for_run,
    )
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    observed_states = []

    async def _observe(_run_id: str, state: dict) -> bool:
        observed_states.append(dict(state))
        return True

    async def _execute(_input) -> dict:
        return {"session_id": getattr(_input, "run_id", "run_outage")}

    _, activities = _install_live_test_activities(monkeypatch, execute_impl=_execute, observe_impl=_observe)

    async with local_workflow_environment() as env:
        handle = await env.client.start_workflow(
            AstraRunWorkflow.run,
            RunInput(run_id="run_outage"),
            id=workflow_id_for_run("run_outage"),
            task_queue=TASK_QUEUE,
        )

        await handle.signal(
            "approval_decision",
            ApprovalDecisionInput(
                approval_id="approval_outage",
                action_digest="digest_outage",
                decision="approved",
                decided_by="owner_1",
            ),
        )
        await handle.signal(
            "retry_step",
            RetryStepInput(step_key="research", requested_by="owner_1", note="outage replay"),
        )

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        ):
            result = await handle.result()

    assert result.status in {"succeeded", "failed"}
    flattened = [state.get("metadata", {}) for state in observed_states]
    assert any("approval_decision" in meta for meta in flattened)
    assert any("retry_request" in meta for meta in flattened)


@pytest.mark.asyncio
async def test_live_workflow_started_without_worker_completes_after_worker_arrives(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import RunInput, TASK_QUEUE, workflow_id_for_run
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    executed = {"count": 0}

    async def _execute(_input) -> dict:
        executed["count"] += 1
        return {"session_id": getattr(_input, "run_id", "run_delayed_worker")}

    _, activities = _install_live_test_activities(monkeypatch, execute_impl=_execute)

    async with local_workflow_environment() as env:
        handle = await env.client.start_workflow(
            AstraRunWorkflow.run,
            RunInput(run_id="run_delayed_worker"),
            id=workflow_id_for_run("run_delayed_worker"),
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.1)

        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        ):
            result = await handle.result()

    assert result.status in {"succeeded", "failed"}
    assert executed["count"] == 1


@pytest.mark.asyncio
async def test_live_workflow_restarts_worker_before_dispatch_without_reexecuting_activity(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import RunInput, TASK_QUEUE, workflow_id_for_run
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    executed = {"count": 0}

    async def _execute(_input) -> dict:
        executed["count"] += 1
        return {"session_id": getattr(_input, "run_id", "run_restart_before_dispatch")}

    _, activities = _install_live_test_activities(monkeypatch, execute_impl=_execute)

    async with local_workflow_environment() as env:
        worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        )
        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        await worker.shutdown()
        await worker_task

        handle = await env.client.start_workflow(
            AstraRunWorkflow.run,
            RunInput(run_id="run_restart_before_dispatch"),
            id=workflow_id_for_run("run_restart_before_dispatch"),
            task_queue=TASK_QUEUE,
        )

        restarted_worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        )
        restarted_task = asyncio.create_task(restarted_worker.run())
        result = await handle.result()
        await restarted_worker.shutdown()
        await restarted_task

    assert result.status in {"succeeded", "failed"}
    assert executed["count"] == 1


@pytest.mark.asyncio
async def test_live_activity_completes_without_reexecution_after_worker_shutdown_during_dispatch(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import RunInput, TASK_QUEUE, workflow_id_for_run
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    executed = {"count": 0}
    started = asyncio.Event()
    release = asyncio.Event()

    async def _execute(_input) -> dict:
        executed["count"] += 1
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            raise
        return {"session_id": getattr(_input, "run_id", "run_shutdown_after_dispatch")}

    _, activities = _install_live_test_activities(monkeypatch, execute_impl=_execute)

    async with local_workflow_environment() as env:
        worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        )
        worker_task = asyncio.create_task(worker.run())

        handle = await env.client.start_workflow(
            AstraRunWorkflow.run,
            RunInput(run_id="run_shutdown_after_dispatch"),
            id=workflow_id_for_run("run_shutdown_after_dispatch"),
            task_queue=TASK_QUEUE,
        )
        await started.wait()

        await worker.shutdown()
        await worker_task

        restarted_worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[AstraRunWorkflow],
            activities=activities,
        )
        restarted_task = asyncio.create_task(restarted_worker.run())
        release.set()
        result = await handle.result()
        await restarted_worker.shutdown()
        await restarted_task

    assert result.status in {"succeeded", "failed"}
    assert executed["count"] == 1


@pytest.mark.asyncio
async def test_live_workflow_survives_temporal_server_restart(tmp_path: Path):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.testing import local_workflow_environment

    db_file = tmp_path / "temporal-restart.sqlite"
    workflow_id = "wave3-server-restart-probe"

    async with local_workflow_environment(database_filename=str(db_file)) as env:
        worker = Worker(
            env.client,
            task_queue="wave3-server-restart",
            workflows=[_ServerRestartProbeWorkflow],
        )
        worker_task = asyncio.create_task(worker.run())
        handle = await env.client.start_workflow(
            _ServerRestartProbeWorkflow.run,
            id=workflow_id,
            task_queue="wave3-server-restart",
        )
        await worker.shutdown()
        await worker_task

    async with local_workflow_environment(database_filename=str(db_file)) as env:
        worker = Worker(
            env.client,
            task_queue="wave3-server-restart",
            workflows=[_ServerRestartProbeWorkflow],
        )
        worker_task = asyncio.create_task(worker.run())
        handle = env.client.get_workflow_handle(workflow_id)
        await handle.signal("release")
        result = await handle.result()
        await worker.shutdown()
        await worker_task

    assert result == "released"


@pytest.mark.asyncio
async def test_phase_gate_workflow_accepts_exact_matching_approval_signal(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import ApprovalDecisionInput, PhaseGateInput, TASK_QUEUE
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    created = {}

    async def _create(run_id: str, gate_key: str, phase_name: str, next_phase: str, artifacts: list[dict]) -> dict:
        created.update({
            "run_id": run_id,
            "gate_key": gate_key,
            "phase_name": phase_name,
            "next_phase": next_phase,
            "artifacts": artifacts,
        })
        return {"id": "approval_phase_1", "approval_id": "approval_phase_1", "action_digest": "digest_phase_1", "policy_version": "v1"}

    _, activities = _install_phase_gate_test_activities(monkeypatch, create_impl=_create)

    async with local_workflow_environment() as env:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PhaseGateWorkflow], activities=activities):
            handle = await env.client.start_workflow(
                PhaseGateWorkflow.run,
                PhaseGateInput(run_id="run_pg", gate_key="phase_gate_design", phase_name="design", next_phase="deploy"),
                id="phase-gate/run_pg/design",
                task_queue=TASK_QUEUE,
            )
            waiting = None
            for _ in range(50):
                waiting = await handle.query("waiting_approval")
                if waiting is not None:
                    break
                await asyncio.sleep(0.02)
            assert waiting["approval_id"] == "approval_phase_1"

            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="wrong",
                action_digest="digest_phase_1",
                decision="approved",
            ))
            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="approval_phase_1",
                action_digest="digest_phase_1",
                decision="approved",
                policy_version="v1",
                note="go ahead",
            ))
            result = await handle.result()

    assert created["gate_key"] == "phase_gate_design"
    assert result.decision == "approved"
    assert result.approval_id == "approval_phase_1"
    assert result.note == "go ahead"


@pytest.mark.asyncio
async def test_phase_gate_workflow_ignores_conflicting_duplicate_or_wrong_policy_decisions(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import ApprovalDecisionInput, PhaseGateInput, TASK_QUEUE
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    async def _create(_run_id: str, _gate_key: str, _phase_name: str, _next_phase: str, _artifacts: list[dict]) -> dict:
        return {"id": "approval_phase_conflict", "approval_id": "approval_phase_conflict", "action_digest": "digest_conflict", "policy_version": "v7"}

    _, activities = _install_phase_gate_test_activities(monkeypatch, create_impl=_create)

    async with local_workflow_environment() as env:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PhaseGateWorkflow], activities=activities):
            handle = await env.client.start_workflow(
                PhaseGateWorkflow.run,
                PhaseGateInput(run_id="run_pg_conflict", gate_key="phase_gate_design", phase_name="design", next_phase="deploy"),
                id="phase-gate/run_pg_conflict/design",
                task_queue=TASK_QUEUE,
            )
            for _ in range(50):
                waiting = await handle.query("waiting_approval")
                if waiting is not None:
                    break
                await asyncio.sleep(0.02)

            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="approval_phase_conflict",
                action_digest="digest_conflict",
                decision="approved",
                policy_version="wrong",
            ))
            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="approval_phase_conflict",
                action_digest="digest_conflict",
                decision="approved",
                policy_version="v7",
                note="first",
            ))
            await handle.signal("approval_decision", ApprovalDecisionInput(
                approval_id="approval_phase_conflict",
                action_digest="digest_conflict",
                decision="rejected",
                policy_version="v7",
                note="conflict",
            ))
            result = await handle.result()

    assert result.decision == "approved"
    assert result.note == "first"


@pytest.mark.asyncio
async def test_phase_gate_workflow_expires_when_no_decision_arrives(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import PhaseGateInput, TASK_QUEUE
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    expired = []

    async def _create(_run_id: str, _gate_key: str, _phase_name: str, _next_phase: str, _artifacts: list[dict]) -> dict:
        return {"id": "approval_phase_2", "approval_id": "approval_phase_2", "action_digest": "digest_phase_2"}

    async def _expire(run_id: str, approval_id: str, action_digest: str, *, note: str = "") -> bool:
        expired.append((run_id, approval_id, action_digest, note))
        return True

    _, activities = _install_phase_gate_test_activities(monkeypatch, create_impl=_create, expire_impl=_expire)

    async with local_workflow_environment() as env:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PhaseGateWorkflow], activities=activities):
            handle = await env.client.start_workflow(
                PhaseGateWorkflow.run,
                PhaseGateInput(
                    run_id="run_pg_timeout",
                    gate_key="phase_gate_deploy",
                    phase_name="deploy",
                    next_phase="govern",
                    timeout_seconds=1,
                ),
                id="phase-gate/run_pg_timeout/deploy",
                task_queue=TASK_QUEUE,
            )
            result = await handle.result()

    assert result.decision == "expired"
    assert expired == [("run_pg_timeout", "approval_phase_2", "digest_phase_2", "")]


@pytest.mark.asyncio
async def test_lane_attempt_workflow_executes_single_bounded_attempt(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import LaneAttemptInput, TASK_QUEUE
    from backend.control_plane.temporal.lane_attempt_workflow import LaneAttemptWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    called = []

    async def _fake_execute(input, **_kwargs):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        called.append((run_id, step_key))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "step_id": "step_live_1",
            "agent": "design",
            "status": "succeeded",
            "attempt_number": 1,
            "result": {"summary": "ok"},
        }

    async def _fake_verify(input):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        called.append((run_id, f"{step_key}:verify"))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "agent": "design",
            "status": "passed",
            "verification": {"status": "passed", "summary": "good"},
        }

    monkeypatch.setattr(
        "backend.control_plane.temporal.activities.execute_lane_attempt",
        _fake_execute,
    )
    monkeypatch.setattr(
        "backend.control_plane.temporal.activities.execute_verification",
        _fake_verify,
    )

    from backend.control_plane.temporal.activities import ExecuteLaneAttemptActivity, ExecuteVerificationActivity

    async with local_workflow_environment() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LaneAttemptWorkflow],
            activities=[ExecuteLaneAttemptActivity.execute, ExecuteVerificationActivity.execute],
        ):
            handle = await env.client.start_workflow(
                LaneAttemptWorkflow.run,
                LaneAttemptInput(run_id="run_lane_live", step_key="design_lane"),
                id="lane-attempt/run_lane_live/design_lane",
                task_queue=TASK_QUEUE,
            )
            result = await handle.result()

    assert called == [("run_lane_live", "design_lane"), ("run_lane_live", "design_lane:verify")]
    assert result.status == "succeeded"
    assert result.step_id == "step_live_1"
    assert result.verification["status"] == "passed"


@pytest.mark.asyncio
async def test_phase_run_workflow_coordinates_lanes_then_gate(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import PhaseRunInput, TASK_QUEUE
    from backend.control_plane.temporal.lane_attempt_workflow import LaneAttemptWorkflow
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.phase_workflow import PhaseRunWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    calls = []

    async def _fake_execute(input, **_kwargs):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        calls.append(("lane", run_id, step_key))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "step_id": f"step_{step_key}",
            "agent": step_key,
            "status": "succeeded",
            "attempt_number": 1,
            "result": {"summary": "ok"},
        }

    async def _fake_verify(input):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        calls.append(("verify", run_id, step_key))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "agent": step_key,
            "status": "passed",
            "verification": {"status": "passed", "summary": f"{step_key} good"},
        }

    async def _create(run_id: str, gate_key: str, phase_name: str, next_phase: str, artifacts: list[dict]) -> dict:
        calls.append(("gate_create", run_id, gate_key, phase_name, next_phase, len(artifacts)))
        return {"id": "approval_phase_x", "approval_id": "approval_phase_x", "action_digest": "digest_phase_x"}

    monkeypatch.setattr("backend.control_plane.temporal.activities.execute_lane_attempt", _fake_execute)
    monkeypatch.setattr("backend.control_plane.temporal.activities.execute_verification", _fake_verify)

    _, gate_activities = _install_phase_gate_test_activities(monkeypatch, create_impl=_create)

    from backend.control_plane.temporal.activities import (
        CreatePhaseApprovalActivity,
        ExecuteLaneAttemptActivity,
        ExecuteVerificationActivity,
    )

    activities = [
        ExecuteLaneAttemptActivity.execute,
        ExecuteVerificationActivity.execute,
        CreatePhaseApprovalActivity.create,
        gate_activities[1],
    ]

    async with local_workflow_environment() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LaneAttemptWorkflow, PhaseGateWorkflow, PhaseRunWorkflow],
            activities=activities,
        ):
            handle = await env.client.start_workflow(
                PhaseRunWorkflow.run,
                PhaseRunInput(
                    run_id="run_phase_live",
                    phase_name="design",
                    next_phase="deploy",
                    step_keys=["design", "marketing"],
                    timeout_seconds=30,
                ),
                id="phase-run/run_phase_live/design",
                task_queue=TASK_QUEUE,
            )
            waiting = None
            for _ in range(50):
                waiting = await handle.query("waiting_gate")
                if waiting == "design":
                    break
                await asyncio.sleep(0.02)
            await handle.signal("approval_decision", {
                "approval_id": "approval_phase_x",
                "action_digest": "digest_phase_x",
                "decision": "approved",
                "note": "looks good",
            })
            result = await handle.result()

    assert ("lane", "run_phase_live", "design") in calls
    assert ("lane", "run_phase_live", "marketing") in calls
    assert ("verify", "run_phase_live", "design") in calls
    assert ("verify", "run_phase_live", "marketing") in calls
    assert ("gate_create", "run_phase_live", "phase_gate_design", "design", "deploy", 2) in calls
    assert result.status == "approved"
    assert result.decision == "approved"
    assert len(result.lane_results) == 2


@pytest.mark.asyncio
async def test_multi_phase_workflow_progresses_across_two_phases(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.contracts import MultiPhaseRunInput, PhaseRunInput, TASK_QUEUE
    from backend.control_plane.temporal.lane_attempt_workflow import LaneAttemptWorkflow
    from backend.control_plane.temporal.multi_phase_workflow import MultiPhaseRunWorkflow
    from backend.control_plane.temporal.phase_gate_workflow import PhaseGateWorkflow
    from backend.control_plane.temporal.phase_workflow import PhaseRunWorkflow
    from backend.control_plane.temporal.testing import local_workflow_environment

    calls = []

    async def _fake_execute(input, **_kwargs):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        calls.append(("lane", run_id, step_key))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "step_id": f"step_{step_key}",
            "agent": step_key,
            "status": "succeeded",
            "attempt_number": 1,
            "result": {"summary": "ok"},
        }

    async def _fake_verify(input):
        run_id = input["run_id"] if isinstance(input, dict) else input.run_id
        step_key = input["step_key"] if isinstance(input, dict) else input.step_key
        calls.append(("verify", run_id, step_key))
        return {
            "run_id": run_id,
            "step_key": step_key,
            "agent": step_key,
            "status": "passed",
            "verification": {"status": "passed", "summary": f"{step_key} good"},
        }

    async def _create(run_id: str, gate_key: str, phase_name: str, next_phase: str, artifacts: list[dict]) -> dict:
        calls.append(("gate_create", run_id, gate_key, phase_name, next_phase))
        return {
            "id": f"approval_{phase_name}",
            "approval_id": f"approval_{phase_name}",
            "action_digest": f"digest_{phase_name}",
        }

    monkeypatch.setattr("backend.control_plane.temporal.activities.execute_lane_attempt", _fake_execute)
    monkeypatch.setattr("backend.control_plane.temporal.activities.execute_verification", _fake_verify)
    _, gate_activities = _install_phase_gate_test_activities(monkeypatch, create_impl=_create)

    from backend.control_plane.temporal.activities import (
        CreatePhaseApprovalActivity,
        ExecuteLaneAttemptActivity,
        ExecuteVerificationActivity,
    )

    activities = [
        ExecuteLaneAttemptActivity.execute,
        ExecuteVerificationActivity.execute,
        CreatePhaseApprovalActivity.create,
        gate_activities[1],
    ]

    async with local_workflow_environment() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LaneAttemptWorkflow, PhaseGateWorkflow, PhaseRunWorkflow, MultiPhaseRunWorkflow],
            activities=activities,
        ):
            handle = await env.client.start_workflow(
                MultiPhaseRunWorkflow.run,
                MultiPhaseRunInput(
                    run_id="run_multi_phase",
                    phases=[
                        PhaseRunInput(run_id="run_multi_phase", phase_name="design", next_phase="deploy", step_keys=["design"]),
                        PhaseRunInput(run_id="run_multi_phase", phase_name="deploy", next_phase="govern", step_keys=["web"]),
                    ],
                ),
                id="multi-phase/run_multi_phase",
                task_queue=TASK_QUEUE,
            )
            for _ in range(100):
                if await handle.query("active_phase") == "design":
                    break
                await asyncio.sleep(0.05)
            await handle.signal("approval_decision", {
                "approval_id": "approval_design",
                "action_digest": "digest_design",
                "decision": "approved",
            })
            for _ in range(100):
                if await handle.query("active_phase") == "deploy":
                    break
                await asyncio.sleep(0.05)
            await handle.signal("approval_decision", {
                "approval_id": "approval_deploy",
                "action_digest": "digest_deploy",
                "decision": "approved",
            })
            result = await handle.result()

    assert result.status == "approved"
    assert [phase["phase_name"] for phase in result.completed_phases] == ["design", "deploy"]
    assert ("gate_create", "run_multi_phase", "phase_gate_design", "design", "deploy") in calls
    assert ("gate_create", "run_multi_phase", "phase_gate_deploy", "deploy", "govern") in calls


@pytest.mark.asyncio
async def test_live_workflow_handles_code_version_change_with_patch_marker(tmp_path: Path):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")

    from temporalio.worker import Worker

    from backend.control_plane.temporal.testing import local_workflow_environment

    db_file = tmp_path / "temporal-versioning.sqlite"
    workflow_id = "wave3-versioned-probe"

    async with local_workflow_environment(database_filename=str(db_file)) as env:
        worker = Worker(
            env.client,
            task_queue="wave3-versioned",
            workflows=[_VersionedProbeWorkflowV1],
        )
        worker_task = asyncio.create_task(worker.run())
        await env.client.start_workflow(
            _VersionedProbeWorkflowV1.run,
            id=workflow_id,
            task_queue="wave3-versioned",
        )
        await worker.shutdown()
        await worker_task

    async with local_workflow_environment(database_filename=str(db_file)) as env:
        worker = Worker(
            env.client,
            task_queue="wave3-versioned",
            workflows=[_VersionedProbeWorkflowV2],
        )
        worker_task = asyncio.create_task(worker.run())
        handle = env.client.get_workflow_handle(workflow_id)
        await handle.signal("release")
        result = await handle.result()
        await worker.shutdown()
        await worker_task

    assert result == "new-path"

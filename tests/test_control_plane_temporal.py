import asyncio
import sys
import types

import pytest

from backend.control_plane.models import RunStep

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in CI environments without temporalio
    temporalio = None

if temporalio is not None:
    from backend.control_plane.temporal.codec import PassthroughPayloadCodec
    from backend.control_plane.temporal.testing import local_workflow_environment
    from backend.control_plane.temporal.contracts import ApprovalDecisionInput, LaneAttemptInput, RetryStepInput, VerificationInput


def _install_fake_workflows_module(monkeypatch):
    workflows_module = types.ModuleType("backend.control_plane.temporal.workflows")

    class AstraRunWorkflow:
        async def run(self):
            return None

    workflows_module.AstraRunWorkflow = AstraRunWorkflow
    monkeypatch.setitem(sys.modules, "backend.control_plane.temporal.workflows", workflows_module)
    return AstraRunWorkflow


@pytest.mark.asyncio
async def test_local_workflow_environment_starts_and_shuts_down_cleanly():
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    async with local_workflow_environment() as env:
        assert env is not None


@pytest.mark.asyncio
async def test_passthrough_codec_returns_payloads_unchanged():
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    codec = PassthroughPayloadCodec()
    payloads = ["a", "b", "c"]
    encoded = await codec.encode(payloads)
    decoded = await codec.decode(encoded)
    assert encoded == payloads
    assert decoded == payloads


@pytest.mark.asyncio
async def test_start_run_uses_ids_only_contract_and_stable_ids(monkeypatch):
    AstraRunWorkflow = _install_fake_workflows_module(monkeypatch)
    import backend.control_plane.temporal.dispatch as dispatch

    calls = {}

    class _FakeClient:
        async def start_workflow(self, workflow, workflow_input, *, id, task_queue):
            calls["workflow"] = workflow
            calls["workflow_input"] = workflow_input
            calls["id"] = id
            calls["task_queue"] = task_queue
            return types.SimpleNamespace()

    async def fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(dispatch, "_get_client", fake_get_client)

    result = await dispatch.start_run(
        run_id="sess_temporal_1",
        founder_id="founder-1",
        company_id="company-1",
        workspace_id="workspace-1",
        chapter_id="chapter-1",
    )

    assert calls["workflow"] is AstraRunWorkflow.run
    assert isinstance(calls["workflow_input"], dispatch.RunInput)
    assert calls["workflow_input"].run_id == "sess_temporal_1"
    assert not hasattr(calls["workflow_input"], "founder_id")
    assert not hasattr(calls["workflow_input"], "company_id")
    assert not hasattr(calls["workflow_input"], "workspace_id")
    assert not hasattr(calls["workflow_input"], "chapter_id")
    assert not hasattr(calls["workflow_input"], "goal")
    assert not hasattr(calls["workflow_input"], "constraints")
    assert calls["id"] == "astra-run/sess_temporal_1"
    assert result["run_id"] == "sess_temporal_1"


@pytest.mark.asyncio
async def test_execute_orchestrator_run_reuses_run_id_and_keeps_heartbeating(monkeypatch):
    from backend.control_plane.temporal.contracts import RunInput
    from backend.control_plane.temporal.execution import execute_orchestrator_run

    heartbeats = []
    calls = {}

    class _FakeOrchestrator:
        async def run(self, **kwargs):
            calls.update(kwargs)
            await asyncio.sleep(0.035)
            return {"ok": True}

    monkeypatch.setattr("backend.core.cancellation.clear", lambda _session_id: None)

    result = await execute_orchestrator_run(
        RunInput(
            run_id="sess_temporal_2",
        ),
        heartbeat=heartbeats.append,
        heartbeat_interval_seconds=0.01,
        get_orchestrator_fn=lambda: _FakeOrchestrator(),
        get_session_meta_fn=lambda _run_id: {
            "goal": "fallback goal",
            "founder_id": "founder-2",
            "company_id": "company-2",
            "workspace_id": "workspace-2",
            "chapter_id": "chapter-2",
            "constraints": {"agents": ["research"]},
        },
        register_task_fn=lambda *args, **kwargs: None,
        request_kill_fn=lambda _session_id: False,
        is_killed_fn=lambda _session_id: False,
    )

    assert calls["session_id"] == "sess_temporal_2"
    assert calls["goal"] == "fallback goal"
    assert calls["constraints"]["agents"] == ["research"]
    assert calls["constraints"]["company_id"] == "company-2"
    assert result["session_id"] == "sess_temporal_2"
    assert heartbeats[0] == "run=sess_temporal_2 state=starting"
    assert heartbeats[-1] == "run=sess_temporal_2 state=completed"
    assert any(beat == "run=sess_temporal_2 state=running" for beat in heartbeats)


@pytest.mark.asyncio
async def test_execute_orchestrator_run_cancellation_kills_the_same_run_id(monkeypatch):
    from backend.control_plane.temporal.contracts import RunInput
    from backend.control_plane.temporal.execution import execute_orchestrator_run

    started = asyncio.Event()
    killed = []

    class _FakeOrchestrator:
        async def run(self, **kwargs):
            started.set()
            await asyncio.sleep(3600)

    monkeypatch.setattr("backend.core.cancellation.clear", lambda _session_id: None)

    task = asyncio.create_task(
        execute_orchestrator_run(
            RunInput(run_id="sess_temporal_3"),
            heartbeat_interval_seconds=0.01,
            get_orchestrator_fn=lambda: _FakeOrchestrator(),
            get_session_meta_fn=lambda _run_id: {"goal": "Cancel me", "founder_id": "founder-3"},
            register_task_fn=lambda *args, **kwargs: None,
            request_kill_fn=lambda session_id: killed.append(session_id) or True,
            is_killed_fn=lambda _session_id: False,
        )
    )

    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert killed == ["sess_temporal_3"]


@pytest.mark.asyncio
async def test_execute_lane_attempt_persists_durable_step_attempt_and_result(monkeypatch):
    from backend.control_plane.fakes import FakeRunStepRepository
    from backend.control_plane.temporal.execution import execute_lane_attempt

    step_repo = FakeRunStepRepository()
    published = []
    merged_meta = {}

    class _FakeAgent:
        async def run(self, ctx):
            assert ctx.goal == "Draft the launch brief"
            assert ctx.founder_id == "founder-lane"
            assert ctx.shared["constraints"]["company_id"] == "company-lane"
            return {"summary": "done"}

    class _FakeOrchestrator:
        specialists = {"marketing": _FakeAgent()}

    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda _run_id, **fields: merged_meta.update(fields))

    result = await execute_lane_attempt(
        LaneAttemptInput(run_id="run_lane_1", step_key="marketing_lane"),
        get_orchestrator_fn=lambda: _FakeOrchestrator(),
        get_session_meta_fn=lambda _run_id: {
            "goal": "Fallback goal",
            "founder_id": "founder-lane",
            "company_id": "company-lane",
            "constraints": {"company_id": "company-lane"},
            "temporal_step_specs": {
                "marketing_lane": {
                    "agent": "marketing",
                    "instruction": "Draft the launch brief",
                    "phase": "launch",
                    "task_id": "task_marketing",
                    "base_shared": {"constraints": {"company_id": "company-lane"}, "company_id": "company-lane"},
                    "dep_results": {"research": {"summary": "validated"}},
                    "task_brief": {"title": "Launch brief"},
                },
            },
        },
        step_repo=step_repo,
        publish_event_fn=lambda session_id, payload: published.append((session_id, payload)),
    )

    latest = step_repo.get_latest_attempt("run_lane_1", "marketing_lane")
    assert latest is not None
    assert latest.agent == "marketing"
    assert latest.status == "succeeded"
    assert latest.attempt_number == 1
    assert latest.started_at is not None
    assert latest.completed_at is not None
    assert result["status"] == "succeeded"
    assert result["agent"] == "marketing"
    assert result["attempt_number"] == 1
    assert "\"summary\": \"done\"" in (latest.output_ref or "")
    assert merged_meta["temporal_step_specs"]["marketing_lane"]["latest_result"]["summary"] == "done"
    assert [event[1]["type"] for event in published] == ["agent_start", "agent_done"]


@pytest.mark.asyncio
async def test_execute_lane_attempt_heartbeats_and_cancels_bounded_attempt(monkeypatch):
    from backend.control_plane.fakes import FakeRunStepRepository
    from backend.control_plane.temporal.execution import execute_lane_attempt

    step_repo = FakeRunStepRepository()
    published = []
    heartbeats = []
    cancel_state = {"count": 0}

    class _FakeAgent:
        async def run(self, _ctx):
            await asyncio.sleep(3600)

    class _FakeOrchestrator:
        specialists = {"design": _FakeAgent()}

    monkeypatch.setattr("backend.core.session_store.merge_session_meta", lambda _run_id, **fields: None)

    def _is_cancelled() -> bool:
        cancel_state["count"] += 1
        return cancel_state["count"] >= 2

    with pytest.raises(asyncio.CancelledError):
        await execute_lane_attempt(
            LaneAttemptInput(run_id="run_lane_cancel", step_key="design_lane"),
            get_orchestrator_fn=lambda: _FakeOrchestrator(),
            get_session_meta_fn=lambda _run_id: {
                "goal": "Design the page",
                "founder_id": "founder-cancel",
                "constraints": {"company_id": "company-cancel"},
                "temporal_step_specs": {
                    "design_lane": {
                        "agent": "design",
                        "instruction": "Design the page",
                        "task_id": "task_design",
                        "base_shared": {"constraints": {"company_id": "company-cancel"}},
                    },
                },
            },
            step_repo=step_repo,
            publish_event_fn=lambda session_id, payload: published.append((session_id, payload)),
            heartbeat_fn=heartbeats.append,
            is_cancelled_fn=_is_cancelled,
            heartbeat_interval_seconds=0.01,
        )

    latest = step_repo.get_latest_attempt("run_lane_cancel", "design_lane")
    assert latest is not None
    assert latest.status == "cancelled"
    assert heartbeats[0]["state"] == "starting"
    assert any(beat["state"] == "running" for beat in heartbeats[1:])
    assert [event[1]["type"] for event in published] == ["agent_start"]


@pytest.mark.asyncio
async def test_execute_lane_attempt_marks_failed_step_attempt(monkeypatch):
    from backend.control_plane.fakes import FakeRunStepRepository
    from backend.control_plane.temporal.execution import execute_lane_attempt

    step_repo = FakeRunStepRepository()
    published = []

    class _FakeAgent:
        async def run(self, _ctx):
            raise RuntimeError("lane boom")

    class _FakeOrchestrator:
        specialists = {"technical": _FakeAgent()}

    with pytest.raises(RuntimeError, match="lane boom"):
        await execute_lane_attempt(
            LaneAttemptInput(run_id="run_lane_2", step_key="technical_lane"),
            get_orchestrator_fn=lambda: _FakeOrchestrator(),
            get_session_meta_fn=lambda _run_id: {
                "goal": "Fallback goal",
                "founder_id": "founder-lane",
                "constraints": {"company_id": "company-lane"},
                "temporal_step_specs": {
                    "technical_lane": {
                        "agent": "technical",
                        "instruction": "Build the scaffold",
                        "task_id": "task_tech",
                        "base_shared": {"constraints": {"company_id": "company-lane"}},
                    },
                },
            },
            step_repo=step_repo,
            publish_event_fn=lambda session_id, payload: published.append((session_id, payload)),
        )

    latest = step_repo.get_latest_attempt("run_lane_2", "technical_lane")
    assert latest is not None
    assert latest.status == "failed"
    assert latest.error == "lane boom"
    assert [event[1]["type"] for event in published] == ["agent_start", "agent_error"]


@pytest.mark.asyncio
async def test_execute_verification_runs_deep_verification_and_publishes_event(monkeypatch):
    from backend.control_plane.fakes import FakeRunStepRepository
    from backend.control_plane.temporal.execution import execute_verification

    step_repo = FakeRunStepRepository()
    step = step_repo.create_attempt(RunStep(
        id="step_verify_1",
        run_id="run_verify_1",
        step_key="web_lane",
        kind="agent",
        agent="web",
        status="running",
    ))
    published = []

    class _FakeOrchestrator:
        async def _verify_llm_call(self, _messages):
            return '{"verdict":"pass","issues":[]}'

    result = await execute_verification(
        VerificationInput(run_id="run_verify_1", step_key="web_lane", attempt_number=1),
        get_orchestrator_fn=lambda: _FakeOrchestrator(),
        get_session_meta_fn=lambda _run_id: {
            "goal": "Fallback goal",
            "temporal_step_specs": {
                "web_lane": {
                    "agent": "web",
                    "instruction": "Build landing page",
                    "task_id": "task_web",
                    "expected_artifacts": ["landing_page"],
                    "execution_blueprint": None,
                    "latest_result": {"deploy_url": "https://example.com", "summary": "live"},
                },
            },
        },
        step_repo=step_repo,
        publish_event_fn=lambda session_id, payload: published.append((session_id, payload)),
    )

    assert result["status"] in {"passed", "needs_review"}
    assert result["agent"] == "web"
    assert published[-1][1]["type"] == "stack_artifact_verification"
    latest = step_repo.get_latest_attempt("run_verify_1", "web_lane")
    assert latest is not None
    assert latest.heartbeat_at is not None


def test_build_multi_phase_run_input_groups_steps_by_phase():
    from backend.control_plane.temporal.execution import build_multi_phase_run_input

    plan = build_multi_phase_run_input(
        "run_plan_1",
        {
            "temporal_phase_order": ["design", "deploy"],
            "temporal_step_specs": {
                "design_copy": {"phase": "design"},
                "design_ui": {"phase": "design"},
                "web_ship": {"phase": "deploy"},
            },
        },
    )

    assert plan is not None
    assert [phase.phase_name for phase in plan.phases] == ["design", "deploy"]
    assert plan.phases[0].step_keys == ["design_copy", "design_ui"]
    assert plan.phases[0].next_phase == "deploy"
    assert plan.phases[1].step_keys == ["web_ship"]
    assert plan.phases[1].next_phase == "complete"
    assert plan.phases[1].step_dependencies == {"web_ship": []}


def test_build_multi_phase_run_input_falls_back_to_stack_template():
    from backend.control_plane.temporal.execution import build_multi_phase_run_input

    plan = build_multi_phase_run_input(
        "run_plan_stack",
        {
            "goal": "Build a SaaS landing page and launch plan",
            "stack_id": "idea_to_revenue",
        },
    )

    assert plan is not None
    assert [phase.phase_name for phase in plan.phases][:3] == ["diagnose", "design", "deploy"]
    diagnose_keys = set(plan.phases[0].step_keys)
    assert diagnose_keys
    assert any(key.startswith("r_") for key in diagnose_keys)


def test_build_temporal_run_plan_rejects_unknown_dependencies():
    from backend.control_plane.temporal.execution import (
        TemporalPlanNonRetryableError,
        build_temporal_run_plan,
    )

    async def _run():
        await build_temporal_run_plan(
            "run_bad_plan",
            {
                "temporal_step_specs": {
                    "design": {
                        "agent": "design",
                        "instruction": "Design the page",
                        "phase": "design",
                        "depends_on": ["missing_step"],
                    }
                }
            },
        )

    with pytest.raises(TemporalPlanNonRetryableError, match="unknown step"):
        asyncio.run(_run())


def test_build_temporal_run_plan_rejects_phase_cycles():
    from backend.control_plane.temporal.execution import (
        TemporalPlanNonRetryableError,
        build_temporal_run_plan,
    )

    async def _run():
        await build_temporal_run_plan(
            "run_cycle_plan",
            {
                "temporal_step_specs": {
                    "design_a": {
                        "agent": "design",
                        "instruction": "Design A",
                        "phase": "design",
                        "depends_on": ["design_b"],
                    },
                    "design_b": {
                        "agent": "design",
                        "instruction": "Design B",
                        "phase": "design",
                        "depends_on": ["design_a"],
                    },
                }
            },
        )

    with pytest.raises(TemporalPlanNonRetryableError, match="cycle detected"):
        asyncio.run(_run())


@pytest.mark.asyncio
async def test_build_temporal_run_plan_respects_selected_agents():
    from backend.control_plane.temporal.execution import build_temporal_run_plan

    class _FakeOrchestrator:
        specialists = {"web": object(), "design": object()}

    plan = await build_temporal_run_plan(
        "run_selected_agents",
        {
            "goal": "Polish the launch site",
            "constraints": {"agents": ["web", "design"]},
        },
        get_orchestrator_fn=lambda: _FakeOrchestrator(),
    )

    task_agents = {task["agent"] for task in plan["tasks"]} if "tasks" in plan else {
        str(spec.get("agent") or "")
        for spec in dict(plan.get("step_specs") or {}).values()
    }
    assert task_agents == {"web", "design"}
    assert [phase["phase_name"] for phase in plan["phases"]] == ["deploy"]
    assert set(plan["phases"][0]["step_keys"]) == {"temporal_web", "temporal_design"}


@pytest.mark.asyncio
async def test_workflow_signal_handlers_and_queries_track_state():
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    from backend.control_plane.temporal.workflows import AstraRunWorkflow

    wf = AstraRunWorkflow()
    wf._state.run_id = "run_query_1"
    wf._state.workflow_status = "running"
    wf._state.active_step = "legacy_orchestrator"
    wf._state.waiting_approval = {"approval_id": "appr_1"}

    assert wf.workflow_status() == "running"
    assert wf.active_step() == "legacy_orchestrator"
    assert wf.waiting_approval() == {"approval_id": "appr_1"}
    assert wf.cancellation_state() == {"requested": False}

    await wf.approval_decision(
        ApprovalDecisionInput(
            approval_id="appr_1",
            action_digest="digest_1",
            decision="approved",
            decided_by="owner_1",
        )
    )
    await wf.retry_step(RetryStepInput(step_key="research", requested_by="owner_1", note="rerun"))
    await wf.cancel()

    assert wf.waiting_approval() is None
    assert wf._approval_decision["approval_id"] == "appr_1"
    assert wf._retry_request["step_key"] == "research"
    assert wf.cancellation_state() == {"requested": True}


@pytest.mark.asyncio
async def test_workflow_run_uses_single_attempt_retry_policy(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod

    captured_start_activity = {}
    captured_execute_activity = []

    class _Handle:
        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            async def _result():
                return {"session_id": "run_retry_policy"}

            return _result().__await__()

    async def _fake_execute_activity(*args, **kwargs):
        captured_execute_activity.append(kwargs.get("retry_policy"))
        return True

    def _fake_start_activity(*args, **kwargs):
        captured_start_activity["retry_policy"] = kwargs.get("retry_policy")
        return _Handle()

    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    monkeypatch.setattr(workflows_mod.workflow, "start_activity", _fake_start_activity)

    wf = workflows_mod.AstraRunWorkflow()
    result = await wf.run(workflows_mod.RunInput(run_id="run_retry_policy"))

    assert result.status == "succeeded"
    assert captured_start_activity["retry_policy"].maximum_attempts == 1
    assert all(policy.maximum_attempts == 1 for policy in captured_execute_activity if policy is not None)


@pytest.mark.asyncio
async def test_workflow_run_cancels_pending_activity_without_restarting(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod

    started = {"count": 0}
    observed = []

    class _Handle:
        def __init__(self):
            self._done = False
            self.cancelled = False

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True
            self._done = True

        def __await__(self):
            async def _result():
                raise asyncio.CancelledError()

            return _result().__await__()

    handle = _Handle()

    async def _fake_execute_activity(activity_fn, *args, **kwargs):
        observed.append((activity_fn, args, kwargs))
        return True

    def _fake_start_activity(*args, **kwargs):
        started["count"] += 1
        return handle

    real_sleep = asyncio.sleep
    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    monkeypatch.setattr(workflows_mod.workflow, "start_activity", _fake_start_activity)
    monkeypatch.setattr(workflows_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = workflows_mod.AstraRunWorkflow()

    async def _drive_cancel():
        task = asyncio.create_task(wf.run(workflows_mod.RunInput(run_id="run_cancel")))
        await asyncio.sleep(0)
        await wf.cancel()
        return await task

    result = await _drive_cancel()

    assert result.status == "cancelled"
    assert handle.cancelled is True
    assert started["count"] == 1


@pytest.mark.asyncio
async def test_workflow_run_observes_approval_and_retry_signals_while_pending(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod

    observations = []

    class _Handle:
        def __init__(self):
            self.calls = 0

        def done(self):
            self.calls += 1
            return self.calls > 2

        def cancel(self):
            return None

        def __await__(self):
            async def _result():
                return {"session_id": "run_pending"}

            return _result().__await__()

    async def _fake_execute_activity(activity_fn, *args, **kwargs):
        if getattr(activity_fn, "__qualname__", "").startswith("ObserveRunActivity"):
            activity_args = kwargs.get("args") or (args[0] if args else [])
            observations.append(activity_args[1] if len(activity_args) > 1 else {})
        return True

    real_sleep = asyncio.sleep
    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    monkeypatch.setattr(workflows_mod.workflow, "start_activity", lambda *args, **kwargs: _Handle())
    monkeypatch.setattr(workflows_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = workflows_mod.AstraRunWorkflow()

    async def _drive_signals():
        task = asyncio.create_task(wf.run(workflows_mod.RunInput(run_id="run_pending")))
        await asyncio.sleep(0)
        await wf.approval_decision(ApprovalDecisionInput(approval_id="approval_1", action_digest="digest_1", decision="approved"))
        await wf.retry_step(RetryStepInput(step_key="research", requested_by="owner_1"))
        return await task

    result = await _drive_signals()

    assert result.status == "succeeded"
    flattened = [payload.get("metadata", {}) for payload in observations if isinstance(payload, dict)]
    assert any("approval_decision" in meta for meta in flattened)
    assert any("retry_request" in meta for meta in flattened)


@pytest.mark.asyncio
async def test_workflow_run_uses_multi_phase_child_when_plan_is_available(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod

    execute_calls = []
    child_signal_calls = []

    class _ChildHandle:
        def __init__(self):
            self.calls = 0

        def done(self):
            self.calls += 1
            return self.calls > 2

        def cancel(self):
            return None

        async def signal(self, name, arg=None):
            child_signal_calls.append((name, arg))

        async def query(self, name):
            if name == "active_phase":
                return "design"
            if name == "waiting_gate":
                return "design" if self.calls <= 2 else None
            return None

        def __await__(self):
            async def _result():
                return workflows_mod.MultiPhaseRunResult(
                    run_id="run_multi_path",
                    status="approved",
                    completed_phases=[{"phase_name": "design", "decision": "approved"}],
                    decision="approved",
                )

            return _result().__await__()

    async def _fake_execute_activity(activity_fn, *args, **kwargs):
        qualname = getattr(activity_fn, "__qualname__", repr(activity_fn))
        execute_calls.append(qualname)
        if "LoadRunPlanActivity" in qualname or "load_run_plan" in qualname:
            return {
                "run_id": "run_multi_path",
                "phases": [
                    {
                        "run_id": "run_multi_path",
                        "phase_name": "design",
                        "next_phase": "deploy",
                        "step_keys": ["design_lane"],
                        "timeout_seconds": 30,
                    },
                ],
            }
        return True

    real_sleep = asyncio.sleep
    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    async def _fake_start_child_workflow(*args, **kwargs):
        return _ChildHandle()

    monkeypatch.setattr(workflows_mod.workflow, "start_child_workflow", _fake_start_child_workflow)
    monkeypatch.setattr(workflows_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = workflows_mod.AstraRunWorkflow()

    async def _drive():
        task = asyncio.create_task(wf.run(workflows_mod.RunInput(run_id="run_multi_path")))
        await asyncio.sleep(0)
        await wf.approval_decision(
            workflows_mod.ApprovalDecisionInput(
                approval_id="approval_design",
                action_digest="digest_design",
                decision="approved",
            )
        )
        return await task

    result = await _drive()

    assert result.status == "succeeded"
    assert any("LoadRunPlanActivity" in call for call in execute_calls)
    assert any(signal_name == "approval_decision" for signal_name, _ in child_signal_calls)


@pytest.mark.asyncio
async def test_phase_workflow_respects_intra_phase_dependencies(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    from backend.control_plane.temporal.phase_workflow import PhaseRunWorkflow

    wf = PhaseRunWorkflow()
    started = []

    class _Handle:
        def __init__(self, step_key):
            self.step_key = step_key

        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_dep_phase",
                    "step_key": self.step_key,
                    "step_id": f"step_{self.step_key}",
                    "agent": self.step_key,
                    "status": "succeeded",
                    "attempt_number": 1,
                    "result": {"summary": "ok"},
                    "verification": {"status": "passed", "summary": "ok"},
                }

            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

    async def _fake_start_child_workflow(_workflow, lane_input, **_kwargs):
        step_key = lane_input.step_key if hasattr(lane_input, "step_key") else lane_input["step_key"]
        started.append(step_key)
        return _Handle(step_key)

    async def _fake_start_gate(*_args, **_kwargs):
        class _GateHandle:
            def done(self):
                return True

            def cancel(self):
                return None

            def __await__(self):
                async def _result():
                    return {
                        "run_id": "run_dep_phase",
                        "gate_key": "phase_gate_deploy",
                        "approval_id": "approval_dep",
                        "action_digest": "digest_dep",
                        "decision": "approved",
                    }

                return _result().__await__()

        return _GateHandle()

    async def _fake_start_child_router(workflow_run, *args, **kwargs):
        name = getattr(workflow_run, "__qualname__", "")
        if "LaneAttemptWorkflow" in name:
            return await _fake_start_child_workflow(workflow_run, *args, **kwargs)
        return await _fake_start_gate(workflow_run, *args, **kwargs)

    import backend.control_plane.temporal.phase_workflow as phase_mod

    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _fake_start_child_router)
    result = await wf.run(
        phase_mod.PhaseRunInput(
            run_id="run_dep_phase",
            phase_name="deploy",
            next_phase="govern",
            step_keys=["t_web", "t_technical"],
            step_dependencies={"t_web": [], "t_technical": ["t_web"]},
        )
    )
    assert started == ["t_web", "t_technical"]
    assert result.status == "approved"


@pytest.mark.asyncio
async def test_multi_phase_workflow_continues_as_new_after_threshold(monkeypatch):
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.multi_phase_workflow as multi_mod
    from backend.control_plane.temporal.contracts import PhaseRunInput

    continued = {}

    class _Handle:
        def __init__(self, phase_name):
            self.phase_name = phase_name

        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_can",
                    "phase_name": self.phase_name,
                    "next_phase": "next",
                    "status": "approved",
                    "decision": "approved",
                    "lane_results": [],
                    "approval": {"approval_id": f"approval_{self.phase_name}"},
                }

            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

        async def query(self, _name):
            return None

    async def _fake_start_child_workflow(_workflow, phase_input, **_kwargs):
        return _Handle(phase_input.phase_name if hasattr(phase_input, "phase_name") else phase_input["phase_name"])

    def _fake_continue_as_new(next_input):
        continued["input"] = next_input
        raise RuntimeError("continue-as-new-triggered")

    monkeypatch.setattr(multi_mod.workflow, "start_child_workflow", _fake_start_child_workflow)
    monkeypatch.setattr(multi_mod.workflow, "continue_as_new", _fake_continue_as_new)
    monkeypatch.setattr(multi_mod, "_CONTINUE_AS_NEW_PHASE_THRESHOLD", 1)

    wf = multi_mod.MultiPhaseRunWorkflow()
    with pytest.raises(RuntimeError, match="continue-as-new-triggered"):
        await wf.run(
                multi_mod.MultiPhaseRunInput(
                    run_id="run_can",
                    phases=[
                        PhaseRunInput(run_id="run_can", phase_name="design", next_phase="deploy", step_keys=["a"]),
                        PhaseRunInput(run_id="run_can", phase_name="deploy", next_phase="govern", step_keys=["b"]),
                    ],
                )
            )

    assert continued["input"].run_id == "run_can"
    assert [phase.phase_name for phase in continued["input"].phases] == ["deploy"]
    assert [phase["phase_name"] for phase in continued["input"].completed_phases_seed] == ["design"]

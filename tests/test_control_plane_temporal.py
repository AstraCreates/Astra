import asyncio
import sys
import types

import pytest

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in CI environments without temporalio
    temporalio = None

if temporalio is not None:
    from backend.control_plane.temporal.codec import PassthroughPayloadCodec
    from backend.control_plane.temporal.testing import local_workflow_environment


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
    assert calls["workflow_input"].founder_id == "founder-1"
    assert calls["workflow_input"].company_id == "company-1"
    assert calls["workflow_input"].workspace_id == "workspace-1"
    assert calls["workflow_input"].chapter_id == "chapter-1"
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
            founder_id="founder-2",
            company_id="company-2",
            workspace_id="workspace-2",
            chapter_id="chapter-2",
        ),
        heartbeat=heartbeats.append,
        heartbeat_interval_seconds=0.01,
        get_orchestrator_fn=lambda: _FakeOrchestrator(),
        get_session_meta_fn=lambda _run_id: {
            "goal": "fallback goal",
            "founder_id": "founder-2",
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
            RunInput(run_id="sess_temporal_3", founder_id="founder-3"),
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

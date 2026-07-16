"""Regression tests for the Retry-a-step fix.

Real production gap (confirmed via audit): dispatch.retry_step() correctly
signals the top-level AstraRunWorkflow, but the signal was never forwarded
down through MultiPhaseRunWorkflow -> PhaseRunWorkflow (the workflow that
actually dispatches per-step LaneAttemptWorkflow children), and
PhaseRunWorkflow had no retry_step signal handler at all -- so the real,
running Temporal workflow never re-ran anything. Meanwhile routes.py's
retry endpoint unconditionally called the legacy rerun_agent(), which spawns
an untracked asyncio task calling the specialist directly in the API
process -- for a Temporal-routed run, a disconnected duplicate execution
that was never part of the real run.

These tests instantiate the workflow classes directly and monkeypatch
`workflow.start_child_workflow` with fake handles, mirroring the pattern in
tests/test_phase_cancellation_await.py, to avoid a real Temporal test server.
"""
from __future__ import annotations

import asyncio

import pytest

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in CI environments without temporalio
    temporalio = None


@pytest.mark.asyncio
async def test_phase_workflow_retries_step_at_gate_and_replaces_stale_result(monkeypatch):
    """The realistic case: a founder sees a bad/failed step result at the
    phase-gate review point and clicks retry. The in-flight gate must be
    cancelled, the named step re-run as a fresh LaneAttemptWorkflow, its
    result replace the old one, and a NEW gate dispatched with the updated
    artifacts -- not silently ignored."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.phase_workflow as phase_mod

    gate_dispatches = []
    lane_dispatches = []

    class _LaneHandle:
        def __init__(self, step_key: str, status: str):
            self.step_key = step_key
            self.status = status

        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            pass

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_retry",
                    "step_key": self.step_key,
                    "step_id": f"step_{self.step_key}",
                    "agent": self.step_key,
                    "status": self.status,
                    "attempt_number": 1,
                    "verification": {"status": self.status, "summary": f"{self.step_key}: {self.status}"},
                }
            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

    class _GateHandle:
        def __init__(self, gate_index: int):
            self.gate_index = gate_index
            self._retry_delivered = False
            self._done = False

        def done(self) -> bool:
            return self._done

        def cancel(self) -> None:
            self._done = True

        def __await__(self):
            async def _result():
                return {"decision": "approved", "gate_key": f"phase_gate_build_{self.gate_index}"}
            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

        async def query(self, _name):
            return None

    async def _fake_start_child_workflow(workflow_fn, wf_input, **kwargs):
        is_gate_dispatch = "phase-gate" in kwargs.get("id", "")
        if not is_gate_dispatch:
            lane_dispatches.append(wf_input.step_key)
            # First dispatch of lane_a returns "failed"; the retry dispatch returns "succeeded".
            status = "failed" if lane_dispatches.count(wf_input.step_key) == 1 and wf_input.step_key == "lane_a" else "succeeded"
            return _LaneHandle(wf_input.step_key, status)
        gate_dispatches.append(kwargs.get("id"))
        handle = _GateHandle(len(gate_dispatches))
        return handle

    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _fake_start_child_workflow)

    real_sleep = asyncio.sleep
    sleep_calls = {"n": 0}

    async def _fake_sleep(_seconds):
        sleep_calls["n"] += 1
        await real_sleep(0)

    monkeypatch.setattr(phase_mod.asyncio, "sleep", _fake_sleep)

    wf = phase_mod.PhaseRunWorkflow()

    # Make the first gate handle never resolve on its own -- the workflow must
    # only move past it via our retry signal, not because it happened to complete.
    original_start = _fake_start_child_workflow
    gate_handles: list[_GateHandle] = []

    async def _tracking_start(workflow_fn, wf_input, **kwargs):
        result = await original_start(workflow_fn, wf_input, **kwargs)
        if isinstance(result, _GateHandle):
            gate_handles.append(result)
            if len(gate_handles) == 1:
                result._done = False  # first gate: stays open until we cancel it via retry
            else:
                result._done = True  # second (post-retry) gate: resolves immediately as approved
        return result

    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _tracking_start)

    async def _drive():
        task = asyncio.create_task(
            wf.run(
                phase_mod.PhaseRunInput(
                    run_id="run_retry",
                    phase_name="build",
                    next_phase="deploy",
                    step_keys=["lane_a"],
                    step_dependencies={},
                )
            )
        )
        await real_sleep(0)
        await real_sleep(0)
        # Deliver the retry signal for lane_a while the first gate is open.
        await wf.retry_step(phase_mod.RetryStepInput(step_key="lane_a", requested_by="founder_1", note="try again"))
        return await task

    result = await _drive()

    assert result.status == "approved"
    assert lane_dispatches.count("lane_a") == 2  # original dispatch + one retry dispatch
    assert len(gate_dispatches) == 2  # original gate + a fresh gate after the retry
    assert len(result.lane_results) == 1
    assert result.lane_results[0]["status"] == "succeeded"  # stale "failed" result was replaced


@pytest.mark.asyncio
async def test_phase_workflow_ignores_retry_for_a_step_key_not_in_this_phase(monkeypatch):
    """A retry request naming a step that never ran in this phase must not
    be actioned (e.g. stale signal, wrong phase, typo) -- the gate proceeds
    normally."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.phase_workflow as phase_mod

    class _LaneHandle:
        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            pass

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_x", "step_key": "lane_a", "step_id": "step_lane_a",
                    "agent": "lane_a", "status": "succeeded", "attempt_number": 1,
                    "verification": {"status": "passed", "summary": "ok"},
                }
            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

    class _GateHandle:
        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            pass

        def __await__(self):
            async def _result():
                return {"decision": "approved"}
            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

        async def query(self, _name):
            return None

    gate_dispatch_count = {"n": 0}

    async def _fake_start_child_workflow(workflow_fn, wf_input, **kwargs):
        if "phase-gate" not in kwargs.get("id", ""):
            return _LaneHandle()
        gate_dispatch_count["n"] += 1
        return _GateHandle()

    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _fake_start_child_workflow)

    wf = phase_mod.PhaseRunWorkflow()
    wf._retry_request = {"step_key": "not_a_real_step", "requested_by": None, "note": None}

    result = await wf.run(
        phase_mod.PhaseRunInput(
            run_id="run_x", phase_name="build", next_phase="deploy",
            step_keys=["lane_a"], step_dependencies={},
        )
    )

    assert result.status == "approved"
    assert gate_dispatch_count["n"] == 1  # never redispatched -- retry request was for an unknown step


@pytest.mark.asyncio
async def test_multi_phase_workflow_forwards_retry_signal_to_active_phase_child(monkeypatch):
    """MultiPhaseRunWorkflow must forward a pending retry request down to the
    currently-active PhaseRunWorkflow child via signal -- mirroring exactly
    how approval_decision is already forwarded. Before this fix, the signal
    was accepted at this level (stored in _pending_retry) but never sent
    anywhere, so the real running phase workflow never heard about it."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.multi_phase_workflow as multi_mod
    from backend.control_plane.temporal.contracts import PhaseRunInput

    signals_received = []

    class _Handle:
        def __init__(self):
            self._done = False

        def done(self) -> bool:
            return self._done

        def cancel(self) -> None:
            self._done = True

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_forward", "phase_name": "design", "next_phase": "deploy",
                    "status": "approved", "decision": "approved", "lane_results": [],
                }
            return _result().__await__()

        async def signal(self, name, payload=None):
            signals_received.append((name, payload))
            if name == "retry_step":
                self._done = True  # let the parent's wait loop exit after forwarding

        async def query(self, _name):
            return None

    async def _fake_start_child_workflow(*_args, **_kwargs):
        return _Handle()

    real_sleep = asyncio.sleep
    monkeypatch.setattr(multi_mod.workflow, "start_child_workflow", _fake_start_child_workflow)
    monkeypatch.setattr(multi_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = multi_mod.MultiPhaseRunWorkflow()

    async def _drive():
        task = asyncio.create_task(
            wf.run(
                multi_mod.MultiPhaseRunInput(
                    run_id="run_forward",
                    phases=[PhaseRunInput(run_id="run_forward", phase_name="design", next_phase="deploy", step_keys=["a"])],
                )
            )
        )
        await real_sleep(0)
        await wf.retry_step(multi_mod.RetryStepInput(step_key="a", requested_by="founder_1", note=None))
        return await task

    result = await _drive()

    assert result.status == "approved"
    retry_signals = [payload for name, payload in signals_received if name == "retry_step"]
    assert len(retry_signals) == 1
    assert retry_signals[0].step_key == "a"
    assert retry_signals[0].requested_by == "founder_1"


@pytest.mark.asyncio
async def test_astra_run_workflow_forwards_retry_signal_to_multi_phase_child(monkeypatch):
    """Top of the chain: AstraRunWorkflow's retry_step signal handler used to
    only stash the request into observed metadata (dispatch.retry_step()
    signals THIS workflow, but nothing then relayed it onward) -- the real
    running MultiPhaseRunWorkflow child never heard about it, so nothing in
    the actual live run ever retried anything."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.workflows as workflows_mod
    from backend.control_plane.temporal.contracts import RetryStepInput as _RetryStepInput

    signals_received = []

    class _ChildHandle:
        def __init__(self):
            self.calls = 0

        def done(self):
            self.calls += 1
            return self.calls > 2

        def cancel(self):
            return None

        async def signal(self, name, arg=None):
            signals_received.append((name, arg))

        async def query(self, name):
            if name == "active_phase":
                return "design"
            if name == "waiting_gate":
                return None
            return None

        def __await__(self):
            async def _result():
                return workflows_mod.MultiPhaseRunResult(
                    run_id="run_retry_top",
                    status="approved",
                    completed_phases=[{"phase_name": "design", "decision": "approved"}],
                    decision="approved",
                )
            return _result().__await__()

    async def _fake_execute_activity(activity_fn, *args, **kwargs):
        qualname = getattr(activity_fn, "__qualname__", repr(activity_fn))
        if "LoadRunPlanActivity" in qualname or "load_run_plan" in qualname:
            return {
                "run_id": "run_retry_top",
                "phases": [{
                    "run_id": "run_retry_top", "phase_name": "design", "next_phase": "deploy",
                    "step_keys": ["design_lane"], "timeout_seconds": 30,
                }],
            }
        return True

    real_sleep = asyncio.sleep
    async def _fake_start_child_workflow(*_args, **_kwargs):
        return _ChildHandle()

    monkeypatch.setattr(workflows_mod.workflow, "execute_activity", _fake_execute_activity)
    monkeypatch.setattr(workflows_mod.workflow, "start_child_workflow", _fake_start_child_workflow)
    monkeypatch.setattr(workflows_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = workflows_mod.AstraRunWorkflow()

    async def _drive():
        task = asyncio.create_task(wf.run(workflows_mod.RunInput(run_id="run_retry_top")))
        await real_sleep(0)
        await wf.retry_step(_RetryStepInput(step_key="design_lane", requested_by="founder_1"))
        return await task

    result = await _drive()

    assert result.status == "succeeded"
    retry_signals = [payload for name, payload in signals_received if name == "retry_step"]
    assert len(retry_signals) == 1
    assert retry_signals[0].step_key == "design_lane"

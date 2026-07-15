"""Regression tests for cancellation-await gaps in the Temporal phase
workflows.

Bug: MultiPhaseRunWorkflow and PhaseRunWorkflow called `handle.cancel()` on
child workflows and then returned immediately, without awaiting the handle
to confirm the cancellation actually completed. For PhaseRunWorkflow's
multi-lane case specifically, only the lane the loop happened to be awaiting
at cancellation time was properly waited on -- remaining concurrent lane
handles got a cancel signal fired but nobody confirmed they finished. This
meant a founder-cancelled run could leave lane-attempt workflows (and the
real agent activities executing inside them) running and burning LLM tokens
after the parent workflow had already reported itself "cancelled".

These tests instantiate the workflow classes directly and monkeypatch
`workflow.start_child_workflow` with fake handles that record whether
`cancel()` was called AND whether the handle was subsequently awaited --
mirroring the pattern used in tests/test_control_plane_temporal.py. This
avoids spinning up a real Temporal test server (which is slow / prone to
hanging in this environment) while still exercising the actual workflow
`run()` coroutines.
"""
from __future__ import annotations

import asyncio

import pytest

try:
    import temporalio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in CI environments without temporalio
    temporalio = None


@pytest.mark.asyncio
async def test_multi_phase_workflow_awaits_child_handle_after_cancel(monkeypatch):
    """MultiPhaseRunWorkflow must await the PhaseRunWorkflow child handle
    (not just call .cancel() on it) before returning a cancelled result."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.multi_phase_workflow as multi_mod
    from backend.control_plane.temporal.contracts import PhaseRunInput

    handle_state = {"cancel_called": False, "awaited": False}

    class _Handle:
        def done(self) -> bool:
            # Never completes on its own -- the only way the parent's loop
            # exits is via the cancellation path under test.
            return False

        def cancel(self) -> None:
            handle_state["cancel_called"] = True

        def __await__(self):
            async def _result():
                handle_state["awaited"] = True
                assert handle_state["cancel_called"], "handle awaited before cancel() was called"
                raise asyncio.CancelledError()

            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

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
                    run_id="run_cancel_multi",
                    phases=[
                        PhaseRunInput(
                            run_id="run_cancel_multi",
                            phase_name="design",
                            next_phase="deploy",
                            step_keys=["a"],
                        ),
                    ],
                )
            )
        )
        # Let the workflow reach its wait loop, then deliver the cancel signal.
        await real_sleep(0)
        await wf.cancel()
        return await task

    result = await _drive()

    assert result.status == "cancelled"
    assert handle_state["cancel_called"] is True
    assert handle_state["awaited"] is True


@pytest.mark.asyncio
async def test_phase_workflow_cancels_and_awaits_all_concurrent_lane_handles(monkeypatch):
    """When PhaseRunWorkflow detects cancellation mid-loop with multiple
    concurrent lane-attempt handles outstanding, ALL of them must be
    cancelled AND awaited -- not just the one the loop happened to reach,
    with the rest abandoned via `handle.cancel(); continue`."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.phase_workflow as phase_mod

    lane_state: dict[str, dict[str, bool]] = {}

    class _LaneHandle:
        def __init__(self, step_key: str):
            self.step_key = step_key
            lane_state[step_key] = {"cancel_called": False, "awaited": False}

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            lane_state[self.step_key]["cancel_called"] = True

        def __await__(self):
            async def _result():
                lane_state[self.step_key]["awaited"] = True
                assert lane_state[self.step_key]["cancel_called"], (
                    f"{self.step_key} handle awaited before cancel() was called"
                )
                raise asyncio.CancelledError()

            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

    wf = phase_mod.PhaseRunWorkflow()

    call_count = {"n": 0}
    step_keys = ["lane_a", "lane_b", "lane_c"]

    async def _fake_start_child_workflow(_workflow_fn, lane_input, **_kwargs):
        call_count["n"] += 1
        handle = _LaneHandle(lane_input.step_key)
        # Simulate the cancel signal arriving after all three lane child
        # workflows have been started but before any of them is awaited --
        # i.e. the exact "multiple concurrent children" scenario from the
        # bug report.
        if call_count["n"] == len(step_keys):
            wf._cancelled = True
        return handle

    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _fake_start_child_workflow)

    result = await wf.run(
        phase_mod.PhaseRunInput(
            run_id="run_cancel_lanes",
            phase_name="build",
            next_phase="deploy",
            step_keys=step_keys,
            step_dependencies={},
        )
    )

    assert result.status == "cancelled"
    assert set(lane_state.keys()) == set(step_keys)
    for step_key, flags in lane_state.items():
        assert flags["cancel_called"] is True, f"{step_key} was never cancelled"
        assert flags["awaited"] is True, f"{step_key} was cancelled but never awaited (abandoned)"


@pytest.mark.asyncio
async def test_phase_workflow_awaits_gate_handle_after_cancel(monkeypatch):
    """PhaseRunWorkflow must await the PhaseGateWorkflow child handle after
    cancelling it, not return immediately after firing the cancel signal."""
    if temporalio is None:
        pytest.skip("temporalio not installed in this environment")
    import backend.control_plane.temporal.phase_workflow as phase_mod

    gate_state = {"cancel_called": False, "awaited": False}

    class _LaneHandle:
        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            pass

        def __await__(self):
            async def _result():
                return {
                    "run_id": "run_cancel_gate",
                    "step_key": "lane_a",
                    "step_id": "step_lane_a",
                    "agent": "lane_a",
                    "status": "succeeded",
                    "attempt_number": 1,
                    "verification": {"status": "passed", "summary": "ok"},
                }

            return _result().__await__()

        async def signal(self, *_args, **_kwargs):
            return None

    class _GateHandle:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            gate_state["cancel_called"] = True

        def __await__(self):
            async def _result():
                gate_state["awaited"] = True
                assert gate_state["cancel_called"], "gate handle awaited before cancel() was called"
                raise asyncio.CancelledError()

            return _result().__await__()

        async def query(self, _name):
            return None

        async def signal(self, *_args, **_kwargs):
            return None

    async def _fake_start_child_router(workflow_fn, *args, **kwargs):
        name = getattr(workflow_fn, "__qualname__", "")
        if "LaneAttemptWorkflow" in name:
            return _LaneHandle()
        return _GateHandle()

    real_sleep = asyncio.sleep
    monkeypatch.setattr(phase_mod.workflow, "start_child_workflow", _fake_start_child_router)
    monkeypatch.setattr(phase_mod.asyncio, "sleep", lambda _seconds: real_sleep(0))

    wf = phase_mod.PhaseRunWorkflow()

    async def _drive():
        task = asyncio.create_task(
            wf.run(
                phase_mod.PhaseRunInput(
                    run_id="run_cancel_gate",
                    phase_name="build",
                    next_phase="deploy",
                    step_keys=["lane_a"],
                    step_dependencies={},
                )
            )
        )
        # Let the lane finish and the gate wait-loop start, then cancel.
        await real_sleep(0)
        await wf.cancel()
        return await task

    result = await _drive()

    assert result.status == "cancelled"
    assert gate_state["cancel_called"] is True
    assert gate_state["awaited"] is True

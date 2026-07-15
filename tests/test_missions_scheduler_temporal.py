import asyncio

from backend.missions import scheduler


async def test_start_missions_scheduler_prefers_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_ensure(interval):
        calls.append(interval)
        scheduler._status.update({
            "running": True,
            "interval_seconds": interval,
            "last_error": "",
            "mode": "temporal",
            "schedule_id": scheduler._TEMPORAL_SCHEDULE_ID,
        })
        return scheduler.get_missions_scheduler_status()

    monkeypatch.setattr(scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(scheduler, "_ensure_temporal_schedule", _fake_ensure)

    status = await scheduler.start_missions_scheduler(interval_seconds=600)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-missions-safety-net"
    assert calls == [600]


async def test_start_missions_scheduler_falls_back_when_temporal_raises(monkeypatch):
    """Regression test: a failure INSIDE _ensure_temporal_schedule (e.g. Temporal briefly
    unreachable) must be caught by start_missions_scheduler and must NOT leave the status
    falsely claiming mode="temporal"/running=True. Previously the coroutine was fired via
    asyncio.create_task() without being awaited, so this exception would only ever surface
    as an unhandled task exception — the status update happened unconditionally beforehand
    and was never rolled back, and the legacy fallback path below was never reached because
    the function had already returned.
    """
    scheduler._status.update({
        "running": False,
        "interval_seconds": 3600,
        "last_tick_at": None,
        "last_missions_run": 0,
        "last_error": "",
        "mode": "legacy",
        "schedule_id": "",
    })
    scheduler._task = None
    scheduler._stop_event = None

    async def _fake_ensure(interval):
        raise RuntimeError("temporal unreachable")

    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(scheduler, "_ensure_temporal_schedule", _fake_ensure)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = await scheduler.start_missions_scheduler(interval_seconds=600)
    sched = status["scheduler"]

    # The core regression: no false "temporal" positive when nothing was actually scheduled.
    assert sched["mode"] == "legacy"
    assert sched["schedule_id"] == ""
    assert sched["last_error"] == "temporal unreachable"
    # It genuinely fell through to the legacy in-process loop (not a silent no-op).
    assert spawned["coro"] is not None
    assert sched["running"] is True
    spawned["coro"].close()
    # Cleanup: the fake create_task left a stub `_task` (no .cancel()) in module-global
    # state, which would break later tests (e.g. stop_missions_scheduler) if left in place.
    scheduler._task = None
    scheduler._stop_event = None


async def test_stop_missions_scheduler_deletes_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_delete():
        calls.append("deleted")

    scheduler._status.update({
        "running": True,
        "mode": "temporal",
        "schedule_id": "astra-missions-safety-net",
    })
    monkeypatch.setattr(scheduler, "_delete_temporal_schedule", _fake_delete)

    status = await scheduler.stop_missions_scheduler()

    assert calls == ["deleted"]
    assert status["scheduler"]["running"] is False

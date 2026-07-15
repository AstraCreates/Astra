import asyncio

from backend.custom_agents import scheduler as custom_scheduler
from backend.tools import company_brain_scheduler


def test_start_company_brain_scheduler_prefers_temporal_schedule(monkeypatch):
    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(company_brain_scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = company_brain_scheduler.start_company_brain_scheduler(interval_seconds=30)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-company-brain-sync"
    spawned["coro"].close()


async def test_stop_company_brain_scheduler_deletes_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_delete():
        calls.append("deleted")

    company_brain_scheduler._status.update({
        "running": True,
        "mode": "temporal",
        "schedule_id": "astra-company-brain-sync",
    })
    monkeypatch.setattr(company_brain_scheduler, "_delete_temporal_schedule", _fake_delete)

    status = await company_brain_scheduler.stop_company_brain_scheduler()

    assert calls == ["deleted"]
    assert status["scheduler"]["running"] is False


async def test_start_custom_agents_scheduler_prefers_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_ensure(interval):
        calls.append(interval)
        custom_scheduler._status.update({
            "running": True,
            "interval_seconds": interval,
            "last_error": "",
            "mode": "temporal",
            "schedule_id": custom_scheduler._TEMPORAL_SCHEDULE_ID,
        })
        return custom_scheduler.get_custom_agents_scheduler_status()

    monkeypatch.setattr(custom_scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(custom_scheduler, "_ensure_temporal_schedule", _fake_ensure)

    status = await custom_scheduler.start_custom_agents_scheduler(interval_seconds=300)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-custom-agents-recurring"
    assert calls == [300]


async def test_start_custom_agents_scheduler_falls_back_when_temporal_raises(monkeypatch):
    """Regression test: a failure inside _ensure_temporal_schedule must be caught (it is
    now awaited, not fire-and-forgotten via asyncio.create_task) and must not leave the
    status falsely reporting mode="temporal"/running=True."""
    custom_scheduler._status.update({
        "running": False,
        "interval_seconds": 900,
        "last_tick_at": None,
        "last_runs_launched": 0,
        "last_error": "",
        "mode": "legacy",
        "schedule_id": "",
    })
    custom_scheduler._task = None
    custom_scheduler._stop_event = None

    async def _fake_ensure(interval):
        raise RuntimeError("temporal unreachable")

    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(custom_scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(custom_scheduler, "_ensure_temporal_schedule", _fake_ensure)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = await custom_scheduler.start_custom_agents_scheduler(interval_seconds=300)
    sched = status["scheduler"]

    assert sched["mode"] == "legacy"
    assert sched["schedule_id"] == ""
    assert sched["last_error"] == "temporal unreachable"
    assert spawned["coro"] is not None
    assert sched["running"] is True
    spawned["coro"].close()
    # Cleanup: the fake create_task left a stub `_task` (no .cancel()) in module-global
    # state, which would break later tests (e.g. stop_custom_agents_scheduler) if left in place.
    custom_scheduler._task = None
    custom_scheduler._stop_event = None


async def test_stop_custom_agents_scheduler_deletes_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_delete():
        calls.append("deleted")

    custom_scheduler._status.update({
        "running": True,
        "mode": "temporal",
        "schedule_id": "astra-custom-agents-recurring",
    })
    monkeypatch.setattr(custom_scheduler, "_delete_temporal_schedule", _fake_delete)

    status = await custom_scheduler.stop_custom_agents_scheduler()

    assert calls == ["deleted"]
    assert status["scheduler"]["running"] is False

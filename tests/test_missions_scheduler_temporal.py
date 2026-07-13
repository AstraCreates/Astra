import asyncio

from backend.missions import scheduler


def test_start_missions_scheduler_prefers_temporal_schedule(monkeypatch):
    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = scheduler.start_missions_scheduler(interval_seconds=600)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-missions-safety-net"
    assert spawned["coro"] is not None
    spawned["coro"].close()


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

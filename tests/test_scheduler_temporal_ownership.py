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


def test_start_custom_agents_scheduler_prefers_temporal_schedule(monkeypatch):
    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(custom_scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = custom_scheduler.start_custom_agents_scheduler(interval_seconds=300)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-custom-agents-recurring"
    spawned["coro"].close()


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

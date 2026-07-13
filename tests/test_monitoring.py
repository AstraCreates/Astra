"""Monitoring ledger, health checks, and auto-heal behavior."""
import asyncio

import pytest

from backend.monitoring import store, checks, scheduler


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    class FakeRedis:
        def __init__(self):
            self.values = {}
        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True
        def get(self, key):
            return self.values.get(key)
        def delete(self, key):
            self.values.pop(key, None)
    redis = FakeRedis()
    monkeypatch.setattr("backend.core.events._redis", lambda: redis)
    return tmp_path


def test_store_roundtrip_latest_and_uptime(vault):
    store.add_monitoring_check("f", "c", artifact_key="landing_page", artifact_type="url", status="up")
    store.add_monitoring_check("f", "c", artifact_key="landing_page", artifact_type="url", status="down")
    latest = store.latest_status("f", "c")
    assert latest["landing_page"]["status"] == "down"
    # 1 up of 2 health checks == 50% uptime.
    assert store.uptime_percent("f", "c", "landing_page") == 50.0


def test_heals_today_counts_only_auto_heal(vault):
    store.add_monitoring_check("f", "c", artifact_key="a", check_type="health", status="up")
    store.add_monitoring_check("f", "c", artifact_key="a", check_type="auto_heal", status="attempted")
    store.add_monitoring_check("f", "c", artifact_key="a", check_type="auto_heal", status="attempted")
    assert store.heals_today("f", "c") == 2


async def test_check_artifact_dead_url_is_down(vault):
    rec = {"artifact_key": "landing_page", "agent": "web", "session_id": "s1",
           "receipt": {"evidence": {"executable": {"url": "http://nonexistent.invalid.test"}}}}
    res = await checks.check_artifact(rec, do_content=False)
    assert res["status"] == "down"
    assert res["kind"] == "url"


async def test_check_artifact_stale_content(vault):
    rec = {"artifact_key": "market_brief", "agent": "research", "session_id": "s1",
           "receipt": {"checked_at": "2026-01-01T00:00:00Z", "evidence": {}}}
    res = await checks.check_artifact(rec, do_content=True)
    assert res["status"] == "stale"
    assert res["kind"] == "content"


async def test_check_artifact_content_skipped_when_not_due(vault):
    rec = {"artifact_key": "market_brief", "agent": "research", "session_id": "s1",
           "receipt": {"checked_at": "2026-01-01T00:00:00Z", "evidence": {}}}
    assert await checks.check_artifact(rec, do_content=False) is None


def _down_check():
    return {"status": "down", "kind": "url",
            "metadata": {"url": "http://x.test", "http_status": 500, "error": ""}}


async def test_auto_heal_reruns_responsible_agent(vault, monkeypatch):
    calls = {}
    notified = []

    async def _fake_start_continue_run(*, instruction, founder_id, prior_session_id, agents, run_id, **_kwargs):
        calls.update(
            instruction=instruction,
            founder_id=founder_id,
            prior_session_id=prior_session_id,
            agents=agents,
            run_id=run_id,
        )
        return {"ok": True}

    monkeypatch.setattr("backend.core.session_store.has_active_run", lambda *a, **k: False)
    monkeypatch.setattr("backend.control_plane.start_run.start_continue_run", _fake_start_continue_run)
    monkeypatch.setattr("backend.core.session_ids.new_session_id", lambda: "sx")
    monkeypatch.setattr("backend.notifications.push.notify_founder",
                        lambda fid, title, body, url="/": notified.append((title, body)))

    record = {"artifact_key": "landing_page", "artifact_title": "Landing",
              "agent": "web", "session_id": "s_prior"}
    ok = await scheduler._auto_heal("f", "c", record, _down_check())
    assert ok is True
    await asyncio.sleep(0.05)  # let the background heal task run

    assert calls["agents"] == ["web"]
    assert calls["prior_session_id"] == "s_prior"
    assert notified and "landing" in notified[0][1].lower()
    # The attempt is recorded for the per-day cap.
    assert store.heals_today("f", "c") == 1


async def test_auto_heal_respects_cap(vault, monkeypatch):
    monkeypatch.setattr("backend.core.session_store.has_active_run", lambda *a, **k: False)
    monkeypatch.setenv("ASTRA_AUTOHEAL_MAX_PER_DAY", "1")
    # Seed one heal so the cap (1) is already reached.
    store.add_monitoring_check("f", "c", artifact_key="x", check_type="auto_heal", status="attempted")
    record = {"artifact_key": "landing_page", "artifact_title": "L", "agent": "web", "session_id": "s"}
    assert await scheduler._auto_heal("f", "c", record, _down_check()) is False


async def test_auto_heal_skips_when_run_active(vault, monkeypatch):
    monkeypatch.setattr("backend.core.session_store.has_active_run", lambda *a, **k: True)
    record = {"artifact_key": "landing_page", "artifact_title": "L", "agent": "web", "session_id": "s"}
    assert await scheduler._auto_heal("f", "c", record, _down_check()) is False


def test_start_monitoring_scheduler_prefers_temporal_schedule(monkeypatch):
    spawned = {}

    def _fake_create_task(coro):
        spawned["coro"] = coro
        class _Task:
            def done(self):
                return False
        return _Task()

    monkeypatch.setattr(scheduler, "_temporal_scheduler_enabled", lambda: True)
    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    status = scheduler.start_monitoring_scheduler(interval_seconds=300)

    assert status["scheduler"]["mode"] == "temporal"
    assert status["scheduler"]["schedule_id"] == "astra-monitoring-hourly"
    assert spawned["coro"] is not None
    spawned["coro"].close()


async def test_stop_monitoring_scheduler_deletes_temporal_schedule(monkeypatch):
    calls = []

    async def _fake_delete():
        calls.append("deleted")

    scheduler._status.update({
        "running": True,
        "mode": "temporal",
        "schedule_id": "astra-monitoring-hourly",
    })
    monkeypatch.setattr(scheduler, "_delete_temporal_schedule", _fake_delete)

    status = await scheduler.stop_monitoring_scheduler()

    assert calls == ["deleted"]
    assert status["scheduler"]["running"] is False

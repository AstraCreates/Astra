import asyncio
from types import SimpleNamespace

import pytest

from backend.control_plane import event_stream


@pytest.mark.asyncio
async def test_stream_run_events_replays_from_last_event_id(monkeypatch):
    monkeypatch.setattr(
        "backend.control_plane.event_stream.SupabaseRunRepository",
        lambda: SimpleNamespace(get=lambda _run_id: SimpleNamespace(id="run_1", org_id="org_1", status="running")),
    )
    monkeypatch.setattr(
        "backend.control_plane.event_stream.list_run_events",
        lambda run_id, after: asyncio.sleep(0, result=[
            {"run_id": run_id, "sequence": 3, "event_type": "agent_start", "payload": {"agent": "web"}},
            {"run_id": run_id, "sequence": 4, "event_type": "agent_done", "payload": {"agent": "web"}},
        ]),
    )
    monkeypatch.setattr("backend.core.events._redis", lambda: None)

    stream = event_stream.stream_run_events("run_1", last_event_id=2)
    try:
        first = await anext(stream)
        second = await anext(stream)
    finally:
        await stream.aclose()

    assert first.startswith("id: 3\n")
    assert second.startswith("id: 4\n")


@pytest.mark.asyncio
async def test_stream_run_events_uses_independent_cursors_per_subscriber(monkeypatch):
    monkeypatch.setattr(
        "backend.control_plane.event_stream.SupabaseRunRepository",
        lambda: SimpleNamespace(get=lambda _run_id: SimpleNamespace(id="run_1", org_id="org_1", status="running")),
    )
    monkeypatch.setattr(
        "backend.control_plane.event_stream.list_run_events",
        lambda _run_id, _after: asyncio.sleep(0, result=[]),
    )

    class FakeRedis:
        def __init__(self):
            self.calls = []

        def xread(self, streams, count=None, block=None):
            self.calls.append(dict(streams))
            return [(
                "events:org_1:run_1",
                [("1-0", {"payload": '{"sequence":1,"event_type":"agent_start","payload":{"agent":"web"}}'})],
            )]

    redis = FakeRedis()
    monkeypatch.setattr("backend.core.events._redis", lambda: redis)

    stream_a = event_stream.stream_run_events("run_1", last_event_id=0)
    stream_b = event_stream.stream_run_events("run_1", last_event_id=0)
    try:
        first_a = await anext(stream_a)
        first_b = await anext(stream_b)
    finally:
        await stream_a.aclose()
        await stream_b.aclose()

    assert first_a.startswith("id: 1\n")
    assert first_b.startswith("id: 1\n")
    assert redis.calls[0] == {"events:org_1:run_1": "0-0"}
    assert redis.calls[1] == {"events:org_1:run_1": "0-0"}


@pytest.mark.asyncio
async def test_stream_run_events_falls_back_to_supabase_after_redis_error(monkeypatch):
    states = iter([
        SimpleNamespace(id="run_1", org_id="org_1", status="running"),
        SimpleNamespace(id="run_1", org_id="org_1", status="succeeded"),
    ])
    monkeypatch.setattr(
        "backend.control_plane.event_stream.SupabaseRunRepository",
        lambda: SimpleNamespace(get=lambda _run_id: next(states)),
    )

    replay_calls = []

    async def fake_list_run_events(run_id, after):
        replay_calls.append((run_id, after))
        if len(replay_calls) == 1:
            return []
        return [{"run_id": run_id, "sequence": 2, "event_type": "goal_done", "payload": {"session_id": run_id}}]

    monkeypatch.setattr("backend.control_plane.event_stream.list_run_events", fake_list_run_events)

    class FailingRedis:
        def xread(self, *_args, **_kwargs):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr("backend.core.events._redis", lambda: FailingRedis())

    stream = event_stream.stream_run_events("run_1", last_event_id=0)
    try:
        first = await anext(stream)
    finally:
        await stream.aclose()

    assert first.startswith("id: 2\n")
    assert replay_calls == [("run_1", 0), ("run_1", 0)]

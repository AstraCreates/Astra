from types import SimpleNamespace

from backend.control_plane import event_stream


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _Supabase:
    def __init__(self, rows):
        self.rows = rows
        self.updates: list[tuple[str, dict]] = []

    def table(self, name):
        query = _Query(self.rows if name == "astra_outbox" else [])
        original_update = query.update

        def _update(patch):
            self.updates.append((name, patch))
            return original_update(patch)

        query.update = _update
        return query


def test_publish_outbox_batch_marks_success_and_clears_last_error(mocker):
    mocker.patch("backend.control_plane.event_stream._utc_now", return_value="2026-07-12T00:00:00Z")
    supabase = _Supabase([
        {"id": 1, "run_id": "run_1", "event_sequence": 7, "payload": {"type": "agent_done"}, "attempts": 0}
    ])
    mocker.patch("backend.db.client.get_supabase", return_value=supabase)

    redis = mocker.MagicMock()
    mocker.patch("backend.core.events._redis", return_value=redis)

    run_repo = mocker.MagicMock()
    run_repo.get.return_value = SimpleNamespace(org_id="org_1")
    mocker.patch("backend.control_plane.event_stream.SupabaseRunRepository", return_value=run_repo)

    published = event_stream._publish_outbox_batch_sync(limit=10)

    assert published == 1
    redis.xadd.assert_called_once()
    assert redis.xtrim.called
    assert ("astra_outbox", {"published_at": "2026-07-12T00:00:00Z", "attempts": 1, "last_error": None}) in supabase.updates


def test_publish_outbox_batch_dead_letters_after_retry_limit(mocker):
    mocker.patch("backend.control_plane.event_stream._utc_now", return_value="2026-07-12T00:00:00Z")
    supabase = _Supabase([
        {
            "id": 11,
            "run_id": "run_1",
            "event_sequence": 4,
            "payload": {"type": "agent_start"},
            "attempts": event_stream._OUTBOX_MAX_ATTEMPTS - 1,
            "last_error": None,
        }
    ])
    mocker.patch("backend.db.client.get_supabase", return_value=supabase)

    redis = mocker.MagicMock()
    redis.xadd.side_effect = RuntimeError("redis offline")
    mocker.patch("backend.core.events._redis", return_value=redis)

    run_repo = mocker.MagicMock()
    run_repo.get.return_value = SimpleNamespace(org_id="org_1")
    mocker.patch("backend.control_plane.event_stream.SupabaseRunRepository", return_value=run_repo)

    published = event_stream._publish_outbox_batch_sync(limit=10)

    assert published == 0
    dead_letter_patch = next(
        patch for table, patch in supabase.updates
        if table == "astra_outbox" and "dead_lettered_at" in patch
    )
    assert dead_letter_patch["attempts"] == event_stream._OUTBOX_MAX_ATTEMPTS
    assert dead_letter_patch["last_error"] == "redis offline"


def test_publish_outbox_batch_returns_zero_without_redis(mocker):
    supabase = _Supabase([])
    mocker.patch("backend.db.client.get_supabase", return_value=supabase)
    mocker.patch("backend.core.events._redis", return_value=None)

    assert event_stream._publish_outbox_batch_sync(limit=10) == 0

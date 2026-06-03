from backend.core.session_ids import new_session_id


def test_new_session_id_is_unique_for_repeated_launches():
    ids = [new_session_id() for _ in range(200)]

    assert len(set(ids)) == len(ids)
    assert all(len(session_id) == 32 for session_id in ids)
    assert all(session_id.isalnum() for session_id in ids)

from backend.core import usage


def test_active_model_pricing_matches_current_openrouter_rates():
    assert usage._PRICING["inclusionai/ling-2.6-flash"] == (0.01, 0.03, 0.001)
    assert usage._PRICING["xiaomi/mimo-v2.5"] == (0.105, 0.28, 0.0105)
    assert usage._PRICING["deepseek/deepseek-v4-pro"] == (0.435, 0.87, 0.0435)
    assert usage._PRICING["deepseek/deepseek-v4-flash"] == (0.09, 0.18, 0.009)


def test_cached_tokens_bill_at_cached_rate():
    cost = usage._cost_usd("inclusionai/ling-2.6-flash", 1_000_000, 0, 500_000)
    assert cost == 0.0055


def test_session_token_reservations_close_concurrent_launch_gap():
    session_id = "reservation_test_session"

    assert usage.reserve_session_tokens(session_id, 600, 1_000) is True
    assert usage.reserve_session_tokens(session_id, 500, 1_000) is False

    usage.release_session_tokens(session_id, 600)
    assert usage.reserve_session_tokens(session_id, 500, 1_000) is True
    usage.release_session_tokens(session_id, 500)

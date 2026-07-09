from backend.api.routes import _run_option_exclusions


def test_default_both_excludes_nothing():
    assert _run_option_exclusions("both", "both") == []
    assert _run_option_exclusions(None, None) == []


def test_technical_scope_none_excludes_technical_and_web():
    assert set(_run_option_exclusions("none", "both")) == {"technical", "web"}


def test_technical_scope_website_excludes_technical_only():
    assert _run_option_exclusions("website", "both") == ["technical"]


def test_technical_scope_technical_excludes_web_only():
    assert _run_option_exclusions("technical", "both") == ["web"]


def test_marketing_organic_excludes_marketing_paid():
    assert _run_option_exclusions("both", "organic") == ["marketing_paid"]


def test_combined_technical_none_and_organic():
    result = _run_option_exclusions("none", "organic")
    assert set(result) == {"technical", "web", "marketing_paid"}

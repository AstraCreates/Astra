from backend.tools.web_navigator_tools import (
    _goal_requests_secret,
    _looks_like_email_verification,
    _scan_for_keys,
    _service_name_from_url,
)


def test_goal_requests_secret_detects_key_retrieval_language():
    assert _goal_requests_secret("Sign up and copy the API key from settings")
    assert _goal_requests_secret("Grab the webhook secret after creating the account")
    assert not _goal_requests_secret("Create an account and land on the dashboard")


def test_email_verification_phrase_detection():
    assert _looks_like_email_verification("Check your email for a verification code to continue.")
    assert _looks_like_email_verification("Enter the confirmation code we sent you")
    assert not _looks_like_email_verification("Welcome to your dashboard")


def test_scan_for_keys_extracts_known_provider_tokens():
    found = _scan_for_keys("Use sk-or-v1-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN1234567890 and ghp_123456789012345678901234567890123456")
    assert found["openrouter_api_key"].startswith("sk-or-v1-")
    assert found["github_token"].startswith("ghp_")


def test_service_name_from_url_uses_host_prefix():
    assert _service_name_from_url("https://platform.openai.com/api-keys") == "platform"
    assert _service_name_from_url("https://vercel.com/dashboard") == "vercel"

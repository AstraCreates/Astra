import pytest

from backend.control_plane.gateway import (
    GatewayUnavailableError,
    gateway_extra_body,
    get_gateway_client,
    handle_gateway_connection_error,
    is_model_gateway_enabled,
    normalize_model_alias,
    reconcile_gateway_usage,
)


class _PromptTokensDetails:
    def __init__(self, cached_tokens=0):
        self.cached_tokens = cached_tokens


class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0, cached_tokens=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        if cached_tokens is not None:
            self.prompt_tokens_details = _PromptTokensDetails(cached_tokens)


class _Response:
    def __init__(self, usage=None, hidden_params=None):
        if usage is not None:
            self.usage = usage
        if hidden_params is not None:
            self._hidden_params = hidden_params


def test_normalize_model_alias_is_identity_for_known_models():
    assert normalize_model_alias("deepseek/deepseek-v4-flash") == "deepseek/deepseek-v4-flash"
    assert normalize_model_alias("xiaomi/mimo-v2.5") == "xiaomi/mimo-v2.5"


def test_normalize_model_alias_trims_whitespace():
    assert normalize_model_alias("  deepseek/deepseek-v4-flash  ") == "deepseek/deepseek-v4-flash"


def test_normalize_model_alias_empty_and_none():
    assert normalize_model_alias("") == ""
    assert normalize_model_alias(None) == ""


def test_normalize_model_alias_strips_openrouter_prefix():
    assert normalize_model_alias("openrouter/deepseek/deepseek-v4-flash") == "deepseek/deepseek-v4-flash"


def test_normalize_model_alias_case_insensitive_match_preserves_declared_casing():
    assert normalize_model_alias("XIAOMI/MIMO-V2.5") == "xiaomi/mimo-v2.5"


def test_normalize_model_alias_unlisted_model_passes_through_cleaned():
    assert normalize_model_alias("  some/unlisted-model  ") == "some/unlisted-model"


def test_reconcile_gateway_usage_extracts_tokens_and_cost():
    resp = _Response(
        usage=_Usage(prompt_tokens=120, completion_tokens=45),
        hidden_params={"response_cost": 0.00873},
    )
    prompt, completion, cost, cached = reconcile_gateway_usage(resp)
    assert prompt == 120
    assert completion == 45
    assert cost == pytest.approx(0.00873)
    assert cached == 0


def test_reconcile_gateway_usage_extracts_cached_tokens():
    resp = _Response(usage=_Usage(prompt_tokens=120, completion_tokens=45, cached_tokens=80))
    _, _, _, cached = reconcile_gateway_usage(resp)
    assert cached == 80


def test_reconcile_gateway_usage_missing_hidden_params_returns_zero_cost():
    resp = _Response(usage=_Usage(prompt_tokens=10, completion_tokens=5))
    prompt, completion, cost, cached = reconcile_gateway_usage(resp)
    assert prompt == 10
    assert completion == 5
    assert cost == 0.0
    assert cached == 0


def test_reconcile_gateway_usage_missing_usage_returns_zeros():
    resp = _Response(hidden_params={"response_cost": 0.01})
    prompt, completion, cost, cached = reconcile_gateway_usage(resp)
    assert prompt == 0
    assert completion == 0
    # usage missing entirely -> defensive path also skips cost extraction? No --
    # cost extraction is independent of usage; hidden_params is present so cost
    # should still be picked up.
    assert cost == pytest.approx(0.01)
    assert cached == 0


def test_reconcile_gateway_usage_completely_malformed_response_returns_zeros():
    class _Garbage:
        pass

    prompt, completion, cost, cached = reconcile_gateway_usage(_Garbage())
    assert (prompt, completion, cost, cached) == (0, 0, 0.0, 0)


def test_reconcile_gateway_usage_never_raises_on_none():
    prompt, completion, cost, cached = reconcile_gateway_usage(None)
    assert (prompt, completion, cost, cached) == (0, 0, 0.0, 0)


def test_reconcile_gateway_usage_non_numeric_cost_defaults_to_zero():
    resp = _Response(
        usage=_Usage(prompt_tokens=10, completion_tokens=5),
        hidden_params={"response_cost": "not-a-number"},
    )
    prompt, completion, cost, cached = reconcile_gateway_usage(resp)
    assert prompt == 10
    assert completion == 5
    assert cost == 0.0
    assert cached == 0


def test_is_model_gateway_enabled_true():
    assert is_model_gateway_enabled({"model_gateway_v2": True}) is True


def test_is_model_gateway_enabled_false_when_absent():
    assert is_model_gateway_enabled({}) is False
    assert is_model_gateway_enabled({"engine": "temporal"}) is False


def test_is_model_gateway_enabled_handles_none():
    assert is_model_gateway_enabled(None) is False


def test_gateway_extra_body_shape():
    body = gateway_extra_body("founder_1", "run_1", "step_1")
    assert body == {
        "metadata": {"run_id": "run_1", "step_id": "step_1", "founder_id": "founder_1"}
    }


def test_gateway_extra_body_handles_missing_step_id():
    body = gateway_extra_body("founder_1", "run_1", None)
    assert body["metadata"]["step_id"] == ""


def test_gateway_extra_body_omits_reservation_and_trace_when_absent():
    body = gateway_extra_body("founder_1", "run_1", "step_1")
    assert "reservation_id" not in body["metadata"]
    assert "trace_id" not in body["metadata"]
    assert "span_id" not in body["metadata"]


def test_gateway_extra_body_links_reservation_and_trace_when_present():
    body = gateway_extra_body(
        "founder_1", "run_1", "step_1",
        reservation_id="res_1", trace_id="abc123", span_id="def456",
    )
    assert body["metadata"]["reservation_id"] == "res_1"
    assert body["metadata"]["trace_id"] == "abc123"
    assert body["metadata"]["span_id"] == "def456"


def test_get_gateway_client_raises_when_base_url_unset(monkeypatch):
    monkeypatch.setattr("backend.config.settings.litellm_gateway_base_url", "")
    with pytest.raises(GatewayUnavailableError):
        get_gateway_client("founder_1", "run_1", "step_1")


def test_get_gateway_client_configures_base_url_and_headers(monkeypatch):
    monkeypatch.setattr("backend.config.settings.litellm_gateway_base_url", "http://litellm:4000")
    monkeypatch.setattr("backend.config.settings.litellm_master_key", "sk-test-key")

    client = get_gateway_client("founder_1", "run_1", "step_1")

    assert "litellm:4000" in str(client.base_url)
    assert client.api_key == "sk-test-key"
    assert client.default_headers["X-Astra-Run-Id"] == "run_1"
    assert client.default_headers["X-Astra-Step-Id"] == "step_1"
    assert client.default_headers["X-Astra-Founder-Id"] == "founder_1"


def test_get_gateway_client_prefers_org_virtual_key_when_configured(monkeypatch):
    monkeypatch.setattr("backend.config.settings.litellm_gateway_base_url", "http://litellm:4000")
    monkeypatch.setattr("backend.config.settings.litellm_master_key", "sk-master")
    monkeypatch.setattr("backend.config.settings.litellm_org_keys_json", '{"founder_1": "sk-org"}')

    client = get_gateway_client("founder_1", "run_1", "step_1")

    assert client.api_key == "sk-org"


def test_get_gateway_client_falls_back_to_master_key_when_org_key_missing(monkeypatch):
    monkeypatch.setattr("backend.config.settings.litellm_gateway_base_url", "http://litellm:4000")
    monkeypatch.setattr("backend.config.settings.litellm_master_key", "sk-master")
    monkeypatch.setattr("backend.config.settings.litellm_org_keys_json", '{"other": "sk-org"}')

    client = get_gateway_client("founder_1", "run_1", "step_1")

    assert client.api_key == "sk-master"


def test_handle_gateway_connection_error_raises_when_direct_provider_disabled():
    with pytest.raises(GatewayUnavailableError):
        handle_gateway_connection_error(RuntimeError("boom"), direct_provider_disabled=True)


def test_handle_gateway_connection_error_returns_quietly_when_direct_provider_allowed():
    handle_gateway_connection_error(RuntimeError("boom"), direct_provider_disabled=False)

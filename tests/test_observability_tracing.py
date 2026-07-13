import pytest

from backend.observability import tracing


def test_redact_attributes_masks_sensitive_keys():
    attrs = {
        "goal": "build a startup that sells widgets",
        "credentials": "supersecret",
        "run.id": "run_123",
        "nested": {"api_key": "sk-live-abc123", "safe_field": "keep me"},
    }
    redacted = tracing.redact_attributes(attrs)
    assert redacted["goal"] == "[REDACTED]"
    assert redacted["credentials"] == "[REDACTED]"
    assert redacted["run.id"] == "run_123"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "keep me"


def test_redact_attributes_case_insensitive_substring_match():
    attrs = {"API_KEY_2": "x", "Tool_Arguments": {"raw": "y"}, "OK_FIELD": "z"}
    redacted = tracing.redact_attributes(attrs)
    assert redacted["API_KEY_2"] == "[REDACTED]"
    assert redacted["Tool_Arguments"] == "[REDACTED]"
    assert redacted["OK_FIELD"] == "z"


def test_redact_attributes_passes_through_non_dict():
    assert tracing.redact_attributes("just a string") == "just a string"
    assert tracing.redact_attributes(None) is None
    assert tracing.redact_attributes(42) == 42
    assert tracing.redact_attributes(["goal", "credentials"]) == ["goal", "credentials"]


def test_redact_attributes_recurses_into_list_items():
    attrs = {"events": [{"api_key": "secret"}, {"safe": "ok"}]}
    redacted = tracing.redact_attributes(attrs)
    assert redacted["events"][0]["api_key"] == "[REDACTED]"
    assert redacted["events"][1]["safe"] == "ok"


def test_redact_attributes_leaves_unrelated_keys_untouched():
    attrs = {"run.id": "r1", "step.key": "s1", "attempt.number": 2}
    assert tracing.redact_attributes(attrs) == attrs


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Ensure tracing is in its default (never-initialized) no-op state for
    every test in this file, and restore whatever it was afterward."""
    prev_initialized = tracing._initialized
    prev_tracer = tracing._tracer
    tracing._initialized = False
    tracing._tracer = None
    yield
    tracing._initialized = prev_initialized
    tracing._tracer = prev_tracer


def test_get_tracer_is_none_before_init():
    assert tracing.get_tracer() is None


@pytest.mark.parametrize(
    "cm_factory",
    [
        lambda: tracing.run_span("run_1", "org_1", "owner_1"),
        lambda: tracing.workflow_span("run_1", "legacy"),
        lambda: tracing.phase_span("run_1", "design"),
        lambda: tracing.step_attempt_span("run_1", "step_1", "web", 1),
        lambda: tracing.model_call_span("run_1", "step_1", "deepseek/deepseek-v4-flash", "openrouter", 0),
        lambda: tracing.tool_call_span("run_1", "step_1", "run_mvp_loop"),
        lambda: tracing.action_span("run_1", "action_1", "deploy", None),
        lambda: tracing.artifact_span("run_1", "artifact_1", "pitch_deck"),
    ],
)
def test_span_context_managers_are_noop_without_init(cm_factory):
    with cm_factory() as span:
        span.set_attribute("anything", "value")
        span.record_exception(RuntimeError("should be a no-op"))


def test_span_context_manager_propagates_exceptions():
    with pytest.raises(ValueError):
        with tracing.run_span("run_1", "org_1", "owner_1"):
            raise ValueError("boom")


def test_span_context_manager_propagates_exceptions_when_initialized():
    tracing.init_tracing("test-service")
    with pytest.raises(RuntimeError):
        with tracing.model_call_span("run_1", "step_1", "some/model", "openrouter", 0) as span:
            span.set_attribute("tokens.prompt", 10)
            raise RuntimeError("model call blew up")


def test_init_tracing_never_raises_and_is_idempotent():
    tracing.init_tracing("test-service")
    tracing.init_tracing("test-service")
    assert tracing._initialized is True


def test_get_tracer_after_init_when_opentelemetry_available():
    tracing.init_tracing("test-service")
    if tracing._OTEL_AVAILABLE:
        assert tracing.get_tracer() is not None
    else:
        assert tracing.get_tracer() is None


def test_get_trace_ids_is_empty_for_noop_span():
    with tracing.run_span("run_1", "org_1", "owner_1") as span:
        assert tracing.get_trace_ids(span) == ("", "")


def test_get_trace_ids_never_raises_on_garbage():
    class _NoGetContext:
        pass

    assert tracing.get_trace_ids(_NoGetContext()) == ("", "")
    assert tracing.get_trace_ids(None) == ("", "")


def test_get_trace_ids_returns_real_hex_ids_when_initialized():
    tracing.init_tracing("test-service")
    if not tracing._OTEL_AVAILABLE:
        pytest.skip("opentelemetry not installed")
    with tracing.model_call_span("run_1", "step_1", "some/model", "openrouter", 0) as span:
        trace_id, span_id = tracing.get_trace_ids(span)
        assert len(trace_id) == 32
        assert len(span_id) == 16


def test_step_attempt_span_accepts_org_id_and_queue_delay():
    with tracing.step_attempt_span(
        "run_1", "step_1", "web", 1, org_id="org_1", queue_delay_seconds=2.5,
    ) as span:
        span.set_attribute("anything", "value")


def test_step_attempt_span_omits_queue_delay_when_none():
    # No-op locally; real assertion is that passing None never raises and the
    # attribute is simply skipped (see _span_attempt_span's `if queue_delay_seconds
    # is not None` guard) rather than reporting a fabricated 0.
    with tracing.step_attempt_span("run_1", "step_1", "web", 1) as span:
        span.set_attribute("anything", "value")

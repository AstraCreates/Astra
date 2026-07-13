"""Wave 5.2 control plane: OpenTelemetry tracing.

Trace hierarchy per PLAN.md: run -> workflow -> phase -> step attempt ->
model/tool/action -> artifact. Langfuse stays disabled
(backend.config.settings.astra_langfuse_enabled) -- this module is the
mandatory OTel path; it does not touch that flag.

Every context manager here is a no-op (yields a dummy span whose methods do
nothing) unless init_tracing() has actually been called AND opentelemetry is
importable. That makes an un-configured deployment (no OTEL_EXPORTER_ENDPOINT)
free: no span objects, no export machinery, nothing that can fail mid-run.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Iterator

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
        ConsoleSpanExporter as _ConsoleSpanExporter,
        SimpleSpanProcessor as _SimpleSpanProcessor,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as _OTLPSpanExporter,
    )

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised in envs without opentelemetry installed
    _OTEL_AVAILABLE = False


# Substrings (case-insensitive) that mark a span-attribute key as sensitive.
# Goals/vault content/credentials/raw tool arguments/PII must never reach an
# exporter verbatim -- see PLAN.md Wave 5.2. Substring match (not exact) so
# "vault_context", "api_key_2", "tool_arguments_raw" etc. all get caught.
REDACTED_KEYS: frozenset[str] = frozenset({
    "goal",
    "instruction",
    "vault",
    "credential",
    "credentials",
    "password",
    "token",
    "api_key",
    "apikey",
    "secret",
    "tool_arguments",
    "tool_args",
    "authorization",
    "cookie",
    "ssn",
    "pii",
})

_tracer: Any = None
_initialized = False


def init_tracing(service_name: str = "astra-backend") -> None:
    """Set up the process-wide TracerProvider. Call once at app startup.

    Empty/unset otel_exporter_endpoint means "no OTLP exporter" -- spans
    still get created (so the instrumentation is actually exercised locally)
    but are only ever printed via ConsoleSpanExporter, never sent over the
    network. Any failure here disables tracing instead of raising, per the
    "must never crash a run" constraint.
    """
    global _tracer, _initialized
    if _initialized:
        return
    _initialized = True
    if not _OTEL_AVAILABLE:
        logger.info("opentelemetry not installed; tracing disabled")
        return
    try:
        from backend.config import settings

        endpoint = str(getattr(settings, "otel_exporter_endpoint", "") or "").strip()
        resource = _Resource.create({"service.name": service_name})
        provider = _TracerProvider(resource=resource)
        if endpoint:
            provider.add_span_processor(
                _BatchSpanProcessor(_OTLPSpanExporter(endpoint=endpoint))
            )
        else:
            # Local dev with no endpoint configured: still exercise the real span
            # API (catches instrumentation bugs) without external I/O. Simple (not
            # batch) processor -- no background export thread to leak/outlive a
            # short-lived process (e.g. a test run whose stdout gets closed).
            provider.add_span_processor(_SimpleSpanProcessor(_ConsoleSpanExporter()))
        _otel_trace.set_tracer_provider(provider)
        _tracer = _otel_trace.get_tracer(service_name)
        logger.info("OpenTelemetry tracing initialized (endpoint=%s)", endpoint or "<console>")
    except Exception:
        logger.exception("init_tracing failed; tracing disabled")
        _tracer = None


def get_tracer() -> Any:
    """Return the module-level tracer, or None if tracing was never initialized."""
    return _tracer


def _key_is_redacted(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in REDACTED_KEYS)


def redact_attributes(attrs: Any) -> Any:
    """Recursively mask sensitive keys in a dict. Non-dict input passes through untouched."""
    if not isinstance(attrs, dict):
        if isinstance(attrs, list):
            return [redact_attributes(item) for item in attrs]
        if isinstance(attrs, tuple):
            return tuple(redact_attributes(item) for item in attrs)
        return attrs
    redacted: dict[str, Any] = {}
    for key, value in attrs.items():
        if _key_is_redacted(str(key)):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_attributes(value)
        elif isinstance(value, list):
            redacted[key] = [redact_attributes(item) for item in value]
        elif isinstance(value, tuple):
            redacted[key] = tuple(redact_attributes(item) for item in value)
        else:
            redacted[key] = value
    return redacted


class _NoOpSpan:
    """Stand-in for opentelemetry.trace.Span when tracing is disabled/unavailable."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attrs: dict) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass


_NOOP_SPAN = _NoOpSpan()


def get_trace_ids(span: Any) -> tuple[str, str]:
    """Best-effort (trace_id_hex, span_id_hex) for any span this module
    handed out -- "" for both on a _NoOpSpan or any real-span extraction
    failure. Lets a call site (e.g. the LiteLLM gateway client) link its
    request metadata back to the OTel trace without needing to know whether
    tracing is actually configured."""
    try:
        ctx = span.get_span_context()
        if ctx is None or not getattr(ctx, "is_valid", True):
            return "", ""
        return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:
        return "", ""


def _set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if not attributes:
        return
    redacted = redact_attributes(attributes)
    for key, value in redacted.items():
        if value is None:
            continue
        try:
            span.set_attribute(key, value)
        except Exception:
            pass
    try:
        from backend.observability.langfuse_hooks import emit_langfuse_event

        emit_langfuse_event("span.attributes", redacted)
    except Exception:
        pass


@contextlib.contextmanager
def _span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Shared implementation for every hierarchy-level context manager below.

    Span start/registration is wrapped in try/except -- that's the operation
    with real (I/O, sandboxing) failure modes. The caller's yielded block is
    NOT wrapped in a swallowing try/except: exceptions there are recorded on
    the span and then re-raised untouched, so tracing is transparent to
    normal error handling.
    """
    span: Any = _NOOP_SPAN
    span_cm: Any = None
    if _initialized and _tracer is not None:
        try:
            span_cm = _tracer.start_as_current_span(name)
            span = span_cm.__enter__()
            _set_span_attributes(span, attributes)
        except Exception:
            logger.debug("tracing span start failed for %s", name, exc_info=True)
            span = _NOOP_SPAN
            span_cm = None
    try:
        yield span
    except Exception as exc:
        try:
            span.record_exception(exc)
            span.set_attribute("error.class", type(exc).__name__)
        except Exception:
            pass
        raise
    finally:
        if span_cm is not None:
            try:
                span_cm.__exit__(None, None, None)
            except Exception:
                pass


@contextlib.contextmanager
def run_span(run_id: str, org_id: str, owner_id: str) -> Iterator[Any]:
    """Top of the trace hierarchy: one run."""
    with _span("astra.run", {"run.id": run_id, "org.id": org_id, "owner.id": owner_id}) as span:
        yield span


@contextlib.contextmanager
def workflow_span(run_id: str, engine: str) -> Iterator[Any]:
    """Nested under run: the workflow engine driving it (legacy | temporal)."""
    with _span("astra.workflow", {"run.id": run_id, "workflow.engine": engine}) as span:
        yield span


@contextlib.contextmanager
def phase_span(run_id: str, phase: str) -> Iterator[Any]:
    """Nested under workflow: one plan phase (diagnose/design/deploy/...)."""
    with _span("astra.phase", {"run.id": run_id, "phase.name": phase}) as span:
        yield span


@contextlib.contextmanager
def step_attempt_span(
    run_id: str,
    step_key: str,
    agent: str,
    attempt_number: int,
    org_id: str = "",
    queue_delay_seconds: float | None = None,
) -> Iterator[Any]:
    """Nested under phase: one attempt at executing a step.

    queue_delay_seconds is the schedule-to-start latency (how long the step
    sat queued before this attempt actually began executing) -- optional
    because it's only knowable when the caller runs inside a Temporal
    activity context with a real scheduled_time (see
    backend/control_plane/temporal/execution.py's use of
    temporalio.activity.info()); direct/test invocations pass None and the
    attribute is simply omitted rather than reported as a fake zero."""
    attrs: dict[str, Any] = {
        "run.id": run_id,
        "step.key": step_key,
        "agent": agent,
        "attempt.number": attempt_number,
    }
    if org_id:
        attrs["org.id"] = org_id
    if queue_delay_seconds is not None:
        attrs["queue.delay_seconds"] = queue_delay_seconds
    with _span("astra.step_attempt", attrs) as span:
        yield span


@contextlib.contextmanager
def model_call_span(
    run_id: str, step_key: str, model_alias: str, provider: str, retry_count: int, org_id: str = "",
) -> Iterator[Any]:
    """Nested under step attempt: one LLM call. Caller sets tokens/cost on the
    yielded span (e.g. span.set_attribute("tokens.prompt", n)) once the
    response is in hand -- those land before the span closes."""
    attrs: dict[str, Any] = {
        "run.id": run_id,
        "step.key": step_key,
        "model.alias": model_alias,
        "model.provider": provider,
        "retry.count": retry_count,
    }
    if org_id:
        attrs["org.id"] = org_id
    with _span("astra.model_call", attrs) as span:
        yield span


@contextlib.contextmanager
def tool_call_span(run_id: str, step_key: str, tool_name: str, org_id: str = "") -> Iterator[Any]:
    """Nested under step attempt: one tool invocation."""
    attrs: dict[str, Any] = {"run.id": run_id, "step.key": step_key, "tool.name": tool_name}
    if org_id:
        attrs["org.id"] = org_id
    with _span("astra.tool_call", attrs) as span:
        yield span


@contextlib.contextmanager
def action_span(
    run_id: str, action_id: str, tool: str, approval_id: str | None, org_id: str = "",
) -> Iterator[Any]:
    """Nested under step attempt: one durable external side effect. Caller
    sets action.receipt on the yielded span once the provider receipt exists."""
    attrs: dict[str, Any] = {"run.id": run_id, "action.id": action_id, "tool.name": tool}
    if approval_id:
        attrs["approval.id"] = approval_id
    if org_id:
        attrs["org.id"] = org_id
    with _span("astra.action", attrs) as span:
        yield span


@contextlib.contextmanager
def artifact_span(run_id: str, artifact_id: str, key: str) -> Iterator[Any]:
    """Leaf of the hierarchy: one produced/verified artifact."""
    with _span(
        "astra.artifact",
        {"run.id": run_id, "artifact.id": artifact_id, "artifact.key": key},
    ) as span:
        yield span

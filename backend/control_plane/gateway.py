"""Wave 5.1 LiteLLM proxy gateway client (PLAN.md target path: Astra ->
LiteLLM -> Headroom -> OpenRouter).

Gated by the model_gateway_v2 run feature (backend/control_plane/rollout.py)
-- backend/core/agent.py branches to get_gateway_client() only when a run's
persisted feature_assignment has it on; every other run keeps calling
backend.core.factory/llm_client's direct OpenRouter client unchanged. Headroom
stays a separate, upstream-of-this compression hop (backend points
OPENROUTER_BASE_URL at Headroom already); this module never talks to it
directly, same as the direct path today.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GatewayUnavailableError(RuntimeError):
    """Raised when the LiteLLM gateway can't be used for this call.

    backend/core/agent.py decides what to do with it: astra_direct_provider_disabled=True
    re-raises (fail loud -- direct calls bypass LiteLLM's spend tracking entirely);
    False (default/dev) falls back to the existing direct OpenRouter client.
    """


# deploy/litellm/config.yaml's model_list -- kept in sync manually (see that
# file's header comment). Maps known non-canonical spellings that might reach
# this function (a stale "openrouter/" prefix already on the string, a
# different case) to the exact model_name the proxy has declared. Anything
# not listed here just gets case/prefix-normalized and passed through, so an
# unlisted model still reaches the proxy and 404s loudly there rather than
# being silently swallowed here.
_KNOWN_GATEWAY_ALIASES: frozenset[str] = frozenset({
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "xiaomi/mimo-v2.5",
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2.5",
    "google/gemini-2.5-pro",
    "google/gemini-3.1-flash-lite",
    "perplexity/sonar",
    "inclusionai/ling-2.6-flash",
})


def normalize_model_alias(model_name: str) -> str:
    """Map an Astra internal model identifier to the alias exposed by
    deploy/litellm/config.yaml's model_list.

    self.model is sometimes constructed with a leading "openrouter/" (some
    call sites build kwargs["model"] straight from a *_MODEL_NAME setting
    that already includes it, others don't) -- strip that prefix so both
    forms resolve to the same declared model_name. Case-fold the comparison
    against the known list but preserve the declared casing on a match,
    since OpenRouter model strings are case-sensitive."""
    cleaned = (model_name or "").strip()
    if cleaned.lower().startswith("openrouter/"):
        cleaned = cleaned[len("openrouter/"):]
    lowered = cleaned.lower()
    for known in _KNOWN_GATEWAY_ALIASES:
        if known.lower() == lowered:
            return known
    return cleaned


def get_gateway_client(founder_id: str, run_id: str, step_id: Optional[str] = None) -> Any:
    """Return an OpenAI-SDK client pointed at the LiteLLM proxy.

    Does not itself probe connectivity -- constructing an openai.OpenAI client
    never makes a network call, so a down litellm container only surfaces once
    the caller actually fires a request (same as any other OpenAI-SDK usage).
    Only raises GatewayUnavailableError for the statically-detectable case: no
    base_url configured at all.
    """
    import openai

    from backend.config import settings

    base_url = (settings.litellm_gateway_base_url or "").strip()
    if not base_url:
        raise GatewayUnavailableError("litellm_gateway_base_url is not configured")

    api_key = _resolve_gateway_api_key(founder_id)

    return openai.OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={
            "X-Astra-Run-Id": str(run_id or ""),
            "X-Astra-Step-Id": str(step_id or ""),
            "X-Astra-Founder-Id": str(founder_id or ""),
        },
    )


def _resolve_gateway_api_key(founder_id: str) -> str:
    """Pick a LiteLLM virtual key for this org when configured.

    Production can seed a JSON mapping via settings.litellm_org_keys_json. The
    lookup is founder/org keyed because that is the identity the gateway
    already sees at request time. If no org-specific key exists we fall back
    to the master key so the proxy continues to work in dev and during
    partial rollout.
    """
    from backend.config import settings

    raw = (settings.litellm_org_keys_json or "").strip()
    if raw and founder_id:
        try:
            mapping = json.loads(raw)
            if isinstance(mapping, dict):
                key = mapping.get(founder_id)
                if isinstance(key, str) and key.strip():
                    return key.strip()
        except Exception as exc:
            logger.warning("Malformed litellm_org_keys_json; falling back to shared gateway key: %s", exc)
    return settings.litellm_master_key or "sk-astra-gateway"


def gateway_extra_body(
    founder_id: str,
    run_id: str,
    step_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
) -> dict[str, Any]:
    """extra_body to merge into a chat.completions.create(**kwargs) call so
    LiteLLM tags spend with run_id/step_id/founder_id (LiteLLM's documented
    per-request metadata convention -- metadata lives in the request body,
    not the client, so this is computed per-call rather than baked into
    get_gateway_client's returned client).

    reservation_id/trace_id/span_id are optional because not every call site
    has them available (e.g. a probe call with no active budget reservation,
    or tracing disabled) -- PLAN.md's "request IDs linked to reservations and
    traces" requirement is best-effort: when present they let an operator
    join a LiteLLM spend row back to the exact astra_budget_reservations row
    and OTel span that produced it, but their absence must never block the
    call itself."""
    metadata: dict[str, Any] = {
        "run_id": str(run_id or ""),
        "step_id": str(step_id or ""),
        "founder_id": str(founder_id or ""),
    }
    if reservation_id:
        metadata["reservation_id"] = str(reservation_id)
    if trace_id:
        metadata["trace_id"] = str(trace_id)
    if span_id:
        metadata["span_id"] = str(span_id)
    return {"metadata": metadata}


def handle_gateway_connection_error(exc: Exception, *, direct_provider_disabled: bool) -> None:
    """Central raise-or-fall-back decision for a gateway request that failed
    to connect. Raises GatewayUnavailableError when direct_provider_disabled
    is True (production safety valve -- fail loud instead of silently
    routing spend around LiteLLM); returns normally otherwise so the caller
    falls back to the direct OpenRouter client for that attempt."""
    if direct_provider_disabled:
        raise GatewayUnavailableError(f"litellm gateway unavailable: {exc}") from exc


def reconcile_gateway_usage(response: Any, headers: Any = None) -> tuple[int, int, float, int]:
    """Extract (prompt_tokens, completion_tokens, actual_cost_usd,
    cached_tokens) from a LiteLLM proxy chat-completion response. Defensive
    by design -- this feeds a budget commit() call, so a malformed/unexpected
    response object must never raise, only degrade to zeros.

    cost_usd comes from LiteLLM's `x-litellm-response-cost` response header
    (pass it via `headers`, e.g. `client...with_raw_response.create(...).headers`)
    -- LiteLLM only attaches `_hidden_params` to responses returned by its
    in-process `litellm.completion()` call; the real gateway path here goes
    over HTTP via `openai.OpenAI()`, whose parsed response never has that
    attribute, so `_hidden_params` is checked only as a same-process fallback.
    cached_tokens is returned separately (not baked into cost_usd) so callers
    that DO want the local rate-table calculation (e.g. to cross-check the
    gateway's number) can still get an accurate cache-discounted result from
    _cost_usd(model, prompt_tokens, completion_tokens, cached_tokens)."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    cost_usd = 0.0
    try:
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    except Exception:
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
    try:
        raw_cost = None
        if headers is not None:
            raw_cost = headers.get("x-litellm-response-cost")
        if raw_cost is None:
            hidden_params = getattr(response, "_hidden_params", None) or {}
            raw_cost = hidden_params.get("response_cost") if isinstance(hidden_params, dict) else None
        cost_usd = float(raw_cost) if raw_cost is not None else 0.0
    except Exception:
        cost_usd = 0.0
    return prompt_tokens, completion_tokens, cost_usd, cached_tokens


def is_model_gateway_enabled(feature_assignment: dict) -> bool:
    """Same read pattern as engine/other v2 flags elsewhere (see
    backend/control_plane/start_run.py's feature_assignment.get("engine"))."""
    return bool((feature_assignment or {}).get("model_gateway_v2"))

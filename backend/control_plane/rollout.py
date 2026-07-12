"""Wave 1 control plane: run-level feature assignment.

backend/runtime/rollout.py::enabled() is a live, per-call check keyed on
founder_id -- right for gradually rolling out a UI tweak, wrong model for
"this run is permanently on Temporal." System invariant this module exists
to satisfy (PLAN.md): "A feature flag is resolved once when a run is
created and stored on that run. Flags never move an in-flight run between
engines." assign_run_features() must be called exactly once, at run
creation (Wave 2's StartRun), and the result persisted onto the run record
-- never re-evaluated for an in-flight run.
"""
from __future__ import annotations

import hashlib

_FEATURES = (
    "control_plane_v2",
    "event_stream_v2",
    "model_gateway_v2",
    "research_engine_v2",
    "brain_v2",
)


def _bucket(org_id: str, run_id: str, feature: str) -> int:
    # Deliberately NOT backend.runtime.rollout._bucket, which is keyed on
    # founder_id -- wrong key for a run-level, engine-sticky assignment.
    # backend/runtime/rollout.py is out of this task's owned-files scope, so
    # this ~3-line hash is duplicated locally rather than refactored to share.
    digest = hashlib.sha256(f"{feature}:{org_id}:{run_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def _feature_enabled(org_id: str, run_id: str, feature: str) -> bool:
    from backend.config import settings
    from backend.runtime.circuit_breaker import is_disabled

    if is_disabled(feature):
        return False
    if not bool(getattr(settings, f"astra_{feature}", False)):
        return False
    percentage = max(0, min(100, int(getattr(settings, f"astra_{feature}_rollout_percent", 0))))
    return percentage >= 100 or _bucket(org_id, run_id, feature) < percentage


def assign_run_features(org_id: str, run_id: str) -> dict[str, "bool | str"]:
    """Resolve every control-plane feature flag ONCE for a run, deterministically,
    keyed on (org_id, run_id) rather than founder_id. Call this exactly once when
    a run is created (Wave 2's StartRun); persist the result on the run record.
    Never call this again for an in-flight run -- flags must not move a run
    between engines mid-execution."""
    from backend.config import settings
    from backend.runtime.circuit_breaker import is_disabled

    resolved = {feature: _feature_enabled(org_id, run_id, feature) for feature in _FEATURES}

    shadow_percentage = max(0, min(100, int(settings.astra_temporal_shadow_percent)))
    temporal_shadow = (
        not is_disabled("temporal_shadow")
        and (shadow_percentage >= 100 or _bucket(org_id, run_id, "temporal_shadow") < shadow_percentage)
        and shadow_percentage > 0
    )

    return {
        "engine": "temporal" if resolved["control_plane_v2"] else "legacy",
        "control_plane_v2": resolved["control_plane_v2"],
        "event_stream_v2": resolved["event_stream_v2"],
        "model_gateway_v2": resolved["model_gateway_v2"],
        "research_engine_v2": resolved["research_engine_v2"],
        "brain_v2": resolved["brain_v2"],
        "langfuse_enabled": bool(settings.astra_langfuse_enabled),
        "temporal_shadow": temporal_shadow,
    }

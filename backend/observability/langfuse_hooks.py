"""Wave 5.2 compatibility hooks for Langfuse.

The migration plan requires Langfuse support to exist in code but stay
disabled until a separate resource benchmark passes. This module provides a
single no-op-compatible integration point that callers can invoke freely:
when disabled (the default), every function returns immediately; when enabled,
it still best-efforts and never crashes a run.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.config import settings
from backend.observability.tracing import redact_attributes

logger = logging.getLogger(__name__)


def langfuse_enabled() -> bool:
    return bool(getattr(settings, "astra_langfuse_enabled", False))


def build_langfuse_payload(name: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a sanitized payload shape suitable for a future Langfuse sink."""
    return {
        "name": str(name or ""),
        "attributes": redact_attributes(attributes or {}),
    }


def emit_langfuse_event(name: str, attributes: dict[str, Any] | None = None) -> bool:
    """Best-effort compatibility hook.

    Returns True only if Langfuse is enabled and an emit was attempted
    successfully. Disabled/default deployments simply return False so callers
    can fire-and-forget without branching.
    """
    if not langfuse_enabled():
        return False
    try:
        # Intentionally no hard dependency on the Langfuse SDK yet. This is the
        # contract surface the benchmarked integration can plug into later.
        payload = build_langfuse_payload(name, attributes)
        logger.info("langfuse hook invoked", extra={"langfuse_event": payload})
        return True
    except Exception:
        logger.warning("langfuse hook failed", exc_info=True)
        return False

"""Shared readiness check primitives.

Readiness modules historically expose plain dictionaries. This module keeps that
wire shape while giving new checks one small registered primitive to share.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Union


CheckFn = Callable[[], Union[dict[str, Any], "ReadinessCheck"]]

_REGISTRY: dict[str, CheckFn] = {}


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    ok: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    status: str | None = None

    def to_dict(self, *, include_empty_missing: bool = False, include_status: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "ok": bool(self.ok),
            "message": self.message,
            "details": dict(self.details),
        }
        if include_empty_missing or self.missing:
            payload["missing"] = list(self.missing)
        if include_status and self.status is not None:
            payload["status"] = self.status
        return payload


def make_check(
    key: str,
    ok: bool,
    message: str = "",
    details: dict[str, Any] | None = None,
    *,
    missing: list[str] | None = None,
    status: str | None = None,
    include_empty_missing: bool = False,
    include_status: bool = False,
) -> dict[str, Any]:
    """Return the canonical check dict while preserving caller-selected fields."""
    return ReadinessCheck(
        key=key,
        ok=ok,
        message=message,
        details=details or {},
        missing=missing or [],
        status=status,
    ).to_dict(include_empty_missing=include_empty_missing, include_status=include_status)


def registered_check(key: str) -> Callable[[CheckFn], CheckFn]:
    """Register a zero-argument check function under a stable key."""
    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY[key] = fn
        return fn

    return decorator


def run_registered_checks(keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Run registered checks in requested or registration order."""
    selected = list(keys) if keys is not None else list(_REGISTRY)
    checks: list[dict[str, Any]] = []
    for key in selected:
        fn = _REGISTRY[key]
        result = fn()
        if isinstance(result, ReadinessCheck):
            checks.append(result.to_dict())
        else:
            checks.append(result)
    return checks

"""Shared argument coercion utilities for agent-callable tools.

LLMs sometimes serialise list/dict args as JSON strings instead of real
Python objects.  These helpers normalise them so tools never crash with
a confusing iteration error on individual characters.
"""
from __future__ import annotations

import json


def parse_list_arg(value: object, param_name: str = "value") -> list | None:
    """Return a list from value, or None on failure.

    Handles:
    - already a list → returned as-is
    - JSON string  → parsed
    - Python-literal string → ast.literal_eval
    - None / empty string → None  (caller should return an error)
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        try:
            import ast
            parsed = ast.literal_eval(v)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        except Exception:
            pass
    return None


def parse_dict_arg(value: object) -> dict | None:
    """Return a dict from value, or None on failure."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        try:
            import ast
            parsed = ast.literal_eval(v)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None

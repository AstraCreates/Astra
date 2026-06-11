"""Resilient JSON extraction from LLM output.

LLMs emit JSON wrapped in prose/markdown and frequently TRUNCATE large objects
at the token limit. A naive `re.search(r"\\{.*\\}")` + json.loads then returns
{} on truncation (silent data loss) or, with a non-greedy regex, a nested leaf
fragment (wrong object). This helper recovers the intended object: direct parse
→ outermost span → brace-repair for truncation → prefer a key-bearing candidate.

Mirrors backend/core/agent.py:_parse_json (the agent loop has its own copy with
action/tool specifics); keep behaviour in sync.
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any

_NESTED = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def extract_json(raw: str, prefer_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    """Best-effort dict from a (possibly truncated/prose-wrapped) LLM response.

    prefer_keys: when multiple objects are found, return the first one containing
    any of these keys (e.g. ("title", "action")) instead of an arbitrary fragment.
    Returns {} only when nothing parseable is found.
    """
    if not raw:
        return {}
    s = raw.strip()
    # Strip ```json fences.
    if "```" in s:
        fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if fence:
            s = fence.group(1).strip()

    # 1) direct
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except Exception:
        pass

    start, end = s.find("{"), s.rfind("}")
    # 2) outermost { ... }
    if start != -1 and end > start:
        blob = s[start:end + 1]
        try:
            v = json.loads(blob)
            if isinstance(v, dict):
                return v
        except Exception:
            pass
        try:
            v = ast.literal_eval(blob)
            if isinstance(v, dict):
                return v
        except Exception:
            pass

    # 3) repair truncation — drop a dangling tail, then balance braces/brackets
    if start != -1:
        frag = s[start:].rstrip()
        # Strip an incomplete trailing token so the balance is parseable:
        #  - dangling key with no value:   ..."workstream":
        #  - dangling key + partial value: ..."x": "unterminat
        #  - trailing comma
        frag = re.sub(r',?\s*"[^"]*"\s*:\s*("[^"]*)?$', "", frag)
        frag = frag.rstrip().rstrip(",")
        opens = frag.count("{") - frag.count("}")
        obrk = frag.count("[") - frag.count("]")
        if opens > 0 or obrk > 0:
            repaired = frag + "]" * max(0, obrk) + "}" * max(0, opens)
            try:
                v = json.loads(repaired)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass

    # 4) candidate blobs — prefer one carrying a wanted key
    candidates: list[dict] = []
    for m in _NESTED.finditer(s):
        d = None
        try:
            d = json.loads(m.group())
        except Exception:
            try:
                r = ast.literal_eval(m.group())
                d = r if isinstance(r, dict) else None
            except Exception:
                d = None
        if isinstance(d, dict):
            if prefer_keys and any(k in d for k in prefer_keys):
                return d
            candidates.append(d)

    return candidates[0] if candidates else {}

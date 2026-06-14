"""Deep verification gates — the layer that makes agent output *real*, not just present.

`artifact_verification.verify_task_artifacts` only answers "is there text and is it
long enough." That is shallow: an agent can ship a landing page that does not load, a
legal doc full of invented clauses, or marketing built on hallucinated research and
still "pass."

This module climbs a verification ladder per agent and returns a single verdict the
orchestrator acts on (retry / block / pass):

  L1 shape       — the result actually contains the typed fields this agent must produce
                   (a web agent must produce a real URL; research must produce specifics).
  L2 executable  — for artifacts that can be run, run them: fetch the deploy URL and
                   assert it loads and is not a fallback/error page.
  L3 semantic    — an LLM judge reads the artifact against an agent-specific rubric and
                   returns concrete issues, not a thumbs-up.

The returned verdict is a superset of the deterministic base verdict, so existing
consumers (`_completion_failures`, stack_lane_status events) keep working. It adds:
  - failed_checks:     list[str]  human-readable failures across all levels
  - correction_prompt: str        ready to feed back to the agent for self-correction
  - levels:            dict        per-level detail for debugging / UI
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# Async callable that takes OpenAI-style messages and returns the raw model string.
LLMCall = Callable[[list[dict]], Awaitable[str]]

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)

_WEB_FALLBACK_MARKERS = (
    "astra-fallback-template",
    "--bg: #06080f",
    "--bg2: #0d1117",
    "define your goal",
    "astra builds it",
)

# Generic filler the semantic layer should never accept as "done".
_FILLER = (
    "lorem ipsum", "placeholder", "coming soon", "tbd", "to be determined",
    "insert ", "your company", "example.com", "[company]", "{{", "xxx",
)

# --- Data-driven artifact-kind inference -------------------------------------
# There is no fixed roster of agents or stacks: founders define their own agents
# and stacks, each with arbitrary artifact keys (github_repo, privacy_policy_pdf,
# er_diagram, ...). So the PRIMARY shape check is derived from the deliverable key
# itself, not the agent name. The per-agent table below is an optional refinement
# for the built-in specialists.
_URL_KIND_HINTS = (
    "url", "link", "site", "website", "deploy", "repo", "github", "domain",
    "landing_page", "live", "preview", "hosted", "endpoint",
)
_DOC_KIND_HINTS = (
    "pdf", "policy", "agreement", "memo", "report", "deck", "doc", "brief",
    "plan", "guide", "checklist", "playbook", "model", "outline", "strategy",
    "schema", "diagram", "roadmap", "sheet", "table", "calendar", "spec",
    "sequence", "playbook", "analysis", "comps", "benchmark",
)


def _infer_kind(key: str, title: str = "") -> str:
    """Classify a deliverable from its key/title: 'url' (must be a working link),
    'doc' (substantial document), or 'text' (substantial prose)."""
    # Tokenize so substrings don't false-match (e.g. "repo" inside "compliance_report").
    tokens = set(re.split(r"[^a-z0-9]+", f"{key} {title}".lower()))
    if tokens & set(_URL_KIND_HINTS):
        return "url"
    if tokens & set(_DOC_KIND_HINTS):
        return "doc"
    return "text"


# Generic rubric applied to ANY agent (built-in or founder-defined) that has no
# specialized rubric. Keeps the semantic judge active for every agent and stack.
_DEFAULT_RUBRIC = (
    "Output must be REAL, specific, usable work that fully completes the task: concrete "
    "details, real names/numbers where relevant, and no placeholders, no generic filler, "
    "and no fabricated or unsupported claims. Reject anything that only looks plausible."
)

# Per-agent shape contract (refinement for built-in specialists). Each agent may satisfy:
#   url_fields      — at least one must hold a real http(s) URL (when listed)
#   text_fields     — at least one must hold substantial concrete prose
#   min_text_chars  — threshold for "substantial"
#   min_specifics   — minimum count of concrete signals (numbers, proper nouns) for
#                     research-style deliverables; 0 disables the check
_AGENT_SHAPE: dict[str, dict[str, Any]] = {
    "research":  {"text_fields": ["findings", "report", "key_findings", "summary", "output_summary", "formatted_text"], "min_text_chars": 400, "min_specifics": 4},
    "web":       {"url_fields": ["deploy_url", "url", "preview_url", "live_url"], "html_fields": ["html"], "min_text_chars": 0, "min_specifics": 0},
    "technical": {"url_fields": ["repo_url", "deploy_url", "url"], "text_fields": ["summary", "report"], "min_text_chars": 120, "min_specifics": 0},
    "legal":     {"text_fields": ["document", "documents", "report", "formatted_text", "summary", "markdown"], "min_text_chars": 600, "min_specifics": 0},
    "marketing": {"text_fields": ["content", "campaign", "posts", "report", "formatted_text", "summary"], "min_text_chars": 300, "min_specifics": 0},
    "ops":       {"text_fields": ["report", "summary", "formatted_text", "output_summary"], "min_text_chars": 300, "min_specifics": 2},
    "sales":     {"text_fields": ["leads", "report", "summary", "outreach", "formatted_text"], "min_text_chars": 200, "min_specifics": 2},
    "design":    {"text_fields": ["spec", "report", "summary", "palette", "formatted_text"], "min_text_chars": 200, "min_specifics": 0},
}

# Rubric the LLM judge applies, per agent. Keep concrete and falsifiable.
_AGENT_RUBRIC: dict[str, str] = {
    "research": "Findings must be SPECIFIC: named competitors, real market sizes/numbers, concrete trends. Reject vague generalities, hedging, or claims with no evidence.",
    "legal": "Document must be a complete, coherent legal document with real clauses appropriate to its type. Reject invented citations, missing essential sections, or boilerplate that does not fit the company.",
    "marketing": "Content must be concrete, on-brand, and grounded in the research/product — real hooks and copy, not generic templates. Reject claims unsupported by upstream research.",
    "technical": "Output must describe a genuinely working MVP: real repo and deploy targets, actual features implemented. Reject scaffolding-only or TODO-laden output.",
    "ops": "Documents must contain real, usable specifics (numbers, names, steps). Reject generic filler.",
    "sales": "Leads/outreach must be concrete and plausibly real, personalized, and grounded in the product. Reject obviously fabricated or generic blasts.",
    "design": "Specs must be concrete and implementable: real tokens, layouts, states. Reject vague mood-board prose.",
    "web": "Copy and structure must be specific to the product with real sections and concrete value props. Reject template/placeholder copy.",
}


def _evidence(result: Any, fields: list[str]) -> str:
    """First non-empty field value, stringified."""
    if not isinstance(result, dict):
        return str(result or "").strip()
    for f in fields:
        v = result.get(f)
        if v:
            return v if isinstance(v, str) else str(v)
    return ""


def _full_text(result: Any) -> str:
    """Everything stringy in the result, for the semantic judge."""
    if isinstance(result, dict):
        parts = [str(v) for k, v in result.items()
                 if k not in ("artifacts_produced", "status", "agent") and v]
        return "\n".join(parts)
    return str(result or "")


def _count_specifics(text: str) -> int:
    """Concrete signals: standalone numbers + Capitalized proper-noun-ish tokens."""
    nums = len(re.findall(r"\b\d[\d,.%$]*\b", text))
    propers = len(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text))
    return nums + min(propers, 20)


def _is_web_fallback(html: str) -> bool:
    h = html.lower()
    return any(m in h for m in _WEB_FALLBACK_MARKERS)


def _check_deliverable_shape(deliverables: list[dict], result: Any) -> list[str]:
    """L1 generic — derive checks from each declared deliverable's key/title. Works
    for ANY agent or stack (built-in or founder-defined). Empty == pass."""
    fails: list[str] = []
    body = _full_text(result)
    has_url = bool(_URL_RE.search(body))
    for d in deliverables:
        if not d.get("required", True):
            continue
        key = str(d.get("artifact_key") or d.get("key") or "")
        title = str(d.get("title") or "")
        if not key:
            continue
        kind = _infer_kind(key, title)
        if kind == "url":
            # The deliverable promises a working link somewhere in the result.
            if not has_url:
                fails.append(
                    f"Deliverable '{key}' must include a real working URL/link, but none "
                    "was found in the output. Produce the actual hosted/deployed link."
                )
        else:  # doc / text
            ev = _evidence(result, [key]) or ""
            # Fall back to whole-body length when the artifact isn't its own field.
            length = len(ev.strip()) or len(body.strip())
            need = 600 if kind == "doc" else 200
            if length < need:
                fails.append(
                    f"Deliverable '{key}' is too thin ({length} chars; need ~{need}+). "
                    "Provide substantial, concrete content."
                )
    return fails


def _check_shape(agent_name: str, result: Any) -> list[str]:
    """L1 — per-agent refinement for built-in specialists. Empty == pass."""
    spec = _AGENT_SHAPE.get(agent_name)
    if not spec:
        # No built-in spec: still run the universal filler guard.
        low = _full_text(result).lower()
        hit = [f for f in _FILLER if f in low]
        if hit:
            return [f"Contains placeholder/filler text ({', '.join(hit[:3])}). Replace with real content."]
        return []
    fails: list[str] = []

    url_fields = spec.get("url_fields") or []
    if url_fields:
        url_val = _evidence(result, url_fields)
        if not _URL_RE.search(url_val or ""):
            fails.append(
                f"No real URL found. You must produce a working link in one of: "
                f"{', '.join(url_fields)} (got: {url_val[:80] or 'nothing'!r})."
            )

    html_fields = spec.get("html_fields") or []
    if html_fields:
        html_val = _evidence(result, html_fields)
        if html_val and _is_web_fallback(html_val):
            fails.append(
                "HTML is the generic fallback template. Regenerate real, product-specific "
                "HTML with concrete copy and brand styling — do not return the placeholder."
            )

    text_fields = spec.get("text_fields") or []
    min_chars = int(spec.get("min_text_chars") or 0)
    if text_fields and min_chars:
        text_val = _evidence(result, text_fields)
        if len((text_val or "").strip()) < min_chars:
            fails.append(
                f"Output too thin ({len(text_val or '')} chars; need ~{min_chars}+). "
                f"Provide substantial, concrete content in one of: {', '.join(text_fields)}."
            )

    min_specifics = int(spec.get("min_specifics") or 0)
    if min_specifics:
        body = _full_text(result)
        if _count_specifics(body) < min_specifics:
            fails.append(
                f"Output is too generic — needs at least {min_specifics} concrete specifics "
                "(real numbers, named entities, dates). Replace vague statements with facts."
            )

    # Universal filler guard.
    low = _full_text(result).lower()
    hit = [f for f in _FILLER if f in low]
    if hit:
        fails.append(f"Contains placeholder/filler text ({', '.join(hit[:3])}). Replace with real content.")

    return fails


def extract_live_url(result: Any) -> str:
    """Pull a deploy/live URL out of a result dict, or '' if none. Public so the
    monitoring layer and the shareable proof page can reuse the same extraction."""
    if not isinstance(result, dict):
        return ""
    preferred = ("deploy_url", "live_url", "preview_url", "url", "hosted_url", "site_url")
    for f in preferred:
        v = result.get(f)
        if isinstance(v, str) and _URL_RE.search(v):
            return _URL_RE.search(v).group(0)
    for k, v in result.items():
        if any(h in str(k).lower() for h in ("url", "site", "deploy", "live", "hosted")) and isinstance(v, str):
            m = _URL_RE.search(v)
            if m:
                return m.group(0)
    return ""


async def probe_live_url(url: str) -> dict:
    """Fetch a URL and report whether it is genuinely live. Returns evidence:
    {url, ok, status, bytes, fallback, error}. Never raises. Reused by L2, the
    monitoring scheduler, and the live proof page."""
    ev = {"url": url, "ok": False, "status": None, "bytes": 0, "fallback": False, "error": ""}
    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url)
        body = resp.text or ""
        ev["status"] = resp.status_code
        ev["bytes"] = len(body)
        ev["fallback"] = _is_web_fallback(body)
        ev["ok"] = resp.status_code < 400 and len(body) >= 500 and not ev["fallback"]
    except Exception as exc:  # network/DNS/timeout == not actually live
        ev["error"] = str(exc)
    return ev


def _count_sources(result: Any) -> int:
    """Count citation-like signals (links + 'Source:'/'[n]' markers) for receipts."""
    body = _full_text(result)
    urls = len(set(_URL_RE.findall(body)))
    markers = len(re.findall(r"(?i)\bsource[s]?\s*[:\-]|\[\d+\]|\bcitation", body))
    return urls + markers


async def _check_executable(agent_name: str, result: Any) -> tuple[list[str], dict]:
    """L2 — for ANY agent that produced a deploy/live URL, actually fetch it and
    confirm it loads. Returns (failures, evidence). Agent-agnostic."""
    url = extract_live_url(result)
    if not url:
        return [], {}  # no live artifact promised; nothing to execute
    ev = await probe_live_url(url)
    if ev["ok"]:
        return [], ev
    if ev["error"]:
        return [f"Could not reach deployed site {url}: {ev['error']}. The deploy is not live."], ev
    if ev["status"] is not None and ev["status"] >= 400:
        return [f"Deployed site {url} returned HTTP {ev['status']} — the deploy is broken. Fix and redeploy."], ev
    if ev["fallback"]:
        return [f"Deployed site {url} is still the fallback template. Deploy the real product page."], ev
    return [f"Deployed site {url} loaded but is nearly empty ({ev['bytes']} bytes). It is not a real page."], ev


async def _check_semantic(agent_name: str, task: dict, result: Any, llm_call: Optional[LLMCall]) -> list[str]:
    """L3 — LLM judge against an agent-specific rubric. Best-effort; never raises."""
    if llm_call is None:
        return []
    # Every agent gets judged: specialized rubric if known, generic rubric otherwise.
    rubric = _AGENT_RUBRIC.get(agent_name) or _DEFAULT_RUBRIC
    body = _full_text(result)[:8000]
    if not body.strip():
        return ["Result is empty — nothing to evaluate."]
    instruction = str(task.get("instruction") or "")[:1200]
    system = (
        "You are a strict quality reviewer for an AI startup-building system. "
        "Judge whether the agent's output is REAL, USABLE work — not plausible-looking filler. "
        "Be skeptical. Output ONLY JSON: "
        '{"verdict": "pass" | "fail", "issues": ["specific problem", ...]}. '
        "If it passes, issues must be []. If it fails, list concrete, actionable problems."
    )
    user = (
        f"AGENT: {agent_name}\n"
        f"RUBRIC: {rubric}\n\n"
        f"TASK GIVEN TO AGENT:\n{instruction}\n\n"
        f"AGENT OUTPUT:\n{body}\n\n"
        "Judge it now. Output only the JSON."
    )
    try:
        raw = await llm_call([{"role": "system", "content": system}, {"role": "user", "content": user}])
    except Exception as exc:
        logger.warning("Semantic judge call failed for %s: %s", agent_name, exc)
        return []
    parsed = _parse_judge(raw)
    if parsed is None:
        return []
    if parsed.get("verdict") == "fail":
        issues = [str(i) for i in (parsed.get("issues") or []) if str(i).strip()]
        return issues or ["Failed semantic review (no specifics returned)."]
    return []


def _parse_judge(raw: str) -> Optional[dict]:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _build_correction_prompt(failed_checks: list[str]) -> str:
    if not failed_checks:
        return ""
    bullets = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(failed_checks))
    return (
        "Your previous output FAILED verification. Fix every issue below and regenerate "
        "the full deliverable — do not just describe the fixes, produce the corrected output:\n"
        f"{bullets}\n"
    )


async def run_deep_verification(
    *,
    agent_name: str,
    task: dict,
    result: Any,
    base_verdict: dict,
    llm_call: Optional[LLMCall] = None,
) -> dict:
    """Climb the ladder, merge with the deterministic base verdict, return one verdict.

    Status precedence (worst wins): blocked > needs_review > passed.
      - L1 shape / L2 executable failures are hard → blocked (retry-worthy, must fix).
      - L3 semantic failures are soft → needs_review (retry-worthy, quality bar).
      - The deterministic base verdict's blocked/needs_review is preserved.
    """
    verdict = dict(base_verdict or {})
    verdict.setdefault("status", "passed")

    # Deliverables drive the generic, stack-agnostic shape check. Prefer the rich
    # artifact list the base verdict already built (has titles); fall back to the
    # task's expected_artifacts keys.
    deliverables = [
        {"artifact_key": a.get("artifact_key"), "title": a.get("title"), "required": a.get("required", True)}
        for a in (verdict.get("artifacts") or [])
        if a.get("artifact_key")
    ]
    if not deliverables:
        deliverables = [{"artifact_key": k, "title": "", "required": True}
                        for k in (task.get("expected_artifacts") or [])]

    shape_fails = _check_deliverable_shape(deliverables, result) + _check_shape(agent_name, result)
    # De-dupe while preserving order (built-in + generic checks can overlap).
    seen: set[str] = set()
    shape_fails = [f for f in shape_fails if not (f in seen or seen.add(f))]
    exec_fails, exec_evidence = await _check_executable(agent_name, result)
    semantic_fails = await _check_semantic(agent_name, task, result, llm_call)

    hard_fails = shape_fails + exec_fails  # must-fix
    soft_fails = semantic_fails            # quality bar

    # Carry over base-verdict failures as text so the correction prompt is complete.
    base_missing = [f"Missing required artifact: {k}" for k in (verdict.get("required_missing") or [])]
    base_weak = [f"Weak required artifact: {k}" for k in (verdict.get("required_weak") or [])]

    all_failed = base_missing + hard_fails + soft_fails + base_weak

    status = verdict.get("status", "passed")
    if base_missing or hard_fails:
        status = "blocked"
    elif (base_weak or soft_fails) and status != "blocked":
        status = "needs_review"

    verdict["status"] = status
    verdict["failed_checks"] = all_failed
    verdict["correction_prompt"] = _build_correction_prompt(all_failed)
    verdict["levels"] = {
        "shape": shape_fails,
        "executable": exec_fails,
        "semantic": semantic_fails,
    }
    # Structured evidence powers the Receipts UI ("fetched 200, cites 14 sources").
    verdict["evidence"] = {
        "shape": {"passed": not shape_fails, "issues": shape_fails},
        "executable": exec_evidence,  # {url,ok,status,bytes,fallback,error} or {}
        "semantic": {"passed": not semantic_fails, "issues": semantic_fails,
                     "sources_count": _count_sources(result)},
    }
    if all_failed and not verdict.get("summary", "").strip():
        verdict["summary"] = "; ".join(all_failed[:3])
    return verdict

"""
Base agent. Local-first LLM via OpenAI-compatible endpoint (MLX/ollama).
Each agent has: identity, tools, memory, P2P messaging, optional computer use.
"""
import asyncio
import difflib
import hashlib
import inspect
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import openai

from backend.config import settings
from backend.core.llm_cache import cacheable_messages, is_openrouter_base_url, openrouter_extra_body
from backend.runtime.budget import RunBudget
from backend.runtime.context_compressor import AstraContextCompressor
from backend.runtime.manifests import SpecialistManifest
from backend.runtime.tool_guardrails import ToolCallGuardrailController
from backend.runtime.tool_guardrails import READ_ONLY_TOOLS
from backend.runtime.tool_registry import ToolEntry, registry as runtime_tool_registry
from backend.runtime.tool_registry import schema_from_callable
from backend.runtime.model_catalog import capabilities_for
from backend.runtime.rollout import enabled as runtime_feature_enabled
from backend.runtime.metrics import increment as runtime_metric
from backend.stacks.verification_gates import _FILLER as _OUTPUT_FILLER

logger = logging.getLogger(__name__)

# Confirmed fast in real production traffic (ledger-timestamp measurement:
# ~4s/call average during a live multi-agent burst). A hang past this timeout
# is abnormal for these models specifically — fail/retry sooner instead of
# the generous 300s default sized for slower/unverified models.
_FAST_MODELS = {"inclusionai/ling-2.6-flash", "xiaomi/mimo-v2.5"}
_FAST_MODEL_TIMEOUT = 90.0

_headroom_tuned = False


def _tune_headroom_pipeline_once() -> None:
    """headroom's default ContentRouterConfig.protect_recent_reads_fraction is
    0.0 ("protect ALL excluded-tool outputs") — not exposed via the public
    compress() kwargs API. Real production data (156 sessions) showed this
    capped real savings at ~10-20% regardless of target_ratio/protect_recent
    tuning, because short agent-loop conversations fall entirely inside the
    always-protected window (verified empirically, not guessed — see commit
    history). Opens a fraction of the conversation (settings.
    headroom_protect_recent_reads_fraction, tunable — a real 2026-07-10
    incident showed 0.3 was too CPU/memory-heavy for this box) to
    compression once it exceeds 4 messages, leaving the rest — including
    all active recent turns — untouched.

    Reaches past compress()'s public wrapper into its private pipeline
    singleton — not a supported integration point, so this is gated behind
    settings.headroom_tuning_enabled (env: HEADROOM_TUNING_ENABLED, defaults
    False — see the field's docstring for the real 2026-07-10 incident this
    default is protecting against) as a kill switch, and any failure
    (headroom-ai internals changed) silently no-ops rather than breaking the
    agent loop. Runs once per process."""
    global _headroom_tuned
    if _headroom_tuned:
        return
    _headroom_tuned = True
    if not getattr(settings, "headroom_tuning_enabled", True):
        logger.info("headroom: pipeline tuning disabled via settings.headroom_tuning_enabled")
        return
    try:
        import importlib
        # `import headroom.compress as X` would bind X via attribute lookup
        # on the `headroom` package (`headroom.compress`), not the module
        # directly — headroom/__init__.py does `from .compress import
        # compress`, which overwrites that same attribute with the function.
        # importlib.import_module bypasses the shadowed attribute and returns
        # the real submodule from sys.modules. (Confirmed via a real
        # production incident: the naive `import ... as` form silently
        # bound to the function, and the outer try/except swallowed the
        # resulting AttributeError — the tuning was a no-op for a period
        # despite logging no error. importlib_module_name is asserted below
        # so that specific failure mode can never recur silently again.)
        _hr_mod = importlib.import_module("headroom.compress")
        assert hasattr(_hr_mod, "_get_pipeline"), (
            "headroom.compress resolved to something other than the real module "
            f"({type(_hr_mod)!r}) — likely the import-shadowing bug again"
        )
        from headroom.transforms.pipeline import TransformPipeline
        from headroom.transforms.content_router import ContentRouter, ContentRouterConfig

        fraction = getattr(settings, "headroom_protect_recent_reads_fraction", 0.1)
        base_pipeline = _hr_mod._get_pipeline()
        # Real production bug: SmartCrusher's default ccr_enabled=True replaces large/
        # opaque tool-result blobs with a retrievable `<<ccr:HASH,type,size>>` marker
        # instead of compressing them away — meant to be resolved later via headroom's
        # CCR retrieval tool (proxy + tool-injection + response-handler stack). We only
        # call the plain compress() entrypoint, never wire up that retrieval stack, so
        # nothing ever resolves these markers. When a model echoes one verbatim (it
        # looks like real prior content in its own context), the raw `<<ccr:...>>`
        # token leaks straight into obsidian_log/done-output/UI (observed 2026-07-10:
        # "<<ccr:82a7f5eaa57c,string,323B>>" shown as a research agent's finished
        # summary). Disable marker injection — SmartCrusher still does its other
        # (JSON/array restructuring, dedup) compression, it just won't leave behind a
        # reference nothing in our stack can ever resolve.
        router_cfg = ContentRouterConfig(protect_recent_reads_fraction=fraction, ccr_enabled=False)
        tuned_transforms = [
            ContentRouter(config=router_cfg) if isinstance(t, ContentRouter) else t
            for t in base_pipeline.transforms
        ]
        if not any(isinstance(t, ContentRouter) for t in tuned_transforms):
            logger.warning("headroom: no ContentRouter found in default pipeline — tuning skipped")
            return
        _hr_mod._pipeline = TransformPipeline(transforms=tuned_transforms)
        logger.info("headroom: tuned protect_recent_reads_fraction=%.2f (default was 0.0)", fraction)
    except Exception as exc:
        logger.warning("headroom pipeline tuning skipped: %s", exc)


# Quality gates — module-level so they're never re-allocated per run
_REQUIRED_BY_AGENT: dict[str, set[str]] = {
    "research":              {"run_research_pipeline", "deep_research"},
    "r_market":              {"run_research_pipeline", "deep_research"},
    "r_competitors":         {"run_research_pipeline", "deep_research"},
    "r_customers":           {"deep_research"},
    "r_gtm":                 {"deep_research"},
    "research_competitors":  {"run_research_pipeline", "deep_research"},
    "research_customers":    {"deep_research"},
    "research_gtm":          {"deep_research"},
    "legal":             {"format_legal_document", "generate_pdf"},
    "legal_docs":        {"format_legal_document", "generate_pdf"},
    "legal_ip":          {"format_legal_document", "generate_pdf", "patent_search"},
    "legal_entity":      {"file_llc_live", "format_legal_document", "generate_pdf", "obsidian_log"},
    "sales":             {"find_leads", "build_outreach_sequence", "build_crm_contact"},
    "sales_pipeline":    {"web_search", "generate_pdf", "obsidian_log"},
    "design":            {"generate_design_spec", "generate_wireframe", "generate_logo_brief"},
    "sales_enablement":  {"generate_pdf", "obsidian_log"},
    "marketing_content": {"generate_reel_package", "generate_tiktok_package", "generate_meta_ad", "generate_pdf", "obsidian_log"},
    "marketing_outreach":{"search_and_fetch", "build_outreach_sequence", "obsidian_log"},
    "marketing_seo":     {"web_search", "generate_pdf", "obsidian_log"},
    "marketing_paid":    {"web_search", "search_and_fetch", "generate_meta_ad", "generate_pdf", "obsidian_log"},
    "web":               {"github_create_repo", "run_mvp_loop", "obsidian_log"},
    "technical":         {"run_mvp_loop", "obsidian_log"},
    "technical_infra":   {"web_search", "generate_pdf", "obsidian_log"},
    "technical_data":    {"generate_pdf", "obsidian_log"},
    "finance_model":     {"generate_pdf", "obsidian_log"},
    "finance_fundraise": {"search_and_fetch", "format_legal_document", "generate_pdf", "obsidian_log"},
    "ops":               {"generate_pdf", "obsidian_log"},
}
_MIN_CALLS_BY_AGENT: dict[str, int] = {
    "research": 3, "r_market": 3, "r_competitors": 2,
    "r_customers": 2, "r_gtm": 2,
    "research_competitors": 2, "research_customers": 2, "research_gtm": 2,
    "sales": 3, "marketing_outreach": 3,
    "legal": 2, "legal_docs": 2, "legal_ip": 2, "legal_entity": 2,
    "design": 3, "marketing_content": 3,
    "finance_fundraise": 2,
}
_RESEARCH_AGENT_NAMES = {
    "research", "research_competitors", "research_customers", "research_gtm",
    "research_market", "research_financial", "research_regulatory", "research_execution",
}


def _normalized_tool_names(tool_names: set[str]) -> set[str]:
    """Compare completion/tool-cap requirements against canonical tool names."""
    return {_tool_cap_name(tool_name) for tool_name in tool_names}


def _latest_research_pipeline_ready(tool_results: list[tuple[str, dict[str, Any]]]) -> bool:
    """Only a typed coverage.ready=True fast-path waives deep-research escalation.

    The research pipeline also returns human-readable `next_step` text, but that
    prose is guidance, not a contract. Keep the completion gate keyed to the
    typed coverage signal so malformed/optimistic strings cannot silently skip
    the deep-research escalation path.
    """
    for tool_name, result in reversed(tool_results):
        if tool_name != "run_research_pipeline" or not isinstance(result, dict):
            continue
        coverage = result.get("coverage")
        return isinstance(coverage, dict) and coverage.get("ready") is True
    return False


def _required_tools_for_completion(
    agent_name: str,
    tool_results: list[tuple[str, dict[str, Any]]],
) -> set[str]:
    required = set(_REQUIRED_BY_AGENT.get(agent_name, set()))
    if agent_name in _RESEARCH_AGENT_NAMES and _latest_research_pipeline_ready(tool_results):
        required.discard("deep_research")
        if agent_name in {"research_customers", "research_gtm"}:
            required.add("run_research_pipeline")
    return required


def _min_calls_for_completion(
    agent_name: str,
    tool_results: list[tuple[str, dict[str, Any]]],
) -> int:
    if agent_name in _RESEARCH_AGENT_NAMES and _latest_research_pipeline_ready(tool_results):
        return 1
    return _MIN_CALLS_BY_AGENT.get(agent_name, 1)


# Hard cap on any single tool result appended to an agent's conversation. Even
# "formatted" search results / full page text must be bounded, or a research-heavy
# agent (design, marketing) accumulates 40 iterations of multi-KB results and
# overflows the model window (observed: 489385 tokens vs 262144 limit).
# Tunable: raise ASTRA_TOOL_RESULT_CAP if agents lose needed detail.
_TOOL_RESULT_CHAR_CAP = int(os.environ.get("ASTRA_TOOL_RESULT_CAP", "40000"))
_BASE64_CONTEXT_CHAR_THRESHOLD = int(os.environ.get("ASTRA_BASE64_CONTEXT_THRESHOLD", "4000"))


# Cumulative conversation budget per agent loop. Must stay under the model window
# AND keep input cost down — long tool-heavy loops resend the whole history every
# turn, so a tighter budget directly cuts billed input tokens. Compression (90k→
# tunable) usually fires first; this is the hard backstop.
_HISTORY_CHAR_BUDGET = int(os.environ.get("ASTRA_HISTORY_CHAR_BUDGET", "300000"))  # ~75k tokens


def _trim_message_history(messages: list[dict], budget_limit: int | None = None) -> list[dict]:
    """Bound an agent's conversation so long tool-heavy loops can't overflow the
    model window. Always keep the system prompt (messages[0]) and the initial goal
    (messages[1]); drop the OLDEST middle turns first, inserting a marker so the
    model knows context was elided. Recent turns (the live working set) are kept."""
    def _clen(m: dict) -> int:
        # Count ALL content, not just str. Tool-call / tool-result messages carry
        # structured (list/dict) content; the old str-only sum ignored them, so the
        # budget never bound and conversations grew unbounded (marketing → 212k tokens).
        c = m.get("content", "")
        if isinstance(c, str):
            return len(c)
        try:
            return len(json.dumps(c, default=str))
        except Exception:
            return len(str(c))

    try:
        history_budget = budget_limit or _HISTORY_CHAR_BUDGET
        # First hard-cap any single oversized tool result (i>=2) so one giant payload
        # can't blow the window even when there are only a few messages.
        _PER_MSG_CAP = 120_000
        capped: list[dict] = []
        for i, m in enumerate(messages):
            c = m.get("content", "")
            if i >= 2 and isinstance(c, str) and len(c) > _PER_MSG_CAP:
                m = {**m, "content": c[:_PER_MSG_CAP] + f"\n…[truncated {len(c)} chars to fit context]"}
            capped.append(m)
        messages = capped
        total = sum(_clen(m) for m in messages)
        if total <= history_budget:
            return messages
        head = messages[:2]
        tail = messages[2:]
        # Drop from the front of `tail` until under budget, keeping the most recent.
        head_chars = sum(_clen(m) for m in head)
        budget = history_budget - head_chars
        kept: list[dict] = []
        running = 0
        for m in reversed(tail):
            c = _clen(m)
            if running + c > budget and kept:
                break
            kept.append(m)
            running += c
        kept.reverse()
        dropped = len(tail) - len(kept)
        if dropped <= 0:
            return messages
        marker = {"role": "user", "content": f"[... {dropped} earlier turn(s) elided to fit context; "
                                              f"key findings are recorded in Obsidian and shared context ...]"}
        return head + [marker] + kept
    except Exception:
        return messages


def _coerce_model_selector(value: Any) -> Optional[str]:
    """Coerce model-controlled action/tool selector fields to a stable string
    before using them in dict/set membership checks."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _normalize_toolish_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize common tool-call-only payloads into the agent's canonical
    {"action":"tool","tool":"...","args":{...}} shape.

    Some providers/models return bare OpenAI-style function objects like
    {"name":"build_research_queries","arguments":{...}} or nest that shape
    under `tool` / `function`. If we don't normalize early, later generic
    handling can stringify the whole dict into the tool selector and produce
    "Unknown tool '{"arguments": ...}'" style failures."""
    if not isinstance(parsed, dict):
        return parsed

    # Real production bug: this guard used to bail whenever `action` was already
    # set, on the assumption a present action means the payload is already
    # well-formed. But the model can correctly say {"action":"tool", ...} while
    # STILL nesting the actual call as an OpenAI-style {"name":...,"args":...}
    # object under "tool" instead of flat tool/args fields — e.g.
    # {"action":"tool","tool":{"name":"run_research_pipeline","args":{...}}}.
    # Bailing here left that nested dict completely unnormalized; it later got
    # json.dumps()'d wholesale into the tool selector by _coerce_model_selector,
    # producing "Unknown tool '{"args":...,"name":...}'" on every single call —
    # confirmed live in production (research lanes stuck at max_iterations_reached,
    # zero real tool calls succeeding). Only skip normalization when there's
    # nothing dict-shaped left to unwrap.
    if parsed.get("action") is not None and not isinstance(parsed.get("tool"), dict):
        return parsed

    def _coerce_args(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return {}
        return value if isinstance(value, dict) else {}

    tool_payload = parsed.get("tool")
    if isinstance(tool_payload, dict):
        name = tool_payload.get("tool") or tool_payload.get("name")
        args = _coerce_args(
            (
            tool_payload.get("args")
            or tool_payload.get("arguments")
            or tool_payload.get("parameters")
            or tool_payload.get("input")
            or {}
            )
        )
        out = dict(parsed)
        out["action"] = "tool"
        out["tool"] = name
        out["args"] = args
        return out

    function_payload = parsed.get("function")
    if isinstance(function_payload, dict):
        name = function_payload.get("name")
        args = _coerce_args(function_payload.get("arguments") or function_payload.get("args") or {})
        out = dict(parsed)
        out["action"] = "tool"
        out["tool"] = name
        out["args"] = args
        return out

    if "name" in parsed and any(key in parsed for key in ("arguments", "args", "parameters", "input")):
        out = dict(parsed)
        out["action"] = "tool"
        out["tool"] = parsed.get("name")
        out["args"] = _coerce_args(parsed.get("args") or parsed.get("arguments") or parsed.get("parameters") or parsed.get("input") or {})
        return out

    return parsed


# Aliases for tool names models commonly hallucinate → the real registered tool.
_TOOL_ALIASES = {
    "obsidian_write": "obsidian_log",
    "obsidian_save": "obsidian_log",
    "obsidian_note": "obsidian_log",
    "obsidian_create": "obsidian_log",
    "obsidian_update": "obsidian_append",
    "save_note": "obsidian_log",
    "write_note": "obsidian_log",
    # Design agents hallucinate landing/wireframe variants → the real wireframe tool.
    "generate_landing": "generate_wireframe",
    "generate_landing_page": "generate_wireframe",
    "create_wireframe": "generate_wireframe",
    "generate_mockup": "generate_wireframe",
    "generate_logo_image": "generate_logo",
    "generate_brandboard": "generate_brand_board",
    "generate_brand_identity": "generate_brand_board",
    "generate_identity": "generate_brand_board",
    "generate_visual_identity": "generate_brand_board",
    "generate_palette": "generate_color_palette",
    "generate_colors": "generate_color_palette",
}

# Some tool names stay separately dispatchable for compatibility, but should
# share one usage budget because they route to the same expensive backend work.
_TOOL_CAP_ALIASES = {
    "sonar_research": "deep_research",
}


def _tool_cap_name(tool_name: str) -> str:
    return _TOOL_CAP_ALIASES.get(tool_name, tool_name)

# Generic verbs shared by many tool names — ignore them when token-matching so the
# distinctive part of the name drives the match (e.g. "brand identity" → brand_board).
_GENERIC_TOOL_TOKENS = {"generate", "create", "make", "get", "run", "build", "do", "new", "the", "a", "tool"}
_DEFAULT_TOOL_TIMEOUT_SECONDS = 180
# Research/browser tools legitimately chain many LLM + network calls (deep_research
# fans out 9+ synthesis calls), so 180s clips them mid-work. Give them a generous
# middle tier — long enough not to truncate a real research pass, still finite.
_RESEARCH_TOOL_TIMEOUT_SECONDS = int(os.environ.get("ASTRA_RESEARCH_TOOL_TIMEOUT", "600"))
_BUILD_TOOL_TIMEOUT_SECONDS = int(os.environ.get("ASTRA_BUILD_TIMEOUT", "5400"))
_LONG_RUNNING_TOOL_TIMEOUTS = {
    "run_mvp_loop": _BUILD_TOOL_TIMEOUT_SECONDS,
    "spawn_parallel_coders": _BUILD_TOOL_TIMEOUT_SECONDS,
    "deep_research": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "run_research_pipeline": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "browser_research": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "batch_search": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "search_and_fetch": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "tiktok_research": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "youtube_research": _RESEARCH_TOOL_TIMEOUT_SECONDS,
    "news_search": _RESEARCH_TOOL_TIMEOUT_SECONDS,
}


def fuzzy_resolve_tool(name: str, tool_names) -> str | None:
    """Best-effort map a hallucinated tool name to the closest real tool for THIS
    agent. Catches the whole class (generate_brand_identity → generate_brand_board)
    without a hardcoded alias for every variant. Returns the real name or None."""
    if not name or not tool_names:
        return None
    keys = list(tool_names)
    low = {k.lower(): k for k in keys}
    n = name.lower().strip()
    if n in low:
        return low[n]

    def toks(s: str) -> set:
        out = set()
        for t in re.split(r"[^a-z0-9]+", s):
            if not t or t in _GENERIC_TOOL_TOKENS:
                continue
            out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)  # singularize: colors→color
        return out

    # 1) Distinctive-token overlap (Jaccard) — precise, drives most hallucinations.
    nt = toks(n)
    best, best_j = None, 0.0
    for lk, orig in low.items():
        ct = toks(lk)
        if not ct:
            continue
        j = len(nt & ct) / len(nt | ct)
        if j > best_j:
            best_j, best = j, orig
    if best_j >= 0.34:
        return best
    # 2) Close-match on the full string (typos / suffix swaps) at a strict cutoff so
    # near-misses like generate_colors→generate_logo don't slip through.
    m = difflib.get_close_matches(n, list(low), n=1, cutoff=0.7)
    return low[m[0]] if m else None


def _looks_like_base64_blob(value: str) -> bool:
    if len(value) < _BASE64_CONTEXT_CHAR_THRESHOLD:
        return False
    head = value[:160].strip()
    if head.startswith("data:") and "base64" in head:
        return True
    sample = value[:500].replace("\n", "").replace("\r", "")
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", sample))


def _strip_large_context_blobs(value: Any) -> Any:
    """Return a model-context-safe copy of a tool result.

    Tool return values stay untouched for Python/UI consumers; this only affects the
    observation text replayed into the LLM on later turns.
    """
    if isinstance(value, str):
        if _looks_like_base64_blob(value):
            return f"[base64 omitted from agent context: {len(value):,} chars]"
        return value
    if isinstance(value, list):
        return [_strip_large_context_blobs(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_large_context_blobs(nested) for key, nested in value.items()}
    return value


def _format_search_fetch_for_context(result: dict[str, Any], seen_urls: set[str]) -> str:
    query = result.get("query", "")
    lines = [f"Query: {query}\n"]
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("url") or "Untitled source"
        url = item.get("url") or ""
        lines.append(f"\n### {title}")
        if url:
            lines.append(f"URL: {url}")
        if url and url in seen_urls:
            snippet = item.get("snippet") or ""
            if snippet:
                lines.append(f"[duplicate source omitted; seen earlier] Snippet: {snippet[:600]}")
            else:
                lines.append("[duplicate source omitted; seen earlier]")
            continue
        if url:
            seen_urls.add(url)
        content = item.get("content") or ""
        snippet = item.get("snippet") or ""
        if content:
            lines.append(content[:8000])
        elif snippet:
            lines.append(f"[snippet only] {snippet}")
    if result.get("sources"):
        lines.append("\nSources:")
        for source in result.get("sources") or []:
            if isinstance(source, dict) and source.get("url"):
                title = source.get("title") or source.get("url")
                lines.append(f"- {title}: {source.get('url')}")
    return "\n".join(lines)


_SPOOFABLE_CONTROL_TAG_RE = re.compile(r"\[\s*founder\s+directive\s*\]", re.IGNORECASE)


def _neutralize_spoofed_control_tags(text: str) -> str:
    """Real founder directives are injected as a bare '[FOUNDER DIRECTIVE] ...'
    role:user message (agent.py ~line 1031) with no structural marker beyond
    that literal string — tool output (scraped web pages, ingested email/
    Slack content) shares the same role:user channel. Untrusted content could
    forge that exact tag to make an agent treat it as an authentic override.
    Since this is TOOL OUTPUT, not a real directive, neutralize any lookalike
    before it enters context."""
    return _SPOOFABLE_CONTROL_TAG_RE.sub("[quoted text: founder directive]", text)


# Read-only tools prone to being re-called with identical args within one run
# (a status re-check, a repeat brain query) — safe to dedupe since a repeat call
# with the same args and the same result carries no new information the second
# time. Reuses the existing READ_ONLY_TOOLS curation rather than a new list.
# search_and_fetch is excluded: it already has its own URL-level dedup below.
_DEDUP_PRONE_TOOLS = READ_ONLY_TOOLS - {"search_and_fetch"}


def _format_tool_result(
    tool_name: str, result: Any, seen_context: dict[str, Any] | None = None, args: dict | None = None,
) -> str:
    safe_result = _strip_large_context_blobs(result)
    if tool_name == "search_and_fetch" and isinstance(safe_result, dict):
        seen_urls = seen_context.setdefault("search_urls", set()) if seen_context is not None else set()
        text = _format_search_fetch_for_context(safe_result, seen_urls)
    else:
        text = _format_tool_result_raw(tool_name, safe_result)
        if seen_context is not None and args is not None and tool_name in _DEDUP_PRONE_TOOLS and isinstance(text, str):
            try:
                fp = hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]
                content_hash = hashlib.sha1(text.encode()).hexdigest()[:12]
                fingerprints: dict[str, str] = seen_context.setdefault("tool_fingerprints", {})
                seen_key = f"{tool_name}:{fp}"
                if fingerprints.get(seen_key) == content_hash:
                    return f"[unchanged since the last identical {tool_name} call this run]"
                fingerprints[seen_key] = content_hash
            except Exception:
                pass  # fingerprinting is a pure optimization — never let it block a real result
    if isinstance(text, str):
        text = _neutralize_spoofed_control_tags(text)
        if len(text) > _TOOL_RESULT_CHAR_CAP:
            return text[:_TOOL_RESULT_CHAR_CAP] + f"\n... (truncated, {len(text):,} chars total)"
    return text


# Hard cap on the serialized SHARED CONTEXT injected into an agent's initial user
# message. That message (messages[1]) is never trimmed by _trim_message_history — the
# head is always preserved — so if shared context alone exceeds the model window the
# very FIRST LLM call fails before any trimming can help (observed: marketing at
# 276,256 tokens vs the 262,144 limit, with 3 research results + brain + genome +
# manifests accumulated in shared). Bound it here, keeping every key visible.
_SHARED_CONTEXT_CHAR_CAP = int(os.environ.get("ASTRA_SHARED_CONTEXT_CAP", "100000"))  # ~25k tokens (was 200k)
_SHARED_VALUE_CHAR_CAP = int(os.environ.get("ASTRA_SHARED_VALUE_CAP", "16000"))  # ~4k tokens/value (was 50k)


def _render_shared_context(shared: dict, max_chars: int = _SHARED_CONTEXT_CHAR_CAP) -> str:
    """Serialize shared context for the prompt, bounded so it cannot overflow the
    model window. Under budget → full pretty JSON. Over budget → per-key rendering
    with oversized values truncated and a hard total ceiling, so every key stays
    visible to the agent while the request stays within limits."""
    try:
        full = json.dumps(shared, indent=2, default=str)
    except Exception:
        return str(shared)[:max_chars]
    if len(full) <= max_chars:
        return full
    parts: list[str] = []
    budget = max_chars
    for k, v in shared.items():
        try:
            vs = json.dumps(v, default=str)
        except Exception:
            vs = str(v)
        if len(vs) > _SHARED_VALUE_CHAR_CAP:
            vs = vs[:_SHARED_VALUE_CHAR_CAP] + f"  ... [truncated, {len(vs):,} chars total]"
        entry = f'  "{k}": {vs}'
        if len(entry) > budget:
            parts.append(f'  "{k}": "[omitted — shared-context budget exhausted]"')
            break
        budget -= len(entry)
        parts.append(entry)
    return "{\n" + ",\n".join(parts) + "\n}"


def _format_tool_result_raw(tool_name: str, result: Any) -> str:
    """
    Format tool results as readable text for LLM context.
    Raw JSON is hard for the LLM to parse — structured text is much better.
    """
    if not isinstance(result, dict):
        text = str(result)
        # HTML/large blobs: only confirm success + char count, don't dump full content
        if tool_name == "generate_landing_page_html" or (len(text) > 2000 and text.strip().startswith("<")):
            return f"HTML generated successfully ({len(text):,} chars). Pass it directly to vercel_deploy."
        return text

    # Web search — format as numbered list
    if tool_name in ("web_search", "news_search") and "formatted" in result:
        return result["formatted"]

    # Page fetcher / search_and_read — format as readable article sections
    if tool_name in ("fetch_page", "search_and_read"):
        if "results" in result:  # search_and_read
            lines = [f"Search: {result.get('query', '')}\n"]
            for r in result.get("results", []):
                lines.append(f"### {r.get('title', r.get('url', ''))}")
                lines.append(f"URL: {r.get('url', '')}")
                content = r.get("page_content") or r.get("snippet", "")
                if content:
                    lines.append(content)
                lines.append("")
            return "\n".join(lines)
        # fetch_page
        title = result.get("title", "")
        text = result.get("text", "")
        url = result.get("url", "")
        lines = []
        if title:
            lines.append(f"# {title}")
        if url:
            lines.append(f"Source: {url}")
        if text:
            lines.append(text)
        return "\n".join(lines)

    # Browser read_page
    if tool_name == "computer_use" or (isinstance(result, dict) and "body_text" in result):
        text = result.get("body_text", result.get("text", ""))
        title = result.get("title", "")
        url = result.get("url", "")
        out = []
        if title:
            out.append(f"Page: {title}")
        if url:
            out.append(f"URL: {url}")
        if text:
            out.append(text)
        return "\n".join(out) if out else json.dumps(result)

    # Obsidian tools — compact
    if tool_name in ("obsidian_log", "obsidian_read", "obsidian_append"):
        if tool_name == "obsidian_read":
            notes = result.get("notes", [])
            if not notes:
                return "No prior notes found."
            lines = [f"{len(notes)} prior session(s) found:\n"]
            for n in notes:
                lines.append(f"--- {n.get('file', '')} ---")
                lines.append(n.get("content", ""))
            return "\n".join(lines)
        return json.dumps(result)

    try:
        return json.dumps(result, indent=2)
    except Exception:
        return str(result)

@dataclass
class AgentContext:
    goal: str
    founder_id: str
    session_id: str
    shared: dict = field(default_factory=dict)
    bypass_approvals: bool = False
    task_id: str = ""
    dep_results: dict = field(default_factory=dict)
    vault_context: str = ""
    unlimited_credits: bool = False  # scale/beta plans skip credit deduction
    budget: RunBudget | None = None
    guardrails: ToolCallGuardrailController | None = None
    delegation_depth: int = 0
    parent_agent: str = ""
    parent_task_id: str = ""


class Agent:
    """
    Hierarchical + P2P capable agent.
    - Calls local LLM (MLX/ollama OpenAI-compatible endpoint)
    - Executes tools with real return values (no hallucination path)
    - Can send/receive messages to/from other agents via bus
    - Can spawn sub-agents
    - Optionally controls browser via computer_use
    """

    def __init__(
        self,
        name: str,
        role: str,
        tools: dict[str, Callable] = None,
        sub_agents: list["Agent"] = None,
        use_computer: bool = False,
        model: str = None,
        model_base_url: str = None,
        model_api_key: str = None,
        max_iterations: int = None,
        max_tool_calls: dict[str, int] | None = None,
        library_files: list[dict] = None,
        skills: list[str] | None = None,
        toolsets: list[str] | None = None,
        manifest: SpecialistManifest | None = None,
        max_cost_usd: float | None = None,
        deadline_seconds: float | None = None,
    ):
        self.name = name
        self.role = role
        self.manifest = manifest
        self.toolsets = list(toolsets or (manifest.toolsets if manifest else ()))
        self._runtime_entries: dict[str, ToolEntry] = {}
        self.tools = dict(tools or {})
        if settings.astra_tool_registry_v2:
            for tool_name, handler in self.tools.items():
                existing = runtime_tool_registry.get(tool_name)
                if existing is None:
                    existing = runtime_tool_registry.register_callable(
                        tool_name, handler, toolset="legacy", override=False,
                    )
                elif existing.handler is not handler:
                    # Another Agent instance registered a tool of the same
                    # name with a DIFFERENT callable (e.g. two specialists
                    # sharing a tool name with distinct implementations, or
                    # a custom/per-founder closure). register_callable's
                    # override=False means the shared registry keeps
                    # whichever was registered first — reusing that entry
                    # here would silently execute the WRONG handler for
                    # this agent's tool calls. Scope a fresh entry to just
                    # this agent's _runtime_entries (not written back to the
                    # shared registry) with this agent's real handler, keeping
                    # the tool-name-intrinsic classification (risk_category,
                    # mutability, schema) from the existing entry.
                    from dataclasses import replace as _dc_replace
                    existing = _dc_replace(
                        existing, handler=handler,
                        is_async=asyncio.iscoroutinefunction(handler),
                    )
                self._runtime_entries[tool_name] = existing
            resolved = runtime_tool_registry.resolve(toolsets=self.toolsets)
            self._runtime_entries.update(resolved)
            self.tools.update({name: entry.handler for name, entry in resolved.items()})
        self.sub_agents = {a.name: a for a in (sub_agents or [])}
        self.use_computer = use_computer
        self.model = model or settings.agent_model_name
        self._model_base_url = model_base_url or settings.agent_model_base_url
        self._model_api_key = model_api_key or settings.agent_model_api_key
        self._max_iterations = max_iterations or (manifest.max_iterations if manifest else None)
        self._max_tool_calls = max_tool_calls or (dict(manifest.max_tool_calls) if manifest else {})
        # Real production bug: specialists are built once and reused for every task
        # assigned to that role (see factory.py — orch.specialists is a persistent
        # dict), but max_tool_calls was enforced against a per-run() counter that
        # resets to empty on every agent.run(ctx) call. When the orchestrator invokes
        # the SAME agent+session more than once for one task (observed 2026-07-10:
        # research_competitors got 3 separate agent_start/agent_done cycles for one
        # task, each resetting the counter — cap of 3 run_research_pipeline calls
        # became 9 real calls, ~2M tokens on one session), the cap only ever bounded
        # a single invocation, not the session. Key counts by session_id so they
        # persist across repeat invocations of this same agent within one session,
        # while staying isolated across different sessions (this Agent instance is
        # shared platform-wide, not per-session).
        self._session_tool_counts: dict[str, dict[str, int]] = {}
        self._max_cost_usd = max_cost_usd if max_cost_usd is not None else (manifest.max_cost_usd if manifest else None)
        self._deadline_seconds = deadline_seconds
        self._library_files: list[dict] = library_files or []
        self._skills: list[str] = skills or []
        self._llm: Optional[openai.OpenAI] = None

    def _get_llm(self) -> openai.OpenAI:
        legacy_client = getattr(self, "_client", None)
        if legacy_client is not None:
            return legacy_client
        is_openrouter = self._model_base_url and "openrouter" in self._model_base_url
        if is_openrouter:
            from backend.core.llm_client import get_or_client
            from backend.core.key_rotator import get_openrouter_key

            # Rotate key on every new acquisition to distribute across all keys;
            # the pooled getter reuses the client for whichever key was selected.
            api_key = get_openrouter_key() or self._model_api_key
            self._llm = get_or_client(
                base_url=self._model_base_url,
                api_key=api_key,
                timeout=None,
            )
            return self._llm
        if self._llm is None:
            self._llm = openai.OpenAI(
                base_url=self._model_base_url,
                api_key=self._model_api_key,
            )
        return self._llm

    def _call_llm(self, messages: list[dict], ctx: "AgentContext | None" = None) -> str:
        import time as _time
        is_openrouter = is_openrouter_base_url(self._model_base_url)
        # Inject cache_control on stable message prefixes for OpenRouter models.
        # OpenRouter uses Anthropic-style per-block markers; models that don't support
        # caching ignore it. We mark two breakpoints:
        #   [0] system prompt  — never changes within a run (or across runs for same agent)
        #   [1] initial user   — goal + shared context, stable for the entire agent loop
        # MiMo: $0.14→$0.0028/M on cache hit (50x cheaper). hy3/ling also benefit.
        try:
            _tune_headroom_pipeline_once()
            from headroom import compress as _hr_compress
            # gpt-4o: tiktoken compat (model name only affects token counting, not compression logic)
            _hr = _hr_compress(messages, model="gpt-4o", model_limit=128000, compress_user_messages=True)
            if _hr.tokens_saved and _hr.tokens_saved > 0:
                logger.debug("%s headroom: saved %d tokens (%.0f%%)", self.name,
                             _hr.tokens_saved, (_hr.compression_ratio or 0) * 100)
                if ctx and ctx.session_id:
                    from backend.core.session_store import add_headroom_savings
                    add_headroom_savings(ctx.session_id, _hr.tokens_saved, _hr.tokens_before)
            messages = _hr.messages
        except Exception as _hr_err:
            logger.debug("%s headroom compress skipped: %s", self.name, _hr_err)
        if is_openrouter and messages:
            messages = cacheable_messages(messages)
        # Cap the per-call output. The agent loop only ever emits a small JSON action
        # (tool call / done), so a few thousand tokens is plenty. WITHOUT a cap, reasoning
        # models like hy3-preview run to their 65536-token default and, hitting the
        # timeout, retry up to 5× → a single stuck iteration burns a long time (this is
        # exactly why the design agent "took ages"). The cap bounds worst-case latency.
        # Real production ling-2.6-flash calls average ~4s (measured from ledger
        # timestamps during a live multi-agent burst) — a hang past _FAST_MODEL_TIMEOUT
        # is unambiguously abnormal for these models, so fail/retry sooner instead of
        # eating a 300s wait per stuck attempt. Slower/unverified models keep the
        # original generous timeout as a safety net.
        _call_timeout = _FAST_MODEL_TIMEOUT if self.model in _FAST_MODELS else 300.0
        kwargs: dict = dict(
            model=self.model,
            messages=messages,
            temperature=0.1,
            timeout=_call_timeout,
            max_tokens=int(os.environ.get("ASTRA_AGENT_MAX_TOKENS", "8192")),
        )
        extra_body = openrouter_extra_body(self.model) if is_openrouter else None
        if extra_body:
            kwargs["extra_body"] = extra_body
        native_enabled = bool(
            ctx and runtime_feature_enabled("native_tool_calls", ctx.founder_id)
            and capabilities_for(self.model).native_tool_calls
        )
        if native_enabled and self.tools:
            if self._runtime_entries:
                kwargs["tools"] = runtime_tool_registry.definitions(self._runtime_entries)
            else:
                kwargs["tools"] = [
                    {"type": "function", "function": schema_from_callable(name, fn)}
                    for name, fn in self.tools.items()
                ]
            kwargs["tool_choice"] = "auto"
        # json_object not supported by OpenRouter models
        if not is_openrouter and not native_enabled:
            kwargs["response_format"] = {"type": "json_object"}
        # Budget reservation (Wave 1): reserve a generous worst-case estimate
        # BEFORE the call fires, commit real usage after. Soft-fail by design
        # -- a reservation problem must never block or crash a live agent
        # call, exactly like the existing post-hoc deduct_credits() below
        # already tolerates insufficient-credits failures. Skipped entirely
        # for unlimited-credit contexts (matches the existing bypass) and
        # when ctx is missing (some test/tool-probe call sites construct
        # Agent without one).
        _reservation = None
        if ctx and not ctx.unlimited_credits:
            try:
                from backend.control_plane.budget import BudgetExceededError, get_default_budget_service
                from backend.core.usage import _cost_usd as _est_cost_usd

                # Completion is hard-capped by max_tokens; prompt is estimated
                # generously (chars/3, erring high) since we don't have an
                # exact tokenizer count pre-call. commit() below caps billing
                # at whichever is smaller -- underestimating here only risks
                # under-billing a rare pathological call, never blocking or
                # over-billing a normal one.
                _est_prompt_tokens = max(256, sum(len(str(m.get("content", ""))) for m in messages) // 3)
                _est_completion_tokens = int(kwargs.get("max_tokens") or 8192)
                _est_usd = _est_cost_usd(self.model, _est_prompt_tokens, _est_completion_tokens) * 1.5
                _reservation = get_default_budget_service().reserve(
                    run_id=ctx.session_id, founder_id=ctx.founder_id, estimated_max_usd=_est_usd,
                )
            except BudgetExceededError as _bee:
                logger.warning("[%s] budget reservation exceeded, proceeding without one (soft-fail): %s", self.name, _bee)
            except Exception as _re:
                logger.debug("[%s] budget reservation skipped: %s", self.name, _re)

        # Rate-limit/transient resilience: retry with key rotation + backoff.
        # On 429 we rotate to the next OpenRouter key; on 5xx/timeout we just
        # back off. Honors a Retry-After header when the provider sends one.
        import openai as _openai
        import random as _random
        import json as _json
        _max_attempts = 5
        _t0 = _time.monotonic()
        resp = None
        for _attempt in range(_max_attempts):
            try:
                resp = self._get_llm().chat.completions.create(**kwargs)
                # Some providers return a 200 with choices=None on an internal error
                # (e.g. rate limit, 'json mode not supported'). Treat as transient and
                # retry instead of crashing on resp.choices[0] later.
                if getattr(resp, "choices", None):
                    break
                if _attempt < _max_attempts - 1:
                    logger.warning("%s LLM returned no choices (attempt %d/%d) — rotating key + retry",
                                   self.name, _attempt + 1, _max_attempts)
                    self._llm = None
                    _time.sleep(min(2.0 * (2 ** _attempt), 20.0))
                    continue
                break
            except Exception as _e:
                _status = getattr(_e, "status_code", None)
                _is_rate = isinstance(_e, _openai.RateLimitError) or _status == 429
                # A malformed/truncated HTTP body (provider returned non-JSON, partial
                # JSON, or an HTML error page) surfaces as JSONDecodeError / APIError with
                # no status code. That is a transient provider glitch, not a fatal bug —
                # retrying usually succeeds. Without this, one bad response killed the
                # entire run (every downstream agent orphaned).
                # The OpenAI SDK itself raises raw TypeError/KeyError/IndexError while
                # parsing a malformed/empty provider body (e.g. hy3-preview returns a
                # response with no `choices`, and `_process_response` subscripts None →
                # 'NoneType' object is not subscriptable). Treat those as a transient
                # bad body and retry rather than letting them kill the agent.
                _is_badbody = isinstance(_e, (_json.JSONDecodeError, _openai.APIResponseValidationError, TypeError, KeyError, IndexError)) or (
                    isinstance(_e, _openai.APIError) and _status is None
                )
                _is_transient = (
                    isinstance(_e, (_openai.APITimeoutError, _openai.APIConnectionError))
                    or (isinstance(_status, int) and _status >= 500)
                    or _is_badbody
                )
                if not (_is_rate or _is_transient):
                    raise
                if _attempt == _max_attempts - 1:
                    # Exhausted retries on a flaky provider — return empty so the agent
                    # loop handles it (re-prompt / finish) instead of crashing the run.
                    logger.warning("%s LLM call failed after %d attempts (%s) — returning empty",
                                   self.name, _max_attempts, type(_e).__name__)
                    fallback = settings.astra_fallback_model
                    if fallback and fallback != self.model:
                        try:
                            fallback_kwargs = {**kwargs, "model": fallback}
                            resp = self._get_llm().chat.completions.create(**fallback_kwargs)
                            if getattr(resp, "choices", None):
                                runtime_metric("model_fallback_success_total")
                                break
                        except Exception:
                            runtime_metric("model_fallback_failure_total")
                    if _reservation is not None:
                        # Early exit from inside the retry loop -- bypasses the
                        # post-loop release-on-failure check below entirely.
                        # Must release here too, or a total-failure call whose
                        # fallback also fails leaks its reservation until TTL.
                        try:
                            from backend.control_plane.budget import get_default_budget_service
                            get_default_budget_service().release(_reservation.id)
                        except Exception:
                            pass
                    return ""
                # Prefer the provider's Retry-After; else exponential backoff + jitter.
                _retry_after = None
                _r = getattr(_e, "response", None)
                if _r is not None:
                    try:
                        _retry_after = float(_r.headers.get("retry-after"))
                    except Exception:
                        _retry_after = None
                _base = 2.0 if _is_rate else 1.0
                _delay = _retry_after if _retry_after else _base * (2 ** _attempt) + _random.uniform(0, 0.5)
                _delay = min(_delay, 30.0)
                logger.warning(
                    "%s LLM call attempt %d/%d failed (%s status=%s); %s retry in %.1fs",
                    self.name, _attempt + 1, _max_attempts, type(_e).__name__, _status,
                    "rotating key," if _is_rate else "", _delay,
                )
                # Force a fresh client so OpenRouter rotates to the next key.
                self._llm = None
                _time.sleep(_delay)
        _elapsed = _time.monotonic() - _t0
        # Track token usage and deduct credits per call
        if resp and getattr(resp, "usage", None) and ctx:
            from backend.core.usage import record_usage
            from backend.core.usage import _cost_usd
            cached = getattr(resp.usage, "prompt_tokens_details", None)
            def _usage_int(value) -> int:
                return int(value) if isinstance(value, (int, float)) else 0

            cached_tokens = _usage_int(getattr(cached, "cached_tokens", 0) if cached else 0)
            prompt_t = _usage_int(getattr(resp.usage, "prompt_tokens", 0))
            completion_t = _usage_int(getattr(resp.usage, "completion_tokens", 0))
            record_usage(ctx.session_id, self.model, prompt_t, completion_t, cached_tokens=cached_tokens)
            if ctx.budget:
                ctx.budget.record_usage(
                    tokens=prompt_t + completion_t,
                    cost_usd=_cost_usd(self.model, prompt_t, completion_t, cached_tokens),
                )
            # Emit model stats event (model name + tk/s) for UI display
            try:
                from backend.core.events import publish_sync
                tks = round(completion_t / _elapsed, 1) if _elapsed > 0 else 0
                publish_sync(ctx.session_id, {
                    "type": "model_stats",
                    "agent": self.name,
                    "model": self.model,
                    "tokens": prompt_t + completion_t,
                    "completion_tokens": completion_t,
                    "tks": tks,
                })
            except Exception:
                pass
            # Deduct credits = real API cost × markup (10×). Revenue scales with spend.
            if not ctx.unlimited_credits:
                try:
                    from backend.credits.store import deduct_credits
                    from backend.core.usage import cost_to_credits
                    total_t = prompt_t + completion_t
                    # Pass cached_tokens so cache hits bill at the cheaper cache rate.
                    credits = cost_to_credits(self.model, prompt_t, completion_t, cached_tokens)
                    if ctx.budget:
                        ctx.budget.record_usage(credits=credits)
                    if _reservation is not None:
                        # Reconciles against the reservation (caps billing at
                        # whichever of actual/reserved is smaller) instead of
                        # deducting directly -- deduct_credits() would double-bill,
                        # since commit() already calls the same underlying ledger.
                        from backend.control_plane.budget import get_default_budget_service
                        get_default_budget_service().commit(
                            _reservation.id,
                            actual_usd=_cost_usd(self.model, prompt_t, completion_t, cached_tokens),
                            founder_id=ctx.founder_id,
                        )
                    else:
                        deduct_credits(ctx.founder_id, credits,
                                       f"{self.name} call ({total_t:,} tokens, {self.model})", ctx.session_id)
                    # Per-session running tally (durable) so each session/goal shows its
                    # own credit spend, not just the founder-wide balance.
                    from backend.core.session_store import add_session_credits
                    add_session_credits(ctx.session_id, credits)
                except Exception as _ce:
                    logger.warning("Per-call credit deduction failed: %s", _ce)
        if _reservation is not None and not (resp and getattr(resp, "usage", None) and ctx):
            # Call never produced a usable response -- nothing was actually
            # spent against this reservation (or ctx vanished), release it
            # rather than leaving it "reserved" until TTL expiry for no reason.
            try:
                from backend.control_plane.budget import get_default_budget_service
                get_default_budget_service().release(_reservation.id)
            except Exception:
                pass
        if not resp or not getattr(resp, "choices", None):
            # Provider never returned a usable completion after all retries — return
            # empty so the agent loop handles it (re-prompt / finish) instead of crashing.
            logger.warning("%s LLM produced no choices after %d attempts — returning empty", self.name, _max_attempts)
            return ""
        msg = resp.choices[0].message
        native_calls = getattr(msg, "tool_calls", None) or []
        if native_calls:
            runtime_metric("native_tool_call_responses_total")
            calls = []
            for call in native_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except Exception:
                    arguments = {}
                calls.append({
                    "id": getattr(call, "id", ""),
                    "tool": call.function.name,
                    "args": arguments,
                })
            return json.dumps({"action": "tool_batch", "native": True, "calls": calls})
        content = msg.content or ""
        # Strip DeepSeek-R1 <think> blocks
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # Strip markdown fences
        content = re.sub(r"^```(?:json)?\s*", "", content).rstrip("```").strip()
        return content

    def _invoke_llm(self, messages: list[dict], ctx: "AgentContext | None" = None) -> str:
        """Call the active LLM hook while preserving legacy one-argument test hooks."""
        hook = self._call_llm
        if getattr(hook, "__self__", None) is self:
            return hook(messages, ctx)
        return hook(messages)

    def _parse_json(self, raw: str) -> dict:
        # Strip <tool_call>...</tool_call> XML wrappers (ling model)
        import re as _re
        tc = _re.search(r'<tool_call>\s*(.*?)\s*</tool_call>', raw, _re.DOTALL)
        if tc:
            raw = tc.group(1)
        # Strip ```json ... ``` fences only when the entire response IS a fence-wrapped
        # block. A global search destroys JSON whose string values contain code blocks
        # (e.g. run_mvp_loop goal args with embedded package.json examples).
        fence = _re.search(r'^\s*```(?:json)?\s*(.*?)```\s*$', raw, _re.DOTALL)
        if fence:
            raw = fence.group(1)

        # Strategy 1: direct parse
        try:
            return json.loads(raw)
        except Exception:
            pass

        # Strategy 2: find outermost { ... }
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            blob = raw[start:end + 1]
            try:
                return json.loads(blob)
            except Exception:
                pass
            # Strategy 2b: Python single-quote dict (hy3-preview returns these)
            try:
                import ast
                result = ast.literal_eval(blob)
                if isinstance(result, dict):
                    return result
            except Exception:
                pass

        # Strategy 2c: repair a TRUNCATED object (large done/tool outputs get cut
        # off at max_tokens → unbalanced braces). Close the open braces/brackets and
        # retry so the envelope ({"action":...}) survives even if the tail is lost.
        if start != -1:
            frag = raw[start:]
            opens = frag.count("{") - frag.count("}")
            obrk = frag.count("[") - frag.count("]")
            if opens > 0 or obrk > 0:
                repaired = frag.rstrip().rstrip(",") + "]" * max(0, obrk) + "}" * max(0, opens)
                try:
                    return json.loads(repaired)
                except Exception:
                    pass

        # Strategy 3: collect JSON-like blobs; PREFER one carrying an action/tool key
        # (don't return a nested leaf fragment like {"heading_font": ...}).
        _candidates: list[dict] = []
        for m in _re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, _re.DOTALL):
            d = None
            try:
                d = json.loads(m.group())
            except Exception:
                try:
                    import ast
                    r = ast.literal_eval(m.group())
                    d = r if isinstance(r, dict) else None
                except Exception:
                    d = None
            if isinstance(d, dict):
                if "action" in d or d.get("tool"):
                    return d
                _candidates.append(d)

        # Strategy 4: reconstruct the envelope from a truncated/garbled response by
        # pulling the action (and tool) out with regex — breaks the unknown-action
        # loop instead of returning a leaf fragment.
        am = _re.search(r'"action"\s*:\s*"([a-z_]+)"', raw)
        if am:
            out: dict = {"action": am.group(1)}
            tm = _re.search(r'"tool"\s*:\s*"([\w.-]+)"', raw)
            if tm:
                out["tool"] = tm.group(1)
            return out

        if _candidates:
            return _candidates[0]
        return {}

    def _system_prompt(self) -> str:
        import inspect
        def _sig(name, fn):
            try:
                sig = inspect.signature(fn)
                params = ", ".join(
                    pname
                    for pname, param in sig.parameters.items()
                )
                doc = (fn.__doc__ or "").split("\n")[0].strip()
                return f"  - {name}({params}): {doc}"
            except Exception:
                return f"  - {name}: {fn.__doc__ or ''}"

        tool_list = "\n".join(_sig(name, fn) for name, fn in self.tools.items())
        sub_list = "\n".join(f"  - {n}" for n in self.sub_agents)
        # Dense pipe-delimited format instead of column-aligned lines — the padding
        # spaces in the old version cost real tokens every turn (this block is
        # rebuilt into every fresh run's messages[0], never trimmed) with zero
        # information value to the model. Same commands/params/effects, ~36% fewer
        # chars.
        computer_section = (
            "\nTo control the browser:\n"
            '{"action": "computer_use", "action_detail": {"action": "<cmd>", ...params}, "reasoning": "..."}\n'
            "Commands (cmd{params}→effect):\n"
            "navigate{url}→go to URL | read_page{}→clean readable content (use after every navigate) | "
            "find_elements{}→list buttons/inputs/links with selectors | click{selector|x,y}→click | "
            "type{selector,text}→fill input | clear{selector}→clear before re-typing | "
            "key{key}→e.g. Enter/Tab/Escape | scroll{delta_y}→scroll page | "
            "scroll_to{text|selector}→scroll into view | hover{selector|x,y}→hover (reveals dropdowns) | "
            "select_option{selector,value|label}→pick from select | check{selector,checked}→tick/untick checkbox | "
            "get_text{selector}→read element text | get_attribute{selector,attribute}→get HTML attr (value/href/data-*) | "
            "extract_table{}→extract table data | eval_js{script}→run JS, return result (masked values) | "
            "wait{ms}→sleep ms | wait_for_text{text,timeout_ms}→wait for text | "
            "wait_for_url{contains,timeout_ms}→wait for URL | screenshot{}→capture (when text parsing fails) | "
            "new_tab{url}→open new tab\n"
            "After each action: result + current URL + page body text.\n"
            "STANDARD LOOP: navigate → read_page → find_elements → act → read_page to verify.\n"
            "Use find_elements before clicking — never guess selectors. "
            "Use eval_js for values not in visible text (e.g. masked API keys).\n"
        ) if self.use_computer else ""

        # Build library context block if canonical files are present
        library_section = ""
        if self._library_files:
            files_to_inject = self._library_files[:5]
            parts = ["\n\nLIBRARY CONTEXT (canonical founder documents — treat as ground truth):"]
            for f in files_to_inject:
                fname = f.get("filename", "untitled")
                dept = f.get("department", "")
                content = f.get("content", "")
                if len(content) > 20_000:
                    content = content[:20_000] + "\n... [truncated]"
                parts.append(f"\n--- {fname} [{dept}] ---\n{content}")
            library_section = "\n".join(parts)

        # Universal examples-library nudge — only for agents that have the tool. Pulling
        # a proven pattern and adapting it beats generate→review→revise loops, which is
        # where token cost compounds. Currently only technical/web prompts mention it;
        # this covers marketing/sales/research/legal/etc too.
        examples_nudge = ""
        if "search_examples" in (self.tools or {}):
            examples_nudge = (
                "\n- BEFORE producing substantial output (code, copy, templates, schemas, "
                "outlines, legal/marketing/sales docs), call search_examples(query, "
                f"agent_role='{self.name}') and adapt the closest match instead of writing "
                "from scratch. Reusing proven patterns means fewer revision rounds.\n"
            )

        # Build skills preamble — prepended before the agent role so the LLM
        # treats skill guidance as the highest-priority context.
        skills_section = ""
        if self._skills:
            skills_section = "\n---\n".join(self._skills) + "\n---\n"

        # ask_user guidance — injected only when the tool is available
        ask_user_section = ""
        if "ask_user" in self.tools:
            ask_user_section = (
                "\nASK FOUNDER (optional): If you genuinely need input from the founder to proceed "
                "— a preference, a decision, a missing credential, or the evidence suggests a materially different direction — call "
                "ask_user(session_id=<SESSION from context>, question=\"...\", options=[\"opt1\",\"opt2\"] or [], hint=\"...\", "
                "title=\"...\", context=\"why this matters\", recommendation=\"your recommended path\", severity=\"info|warning|critical\", option_details={\"Option\":\"what it means\"}). "
                "Use this for decision-grade questions: pivots, ICP changes, pricing changes, scope cuts, and other forks with real tradeoffs. "
                "Do NOT ask vague or generic questions like 'what do you want to do?'. Offer 2-4 crisp options and explain the consequence of each when possible. "
                "It blocks until they respond, so use it when the choice is consequential, not for trivia you can infer yourself.\n"
            )

        # Dashboard guidance injected only when the agent has the tool
        dashboard_section = ""
        if "dashboard_add_element" in self.tools:
            dashboard_section = (
                f"\nDASHBOARD (optional): Call dashboard_add_element ONLY if your tools returned a concrete result a founder needs to track. "
                "Hard rules:\n"
                "- ONLY tile real numbers/data from actual tool results. Never tile estimated, placeholder, or 'N/A' values.\n"
                "- ONLY tile if it answers: revenue, users, conversion, burn, churn, pipeline, or a live blocker/risk.\n"
                "- Max 2 tiles per agent. Prefer 1 tight tile over 2 vague ones.\n"
                "- Use 'metric' for single numbers (e.g. value='1,243', unit='$', label='MRR'). "
                "Use 'table' for comparisons (competitors, pricing). "
                "Use 'status_board' for live system/integration health. "
                "Use 'list' only for prioritized action items with specific next steps.\n"
                "- NEVER tile: task summaries, agent status, intermediate steps, generic 'completed' messages, "
                "things the founder already sees in the run view, or anything without a concrete value.\n"
                "- BAD: title='Market Research Done', type='markdown', content='Completed research...'\n"
                "- GOOD: title='Top Competitors', type='table', columns=['Company','Price','Users'], rows=[...real data...]\n"
                "- GOOD: title='Signups This Week', type='metric', value='47', trend='+12% vs last week', trend_up=True\n"
                f"Pass agent={self.name!r} and the current session_id. Use section= to group related tiles.\n"
            )

        return (
            skills_section +
            f"You are {self.name}, {self.role}.\n\n"
            f"TOOLS:\n{tool_list or '  (none)'}\n\n"
            f"SUB-AGENTS YOU CAN DELEGATE TO:\n{sub_list or '  (none)'}\n\n"
            + ask_user_section
            + dashboard_section
            + "RESPONSE FORMAT — YOU MUST RESPOND WITH A SINGLE JSON OBJECT ONLY. NO PROSE. NO MARKDOWN. NO EXPLANATION.\n\n"
            "Call a tool:\n"
            '{"action": "tool", "tool": "<name>", "args": {<kwargs>}, "reasoning": "<one line>"}\n\n'
            "Delegate to sub-agent:\n"
            '{"action": "delegate", "agent": "<name>", "task": "...", "reasoning": "<one line>"}\n\n'
            + computer_section +
            "Task complete:\n"
            '{"action": "done", "output": {<result>}, "reasoning": "<one line>"}\n\n'
            "RULES:\n"
            "- Output ONLY the JSON object. Nothing before it, nothing after it.\n"
            "- Never invent tool results. Only report what tools actually returned.\n"
            "- If a tool fails, try an alternative approach or search query — do NOT call done on the first failure.\n"
            "- Do NOT call done until you have gathered substantial real data and executed required tools.\n"
            "- Use exact arg names from tool descriptions.\n"
            "- Treat injected run_context_pack/current_company_goal/company_brain_context as source-of-truth context. "
            "Call Company Brain tools only when that injected context is insufficient for the current task."
            + examples_nudge
            + library_section
        )

    async def run(self, ctx: AgentContext) -> dict[str, Any]:
        if ctx.budget is None:
            ctx.budget = RunBudget(
                max_iterations=self._max_iterations or 20,
                max_cost_usd=self._max_cost_usd,
                deadline_seconds=self._deadline_seconds,
            )
        if ctx.guardrails is None and settings.astra_runtime_guardrails:
            ctx.guardrails = ToolCallGuardrailController()
        system_prompt = self._system_prompt()
        try:
            from backend.skills.store import get_skills_for_agent
            approved_skills = get_skills_for_agent(ctx.founder_id, self.name)
            contents = [
                str(skill.get("content") or "") for skill in approved_skills
                if skill.get("content") and skill.get("status", "active") == "active"
            ]
            if contents:
                system_prompt = "\n---\n".join(contents) + "\n---\n" + system_prompt
        except Exception:
            pass
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"GOAL: {ctx.goal}\n"
                f"FOUNDER_ID: {ctx.founder_id}\n"
                f"SESSION: {ctx.session_id}\n"
                f"SHARED CONTEXT: {_render_shared_context(ctx.shared)}"
            )},
        ]

        browser = None
        if self.use_computer:
            from backend.computer_use.browser import BrowserSession
            browser = BrowserSession(headless=True)  # lazy-starts on first computer_use action

        try:
            return await self._run_loop(messages, ctx, browser)
        finally:
            if browser and browser._started:
                await browser.stop()

    async def _emit(self, ctx: AgentContext, event_type: str, **kwargs) -> None:
        from backend.core.events import publish
        await publish(ctx.session_id, {"type": event_type, "agent": self.name, **kwargs})

    async def _run_loop(self, messages: list[dict], ctx: AgentContext, browser=None) -> dict[str, Any]:
        i = 0
        MAX_ITERATIONS = self._max_iterations or 20
        if self.name.startswith("research"):
            # Research tools already persist evidence externally. Keeping a
            # 75k-token rolling transcript is counterproductive: every Ling
            # call resends it, so one lane can burn hundreds of thousands of
            # input tokens before the generic 30-iteration ceiling fires.
            MAX_ITERATIONS = min(MAX_ITERATIONS, int(os.environ.get("ASTRA_RESEARCH_MAX_ITERATIONS", "16")))
            history_budget = int(os.environ.get("ASTRA_RESEARCH_HISTORY_CHAR_BUDGET", "80000"))
        else:
            history_budget = _HISTORY_CHAR_BUDGET
        compressor = AstraContextCompressor()
        # Track consecutive failures per tool to break infinite retry loops
        _tool_fail_counts: dict[str, int] = {}
        _large_results: dict[str, Any] = {}  # stores large non-dict results (HTML etc.) by tool name
        # One-shot tools: hard-blocked after first success
        _ONE_SHOT_TOOLS = {"generate_landing_page_html", "vercel_deploy", "claude_code_scaffold",
                           "obsidian_log"}
        if self.manifest:
            _ONE_SHOT_TOOLS.update(self.manifest.one_shot_tools)
        _one_shot_done: set[str] = set()
        _called_tools: set[str] = set()
        _attempted_tools: set[str] = set()  # includes failed attempts
        # Persists across repeat agent.run() invocations for this session (see
        # self._session_tool_counts docstring in __init__) — NOT a fresh dict per
        # call, so max_tool_calls caps the session total, not just one invocation.
        _tool_attempt_counts = self._session_tool_counts.setdefault(ctx.session_id, {})
        _tool_results: list[tuple[str, dict[str, Any]]] = []
        _tool_context_seen: dict[str, Any] = {}
        _consecutive_unknown = 0  # consecutive "unknown action" responses
        _invalid_action_count = 0
        _repair_attempts = 0
        _response_signatures: dict[str, int] = {}
        _pending_error_backoff = 0.0
        _error_streak = 0

        def _schedule_error_backoff(reason: str) -> None:
            nonlocal _pending_error_backoff, _error_streak
            _error_streak += 1
            base = max(0.0, float(os.environ.get("ASTRA_AGENT_ERROR_BACKOFF_SECONDS", "2")))
            _pending_error_backoff = min(base * (2 ** min(_error_streak - 1, 3)), 10.0)
            logger.warning("[%s] error backoff %.1fs after %s", self.name, _pending_error_backoff, reason)

        async def _repair_response(raw_response: str, failure: str) -> dict[str, Any] | None:
            """Use one bounded same-model pass to recover a malformed action.

            This is deliberately outside the normal path: the repair model sees
            only the bad response, the exact tool contract, and the allowed
            envelope, so it cannot turn a parser error into another long agent
            history or an open-ended research retry.
            """
            nonlocal _repair_attempts
            if _repair_attempts >= 1:
                return None
            _repair_attempts += 1
            allowed_tools = sorted(self.tools)
            tool_contracts = []
            for tool_name in allowed_tools:
                handler = self.tools[tool_name]
                try:
                    signature = str(inspect.signature(handler))
                except Exception:
                    signature = "(...)"
                description = (getattr(handler, "__doc__", "") or "").strip().splitlines()
                tool_contracts.append(f"- {tool_name}{signature}: {description[0] if description else 'no description'}")
            repair_prompt = (
                "Repair exactly one malformed Astra agent response or natural-language tool request. Return ONLY one JSON object.\n"
                "Valid actions are: tool, tool_batch, delegate, computer_use, done.\n"
                f"Current goal: {ctx.goal}\n"
                "Available tool contracts:\n"
                + "\n".join(tool_contracts) + "\n"
                "For a tool call use {\"action\":\"tool\",\"tool\":\"<exact available name>\",\"args\":{}}.\n"
                "Translate only an explicit tool request. If the response is merely commentary or the intended tool/arguments are ambiguous, return {\"action\":\"done\",\"output\":{\"status\":\"repair_ambiguous\"}}.\n"
                "Preserve the intended tool and arguments; do not invent a different task.\n"
                f"Failure: {failure}\nMalformed response:\n{raw_response[:16000]}"
            )
            try:
                repaired_raw = await asyncio.to_thread(
                    self._invoke_llm,
                    [{"role": "system", "content": "You are a strict JSON repair parser."},
                     {"role": "user", "content": repair_prompt}],
                    ctx,
                )
                repaired = _normalize_toolish_payload(self._parse_json(str(repaired_raw or "")))
                repaired_action = _coerce_model_selector(repaired.get("action"))
                repaired_tool = _coerce_model_selector(repaired.get("tool"))
                valid_actions = {"tool", "tool_batch", "delegate", "computer_use", "done"}
                if repaired_action not in valid_actions:
                    return None
                if repaired_action == "tool" and repaired_tool not in self.tools:
                    return None
                if repaired_action == "computer_use" and not self.use_computer:
                    return None
                logger.warning("[%s] repaired malformed response into action=%s tool=%s", self.name, repaired_action, repaired_tool)
                return repaired
            except Exception as exc:
                logger.warning("[%s] malformed-response repair failed: %s", self.name, exc)
                return None

        def _tool_limit_status(tool_name: str) -> tuple[str, int | None, int, int]:
            cap_key = _tool_cap_name(tool_name)
            limit = self._max_tool_calls.get(cap_key)
            attempts = _tool_attempt_counts.get(cap_key, 0)
            successes = sum(1 for tn, _ in _tool_results if _tool_cap_name(tn) == cap_key)
            return cap_key, limit, attempts, successes

        while i < MAX_ITERATIONS:
            if _pending_error_backoff:
                await asyncio.sleep(_pending_error_backoff)
                _pending_error_backoff = 0.0
            # Per-agent stop: copilot can halt THIS agent without killing the run.
            try:
                from backend.core.cancellation import is_agent_killed
                if ctx.session_id and is_agent_killed(ctx.session_id, self.name):
                    await self._emit(ctx, "agent_stopped", agent=self.name, reason="stopped_by_founder")
                    return {"status": "stopped", "agent": self.name, "reason": "stopped_by_founder"}
            except Exception:
                pass
            if ctx.budget and not ctx.budget.consume_iteration():
                snapshot = ctx.budget.snapshot()
                payload = {
                    "status": "budget_exhausted",
                    "agent": self.name,
                    "reason": snapshot.exhausted_reason or "unknown",
                    "budget": snapshot.__dict__,
                }
                await self._emit(ctx, "agent_budget_exhausted", **payload)
                return payload
            i += 1
            # Inject any founder steer messages before calling LLM
            try:
                from backend.core.events import steer_pull
                for directive in steer_pull(ctx.session_id, agent_name=self.name):
                    messages.append({"role": "user", "content": f"[FOUNDER DIRECTIVE] {directive}\nAdjust your current plan accordingly and continue."})
                    logger.info("%s received founder directive: %s", self.name, directive[:80])
                    # Tell the UI/manager the directive actually landed + is being acted on.
                    await self._emit(ctx, "steer_delivered", agent=self.name, directive=directive[:200])
            except Exception:
                pass
            if runtime_feature_enabled("context_compression_v2", ctx.founder_id) and compressor.should_compress(messages):
                await self._emit(ctx, "context_compression_started", messages=len(messages))
                try:
                    summary_override = None
                    try:
                        summary_source = compressor.summary_source(messages)
                        from backend.tools._llm import generate
                        summary_override = await asyncio.to_thread(
                            generate,
                            compressor.summary_prompt(summary_source, ctx.goal),
                            max_tokens=2500,
                            model="small",
                        )
                    except Exception:
                        runtime_metric("context_compression_llm_fallback_total")
                    messages, compression = compressor.compress(messages, summary_override=summary_override)
                    runtime_metric("context_compression_total")
                    await self._emit(ctx, "context_compression_completed", **compression)
                except Exception as exc:
                    await self._emit(ctx, "context_compression_failed", error=str(exc)[:240])
                    messages = _trim_message_history(messages, history_budget)
            else:
                messages = _trim_message_history(messages, history_budget)
            if ctx.budget:
                await self._emit(ctx, "agent_budget_update", budget=ctx.budget.snapshot().__dict__)
            # Session-wide token circuit breaker. Per-agent iteration limits do not
            # protect against several agents launching large prompts concurrently,
            # and delegated agents have their own RunBudget instances. Reserve an
            # estimate atomically before each request so the whole session shares one
            # ceiling regardless of which agent or retry path initiated the call.
            try:
                _constraint_token_limit = ((ctx.shared or {}).get("constraints") or {}).get("session_max_tokens")
                _session_token_limit = int(
                    _constraint_token_limit
                    if _constraint_token_limit is not None
                    else os.environ.get("ASTRA_SESSION_MAX_TOKENS", "750000")
                )
            except (TypeError, ValueError):
                _session_token_limit = 750000
            try:
                _request_chars = len(json.dumps(messages, default=str))
                if self.tools:
                    if self._runtime_entries:
                        _tool_defs = runtime_tool_registry.definitions(self._runtime_entries)
                    else:
                        _tool_defs = [
                            {"type": "function", "function": schema_from_callable(name, fn)}
                            for name, fn in self.tools.items()
                        ]
                    _request_chars += len(json.dumps(_tool_defs, default=str))
                _reserved_tokens = max(1000, _request_chars // 4) + min(
                    int(os.environ.get("ASTRA_AGENT_MAX_TOKENS", "8192")), 2048
                )
            except Exception:
                _reserved_tokens = 4096
            _reservation_active = False
            if _session_token_limit > 0:
                from backend.core.usage import reserve_session_tokens
                _reservation_active = reserve_session_tokens(
                    ctx.session_id, _reserved_tokens, _session_token_limit
                )
                if not _reservation_active:
                    payload = {
                        "status": "budget_exhausted",
                        "agent": self.name,
                        "reason": "session_tokens",
                        "session_max_tokens": _session_token_limit,
                    }
                    await self._emit(ctx, "agent_budget_exhausted", **payload)
                    return payload
            try:
                raw = await asyncio.to_thread(self._invoke_llm, messages, ctx)
            finally:
                if _reservation_active:
                    from backend.core.usage import release_session_tokens
                    release_session_tokens(ctx.session_id, _reserved_tokens)
            if not isinstance(raw, str):
                try:
                    raw = json.dumps(raw, default=str)
                except Exception:
                    raw = str(raw)
            parsed = self._parse_json(raw)
            if not parsed:
                # Handle plain-text "done" from models that don't follow JSON format
                raw_stripped = raw.strip().lower().strip('"\'')
                if raw_stripped in ("done", "complete", "finished"):
                    parsed = {"action": "done", "result": {}}
                else:
                    repaired = await _repair_response(raw, "response was not parseable JSON")
                    if repaired is not None:
                        parsed = repaired
                    else:
                        _schedule_error_backoff("unparseable model response")
                        logger.warning("%s iteration %d: unparseable response — raw: %r", self.name, i, raw[:300])
                        await self._emit(ctx, "agent_thinking", iteration=i, hint=raw[:80])
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({"role": "user", "content": 'Respond with valid JSON only. Example: {"action":"done","result":{}} or {"action":"tool_call","tool":"batch_search","args":{"queries":["..."]}}. No prose.'})
                        continue

            parsed = _normalize_toolish_payload(parsed)
            action = _coerce_model_selector(parsed.get("action"))
            tool_field = _coerce_model_selector(parsed.get("tool"))
            if tool_field == "done" and action in (None, "tool"):
                args = parsed.get("args") or {}
                parsed = {
                    "action": "done",
                    "output": args.get("output") or args,
                    "reasoning": args.get("summary", ""),
                }
                action = "done"
            # If action is missing but parsed has an "output" key containing a dict with "action", unwrap it
            if action is None and isinstance(parsed.get("output"), dict) and parsed["output"].get("action"):
                parsed = parsed["output"]
                action = _coerce_model_selector(parsed.get("action"))
                tool_field = _coerce_model_selector(parsed.get("tool"))
            # Model returned a bare RESULT object with no action envelope (common
            # drift: dumps {"documents":...} / {"design_spec":...} instead of
            # {"action":"done","output":{...}}). If it carries substantive content
            # (not just reasoning) and isn't a tool attempt, treat it as an implicit
            # done so the agent completes with its result instead of looping.
            if action is None and isinstance(parsed, dict) and parsed and "tool" not in parsed:
                _noise = {"reasoning", "thinking", "thought", "text", "message", "summary"}
                if any(k not in _noise for k in parsed):
                    parsed = {"action": "done", "output": parsed}
                    action = "done"
            if self.name in _RESEARCH_AGENT_NAMES and action not in (None, "done", "tool_batch"):
                signature = json.dumps(
                    {"action": action, "tool": tool_field, "args": parsed.get("args") or parsed.get("arguments") or {}},
                    sort_keys=True,
                    default=str,
                )
                _response_signatures[signature] = _response_signatures.get(signature, 0) + 1
                if _response_signatures[signature] >= 3:
                    _schedule_error_backoff("repeated identical research action")
                    logger.error("[%s] repeated identical action 3x; forcing synthesis", self.name)
                    break
            # A parsed envelope can still be semantically invalid (unknown action
            # or tool). Give the one-shot repair pass the raw response before the
            # normal retry prompt starts a potentially expensive loop.
            valid_actions = {"tool", "tool_batch", "delegate", "computer_use", "done"}
            if (
                action not in valid_actions
                or (action == "tool" and tool_field not in self.tools)
                or (action == "computer_use" and not self.use_computer)
            ):
                repaired = await _repair_response(raw, f"invalid action={action!r}, tool={tool_field!r}")
                if repaired is not None:
                    parsed = repaired
                    action = _coerce_model_selector(parsed.get("action"))
                    tool_field = _coerce_model_selector(parsed.get("tool"))
            reasoning = parsed.get("reasoning", "")
            tool_hint = tool_field or ""
            _log_hint = tool_hint or reasoning
            if not isinstance(_log_hint, str):
                _log_hint = json.dumps(_log_hint, default=str)
            logger.info("[%s] iter=%d  action=%-12s  %s", self.name, i, action, _log_hint[:80])
            messages.append({"role": "assistant", "content": raw})
            if action in ("done", "tool", "tool_batch", "delegate", "computer_use"):
                _consecutive_unknown = 0

            if action == "done":
                required_tools = _required_tools_for_completion(self.name, _tool_results)
                normalized_called_tools = _normalized_tool_names(_called_tools)
                min_calls_needed = _min_calls_for_completion(self.name, _tool_results)
                actual_calls = len(normalized_called_tools - {"obsidian_log"})
                if actual_calls < min_calls_needed:
                    messages.append({"role": "user", "content": (
                        f"You cannot call done yet. You have only made {actual_calls} distinct tool "
                        f"call(s) but this task requires at least {min_calls_needed}. "
                        "You have NOT done enough real work. Keep researching / executing."
                    )})
                    continue
                missing = sorted(required_tools - normalized_called_tools)
                # Custom agents never match the built-in names above, so they get no
                # required-tool enforcement at all — a founder who explicitly picked
                # generate_pdf when building the agent expects a file every run, but
                # the model is free to skip it (e.g. write a summary into obsidian_log
                # instead) unless something forces the call.
                if self.name not in _REQUIRED_BY_AGENT and "generate_pdf" in self.tools and "generate_pdf" not in _called_tools:
                    missing = sorted(set(missing) | {"generate_pdf"})
                if missing:
                    messages.append({"role": "user", "content": (
                        f"You cannot call done yet. Missing required tool calls: {', '.join(missing)}. "
                        "Execute those tool calls now, then call done."
                    )})
                    continue
                output = parsed.get("output", {})
                if isinstance(output, dict):
                    output = self._normalize_done_output(output, _tool_results)
                    missing_output = self._missing_required_output(output, _attempted_tools)
                    if missing_output:
                        messages.append({"role": "user", "content": (
                            "You cannot call done yet. Output is missing required fields: "
                            f"{', '.join(missing_output)}. "
                            "Call the necessary tools, then call done with a complete output payload."
                        )})
                        continue
                    # Reject placeholder/filler outputs — scan full output, not just summary
                    _output_text = json.dumps(output, default=str).lower()
                    _filler_hits = [f for f in _OUTPUT_FILLER if f in _output_text]
                    if _filler_hits and actual_calls < min_calls_needed:
                        messages.append({"role": "user", "content": (
                            f"Your output contains placeholder text ({_filler_hits[0]!r}) and no real research was done. "
                            "Search the web, gather actual data, then provide a real summary."
                        )})
                        continue
                await self._emit(ctx, "agent_done", result=output)
                logger.info("[%s] DONE — output keys: %s", self.name, list(output.keys()) if isinstance(output, dict) else type(output).__name__)
                # Auto-log to obsidian if agent never called it
                if "obsidian_log" in self.tools and "obsidian_log" not in _called_tools and ctx.founder_id and ctx.session_id:
                    try:
                        summary = output.get("summary", "") if isinstance(output, dict) else ""
                        await asyncio.to_thread(
                            self.tools["obsidian_log"],
                            agent=self.name,
                            session_id=ctx.session_id,
                            summary=summary or json.dumps(output)[:500],
                            output=output,
                            founder_id=ctx.founder_id,
                        )
                        logger.info("[%s] auto-logged done output to obsidian", self.name)
                    except Exception as oe:
                        logger.warning("[%s] obsidian auto-log failed: %s", self.name, oe)
                if runtime_feature_enabled("skill_review", ctx.founder_id) and isinstance(output, dict):
                    from backend.skills.reviewer import review_run_for_skill_proposal
                    asyncio.create_task(review_run_for_skill_proposal(
                        founder_id=ctx.founder_id, specialist=self.name,
                        session_id=ctx.session_id, goal=ctx.goal, result=output,
                    ))
                return output

            elif action == "tool_batch":
                calls = [call for call in (parsed.get("calls") or []) if isinstance(call, dict)]
                is_native = bool(parsed.get("native"))
                unique: list[dict] = []
                seen: set[tuple[str, str]] = set()
                for call in calls:
                    name = str(call.get("tool") or call.get("name") or "")
                    args = call.get("args") or call.get("arguments") or {}
                    signature = (name, json.dumps(args, sort_keys=True, default=str))
                    if name and signature not in seen:
                        seen.add(signature)
                        unique.append({"tool": name, "args": args})

                read_calls = [call for call in unique if call["tool"] in READ_ONLY_TOOLS]
                write_calls = [call for call in unique if call["tool"] not in READ_ONLY_TOOLS]

                # Reserve every call's attempt slot synchronously, before any concurrent
                # dispatch. The old code checked-then-awaited-then-incremented inside
                # execute() itself, so same-tool calls sharing one asyncio.gather() batch
                # (read_calls below) could all observe the same stale attempt count
                # before any of them incremented it, letting a batch exceed its cap.
                # This loop has no `await` in it, so it runs atomically w.r.t. the event
                # loop — no other coroutine can interleave between reservations.
                for call in unique:
                    name = call["tool"]
                    cap_key, limit, attempts, successes = _tool_limit_status(name)
                    if limit is not None and attempts >= limit:
                        call["_blocked"] = {"cap_key": cap_key, "limit": limit, "attempts": attempts, "successes": successes}
                    else:
                        _tool_attempt_counts[cap_key] = attempts + 1

                async def execute(call: dict) -> tuple[str, dict, Any]:
                    name, args = call["tool"], call["args"]
                    blocked = call.get("_blocked")
                    if blocked is not None:
                        return name, args, {
                            "error": (
                                f"BLOCKED: {name} has already been attempted {blocked['attempts']} time(s) "
                                f"({blocked['successes']} succeeded, limit={blocked['limit']}). Stop calling {name} and move on."
                            ),
                            "blocked": True,
                            "tool": name,
                            "cap_key": blocked["cap_key"],
                        }
                    await self._emit(ctx, "agent_action", action="tool", tool=name, args=args, reasoning=reasoning)
                    result = await self._execute_tool(name, args, ctx)
                    await self._emit(ctx, "agent_action_result", tool=name, result=result)
                    return name, args, result

                batch_results: list[tuple[str, dict, Any]] = []
                # (tool, json-args) -> result, keyed the same way dedup does above, so the
                # native branch below can map each ORIGINAL call id back to its executed
                # result even when two ids shared identical name+args and were deduped to
                # one execution.
                result_by_signature: dict[tuple[str, str], Any] = {}
                if read_calls:
                    read_results = await asyncio.gather(*(execute(call) for call in read_calls))
                    batch_results.extend(read_results)
                    for name, args, result in read_results:
                        result_by_signature[(name, json.dumps(args, sort_keys=True, default=str))] = result
                for call in write_calls:
                    name, args, result = await execute(call)
                    batch_results.append((name, args, result))
                    result_by_signature[(name, json.dumps(args, sort_keys=True, default=str))] = result
                for name, args, result in batch_results:
                    _attempted_tools.add(name)
                    if not (isinstance(result, dict) and result.get("error")):
                        _called_tools.add(name)
                        if isinstance(result, dict):
                            _tool_results.append((name, result))
                if any(isinstance(result, dict) and result.get("error") for _, _, result in batch_results):
                    _schedule_error_backoff("tool batch error")

                if is_native:
                    # Real native tool-calling response: emit conformant assistant(tool_calls)
                    # + tool(tool_call_id) message pairs instead of one merged role:user blob,
                    # so role-aware tooling (context compression, compression proxies) has
                    # real signal. content:"" not None — nothing downstream in this codebase
                    # (compression, logging, truncation) has ever had to handle a None content
                    # field, and "" is accepted anywhere null would be.
                    tool_calls_msg = []
                    tool_result_msgs = []
                    for call in calls:
                        name = str(call.get("tool") or call.get("name") or "")
                        args = call.get("args") or call.get("arguments") or {}
                        call_id = call.get("id") or ""
                        signature = (name, json.dumps(args, sort_keys=True, default=str))
                        result = result_by_signature.get(signature, {"error": "not executed (duplicate or invalid call)"})
                        tool_calls_msg.append({
                            "id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args, default=str)},
                        })
                        tool_result_msgs.append({
                            "role": "tool", "tool_call_id": call_id, "name": name,
                            "content": _format_tool_result(name, result, _tool_context_seen, args),
                        })
                    messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls_msg})
                    messages.extend(tool_result_msgs)
                else:
                    messages.append({
                        "role": "user",
                        "content": "\n\n".join(
                            f"Tool result ({name}):\n{_format_tool_result(name, result, _tool_context_seen, args)}"
                            for name, args, result in batch_results
                        ),
                    })

            elif action == "tool":
                tool_name = tool_field
                args = parsed.get("args", {})
                # Some models wrap args under "arguments" key instead of "args"
                if not args and "arguments" in parsed:
                    args = parsed["arguments"]
                    if isinstance(args, str):
                        try:
                            import json as _j; args = _j.loads(args)
                        except Exception:
                            args = {}
                # Also unwrap if args itself has a single "arguments" key
                if isinstance(args, dict) and list(args.keys()) == ["arguments"]:
                    args = args["arguments"] or {}
                # Hard-block repeated calls to one-shot tools
                if tool_name in _ONE_SHOT_TOOLS and tool_name in _one_shot_done:
                    messages.append({"role": "user", "content": (
                        f"BLOCKED: {tool_name} already ran successfully this session. "
                        f"You MUST NOT call it again. Call done with the results you already have."
                    )})
                    continue
                # Enforce per-tool call limits (e.g. max 3 search calls for marketing)
                # Count ALL attempts (success + failure) so retries don't bypass the cap.
                _tool_cap_key, _tool_call_limit, _tool_total_attempts, _tool_success_count = _tool_limit_status(tool_name)
                if _tool_call_limit is not None:
                    if _tool_total_attempts >= _tool_call_limit:
                        messages.append({"role": "user", "content": (
                            f"BLOCKED: {tool_name} has already been attempted {_tool_total_attempts} time(s) "
                            f"({_tool_success_count} succeeded, limit={_tool_call_limit}). You have enough research data. "
                            f"Stop calling {tool_name} and move on to content creation tools now."
                        )})
                        # Once a research lane has completed its required evidence
                        # calls, a blocked repeat is a stop signal, not another
                        # prompt-turn. Falling through to forced synthesis prevents
                        # Ling from spending the remaining budget rephrasing reads.
                        if (
                            self.name in _RESEARCH_AGENT_NAMES
                            and _required_tools_for_completion(self.name, _tool_results)
                            <= _normalized_tool_names(_called_tools)
                        ):
                            logger.info("[%s] required research evidence complete; forcing synthesis after blocked %s", self.name, tool_name)
                            break
                        continue
                # Always use the actual cached HTML — LLM may pass a truncated/regenerated version
                if tool_name == "vercel_deploy" and _large_results.get("generate_landing_page_html"):
                    args["html"] = _large_results["generate_landing_page_html"]
                    logger.debug("[%s] forced cached HTML into vercel_deploy args (%d chars)", self.name, len(args["html"]))
                await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                _attempted_tools.add(tool_name)
                _tool_attempt_counts[_tool_cap_key] = _tool_total_attempts + 1
                result = await self._execute_tool(tool_name, args, ctx)
                await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
                if "error" not in result:
                    _called_tools.add(tool_name)
                    if isinstance(result, dict):
                        _tool_results.append((tool_name, result))
                    elif isinstance(result, str) and len(result) > 2000:
                        _large_results[tool_name] = result
                if "error" in result:
                    _schedule_error_backoff(f"tool {tool_name}")
                    _tool_fail_counts[tool_name] = _tool_fail_counts.get(tool_name, 0) + 1
                    if _tool_fail_counts[tool_name] >= 3:
                        # Force the agent to give up on this tool
                        messages.append({"role": "user", "content": (
                            f"TOOL {tool_name} FAILED {_tool_fail_counts[tool_name]} TIMES IN A ROW: {json.dumps(result)}\n"
                            f"STOP trying {tool_name}. It will not work. "
                            f"Either use a different tool or call done with what you have accomplished so far. "
                            f"Do NOT call {tool_name} again."
                        )})
                    else:
                        messages.append({"role": "user", "content": (
                            f"TOOL FAILED: {json.dumps(result)}\n"
                            f"You MUST fix the arguments and retry, or call done with the error in output. "
                            f"Do NOT report this tool as successful."
                        )})
                else:
                    _error_streak = 0
                    _tool_fail_counts[tool_name] = 0  # reset on success
                    if tool_name in _ONE_SHOT_TOOLS:
                        _one_shot_done.add(tool_name)
                    content = f"Tool result ({tool_name}):\n{_format_tool_result(tool_name, result, _tool_context_seen, args)}"
                    if i >= MAX_ITERATIONS - 5:
                        content += f"\n\n[Iteration {i}/{MAX_ITERATIONS}] You are near the iteration limit. Wrap up: call obsidian_log then done unless one more tool call is critical."
                    if tool_name in _ONE_SHOT_TOOLS:
                        content += f"\n\nIMPORTANT: {tool_name} completed. Proceed to the next step — do NOT call {tool_name} again."
                    messages.append({"role": "user", "content": content})

            elif action == "delegate":
                agent_name = parsed.get("agent")
                task = parsed.get("task", "")
                await self._emit(ctx, "agent_action", action="delegate", target=agent_name, task=task, reasoning=reasoning)
                result = await self._delegate(agent_name, task, ctx)
                messages.append({"role": "user", "content": f"Sub-agent result: {json.dumps(result)}"})

            elif action == "computer_use" and browser is not None:
                detail = parsed.get("action_detail", {})
                if not detail or not detail.get("action"):
                    messages.append({"role": "user", "content": 'computer_use requires action_detail.action. Example: {"action": "navigate", "url": "https://..."}'})
                    continue
                await self._emit(ctx, "agent_action", action="computer_use", detail=detail, reasoning=reasoning)
                try:
                    result = await asyncio.wait_for(browser.execute_action(detail), timeout=60)
                    state = await asyncio.wait_for(browser.page_state(), timeout=30)
                except asyncio.TimeoutError:
                    _schedule_error_backoff("computer_use timeout")
                    messages.append({"role": "user", "content": "computer_use timed out. Proceed to done with results gathered so far."})
                    await self._emit(ctx, "agent_action_result", action="computer_use", url="", title="timeout")
                    continue
                except Exception as _cu_err:
                    _schedule_error_backoff("computer_use error")
                    messages.append({"role": "user", "content": f"computer_use failed: {_cu_err}. Proceed to done with results gathered so far."})
                    await self._emit(ctx, "agent_action_result", action="computer_use", url="", title="error")
                    continue
                await self._emit(ctx, "agent_action_result", action="computer_use", url=state.get("url"), title=state.get("title"))
                try:
                    screenshot_b64 = result.get("screenshot_b64") or (
                        # Auto-capture screenshot after navigate/click so agent sees result
                        (await asyncio.wait_for(browser.execute_action({"action": "screenshot"}), timeout=20)).get("screenshot_b64")
                        if detail.get("action") in ("navigate", "click") else None
                    )
                except Exception:
                    screenshot_b64 = None
                text_part = (
                    f"Browser result: {json.dumps({k: v for k, v in result.items() if k != 'screenshot_b64'})}\n"
                    f"URL: {state.get('url', 'unknown')}\n"
                    f"Title: {state.get('title', '')}\n"
                    f"Form fields: {json.dumps(state.get('form_fields', []))}\n"
                    f"Interactive elements: {json.dumps(state.get('interactive_elements', []))}\n"
                    f"Page text: {state.get('body_text', '')}"
                )
                if screenshot_b64:
                    messages.append({"role": "user", "content": [
                        {"type": "text", "text": text_part},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                    ]})
                else:
                    messages.append({"role": "user", "content": text_part})

            elif action == "computer_use" and browser is None:
                messages.append({"role": "user", "content": "computer_use not available. Use tool or delegate."})

            elif action in ("tool_call", "function_call", "call_tool", "use_tool") or (
                action is None and (
                    tool_field in self.tools
                    or _coerce_model_selector(parsed.get("name")) in self.tools
                )
            ):
                # Normalize: some models output {"action":"tool_call",...} or {"tool":"name","args":{}} with no action
                parsed["action"] = "tool"
                tool_name = tool_field or _coerce_model_selector(parsed.get("function")) or _coerce_model_selector(parsed.get("name"))
                args = parsed.get("args") or parsed.get("parameters") or parsed.get("input") or parsed.get("arguments") or {}
                if not args and "arguments" in parsed:
                    args = parsed["arguments"]
                    if isinstance(args, str):
                        try:
                            import json as _j; args = _j.loads(args)
                        except Exception:
                            args = {}
                if tool_name and tool_name in self.tools:
                    if tool_name in _ONE_SHOT_TOOLS and tool_name in _one_shot_done:
                        messages.append({"role": "user", "content": (
                            f"BLOCKED: {tool_name} already ran successfully this session. "
                            f"You MUST NOT call it again. Call done with the results you already have."
                        )})
                        continue
                    _tool_cap_key, _tool_call_limit, _tool_total_attempts, _tool_success_count = _tool_limit_status(tool_name)
                    if _tool_call_limit is not None:
                        if _tool_total_attempts >= _tool_call_limit:
                            messages.append({"role": "user", "content": (
                                f"BLOCKED: {tool_name} has already been attempted {_tool_total_attempts} time(s) "
                                f"({_tool_success_count} succeeded, limit={_tool_call_limit}). "
                                f"Stop calling {tool_name} and move on."
                            )})
                            continue
                    await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                    _attempted_tools.add(tool_name)
                    _tool_attempt_counts[_tool_cap_key] = _tool_total_attempts + 1
                    result = await self._execute_tool(tool_name, args, ctx)
                    await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
                    if "error" not in result:
                        _called_tools.add(tool_name)
                        if isinstance(result, dict):
                            _tool_results.append((tool_name, result))
                        if tool_name in _ONE_SHOT_TOOLS:
                            _one_shot_done.add(tool_name)
                    if "error" in result:
                        _schedule_error_backoff(f"tool {tool_name}")
                        _tool_fail_counts[tool_name] = _tool_fail_counts.get(tool_name, 0) + 1
                        if _tool_fail_counts[tool_name] >= 3:
                            messages.append({"role": "user", "content": (
                                f"TOOL {tool_name} FAILED {_tool_fail_counts[tool_name]} TIMES IN A ROW: {json.dumps(result)}\n"
                                f"STOP trying {tool_name}. Use a different tool or call done."
                            )})
                        else:
                            messages.append({"role": "user", "content": f"TOOL FAILED: {json.dumps(result)}"})
                    else:
                        _error_streak = 0
                        _tool_fail_counts[tool_name] = 0
                        messages.append({"role": "user", "content": f"Tool result ({tool_name}):\n{_format_tool_result(tool_name, result, _tool_context_seen, args)}"})
                else:
                    messages.append({"role": "user", "content": f"Unknown tool '{tool_name}'. Use: tool, delegate, computer_use, or done."})

            elif action in self.tools:
                # Model used action name directly instead of {"action":"tool","tool":"<name>"}
                tool_name = action
                # Args may be nested under "args" key or spread at top level
                if "args" in parsed and isinstance(parsed["args"], dict):
                    args = parsed["args"]
                else:
                    args = {k: v for k, v in parsed.items() if k not in ("action", "reasoning", "tool")}
                if tool_name in _ONE_SHOT_TOOLS and tool_name in _one_shot_done:
                    messages.append({"role": "user", "content": (
                        f"BLOCKED: {tool_name} already ran successfully this session. "
                        f"You MUST NOT call it again. Call done with the results you already have."
                    )})
                    continue
                _tool_cap_key, _tool_call_limit, _tool_total_attempts, _tool_success_count = _tool_limit_status(tool_name)
                if _tool_call_limit is not None:
                    if _tool_total_attempts >= _tool_call_limit:
                        messages.append({"role": "user", "content": (
                            f"BLOCKED: {tool_name} has already been attempted {_tool_total_attempts} time(s) "
                            f"({_tool_success_count} succeeded, limit={_tool_call_limit}). "
                            f"Stop calling {tool_name} and move on."
                        )})
                        continue
                await self._emit(ctx, "agent_action", action="tool", tool=tool_name, args=args, reasoning=reasoning)
                _attempted_tools.add(tool_name)
                _tool_attempt_counts[_tool_cap_key] = _tool_total_attempts + 1
                result = await self._execute_tool(tool_name, args, ctx)
                await self._emit(ctx, "agent_action_result", tool=tool_name, result=result)
                if "error" not in result:
                    _called_tools.add(tool_name)
                    if isinstance(result, dict):
                        _tool_results.append((tool_name, result))
                    if tool_name in _ONE_SHOT_TOOLS:
                        _one_shot_done.add(tool_name)
                if "error" in result:
                    _schedule_error_backoff(f"tool {tool_name}")
                    _tool_fail_counts[tool_name] = _tool_fail_counts.get(tool_name, 0) + 1
                    if _tool_fail_counts[tool_name] >= 3:
                        messages.append({"role": "user", "content": (
                            f"TOOL {tool_name} FAILED {_tool_fail_counts[tool_name]} TIMES IN A ROW: {json.dumps(result)}\n"
                            f"STOP trying {tool_name}. Use a different tool or call done."
                        )})
                    else:
                        messages.append({"role": "user", "content": f"TOOL FAILED: {json.dumps(result)}"})
                else:
                    _error_streak = 0
                    _tool_fail_counts[tool_name] = 0
                    messages.append({"role": "user", "content": f"Tool result ({tool_name}):\n{_format_tool_result(tool_name, result, _tool_context_seen, args)}"})

            else:
                _schedule_error_backoff("unknown action")
                logger.warning("[%s] iter=%d unknown action=%r parsed_keys=%s raw=%r", self.name, i, action, list(parsed.keys()), raw[:200])
                await self._emit(ctx, "agent_unknown_action", action=action, parsed_keys=list(parsed.keys()), raw_snippet=raw[:120])
                _consecutive_unknown += 1
                _invalid_action_count += 1
                invalid_limit = 3
                if _consecutive_unknown >= 3 or _invalid_action_count >= invalid_limit:
                    # Break narrative loop — force done
                    logger.error("[%s] invalid action limit reached (%d) — forcing done", self.name, _invalid_action_count)
                    break
                messages.append({"role": "user", "content": (
                    f"INVALID RESPONSE. You must output ONLY valid JSON with an 'action' key.\n"
                    f"Unknown action: {action!r}\n"
                    "Valid actions: tool, delegate, computer_use, done.\n"
                    'Example: {"action": "tool", "tool": "web_search", "input": {"query": "..."}}\n'
                    "Do NOT write prose. Respond with JSON only."
                )})

        logger.warning("%s hit MAX_ITERATIONS (%d) — forcing synthesis from gathered data", self.name, MAX_ITERATIONS)
        # Force one final synthesis call using everything gathered so far
        try:
            synthesis_seen: dict[str, Any] = {}
            gathered = "\n\n".join(
                f"[{name}]: {_format_tool_result(name, res, synthesis_seen)}" for name, res in _tool_results
            ) or "No tool results gathered."
            # Send ONLY system prompt + gathered data — NOT full history (avoids token explosion)
            synthesis_messages = [
                messages[0],  # system prompt
                {"role": "user", "content": (
                    f"GOAL: {ctx.goal}\n\n"
                    f"Research data gathered:\n{gathered}\n\n"
                    "Synthesize into a final structured response. "
                    "Respond with JSON: {\"action\": \"done\", \"output\": {\"summary\": \"...\", \"findings\": [...], \"sources\": [...]}}"
                )},
            ]
            raw = await asyncio.to_thread(self._invoke_llm, synthesis_messages, ctx)
            parsed = self._parse_json(raw)
            if parsed and parsed.get("action") == "done":
                output = parsed.get("output", {})
                output = self._normalize_done_output(output, _tool_results)
                if isinstance(output, dict):
                    # Apply same quality checks as normal done path — can't re-prompt, just flag
                    _synth_required_tools = _required_tools_for_completion(self.name, _tool_results)
                    _synth_called_tools = _normalized_tool_names(_called_tools)
                    _synth_missing_tools = sorted(_synth_required_tools - _synth_called_tools)
                    _synth_missing_output = self._missing_required_output(output, _attempted_tools)
                    _synth_min = _min_calls_for_completion(self.name, _tool_results)
                    _synth_actual = len(_synth_called_tools - {"obsidian_log"})
                    if _synth_missing_tools or _synth_missing_output or _synth_actual < _synth_min:
                        quality_flags = {
                            "missing_tools": _synth_missing_tools,
                            "missing_output": _synth_missing_output,
                            "tool_calls_made": _synth_actual,
                            "tool_calls_required": _synth_min,
                        }
                        output["status"] = "max_iterations_reached"
                        output["quality_flags"] = quality_flags
                        logger.warning("[%s] force synthesis rejected — missing_tools=%s missing_output=%s calls=%d/%d",
                                       self.name, _synth_missing_tools, _synth_missing_output, _synth_actual, _synth_min)
                        return {
                            "status": "max_iterations_reached",
                            "agent": self.name,
                            "quality_flags": quality_flags,
                            "partial_output": output,
                        }
                    else:
                        output["status"] = "partial"
                await self._emit(ctx, "agent_done", result=output)
                # Auto-write to obsidian so downstream agents can read it
                if "obsidian_log" in self.tools and ctx.founder_id and ctx.session_id:
                    try:
                        summary = output.get("summary", "") or json.dumps(output)[:500]
                        await asyncio.to_thread(
                            self.tools["obsidian_log"],
                            agent=self.name,
                            session_id=ctx.session_id,
                            summary=summary,
                            output=output,
                            founder_id=ctx.founder_id,
                        )
                        logger.info("[%s] auto-logged synthesis to obsidian", self.name)
                    except Exception as oe:
                        logger.warning("[%s] obsidian auto-log failed: %s", self.name, oe)
                if runtime_feature_enabled("skill_review", ctx.founder_id) and isinstance(output, dict):
                    from backend.skills.reviewer import review_run_for_skill_proposal
                    asyncio.create_task(review_run_for_skill_proposal(
                        founder_id=ctx.founder_id, specialist=self.name,
                        session_id=ctx.session_id, goal=ctx.goal, result=output,
                    ))
                return output
        except Exception as e:
            logger.warning("%s forced synthesis failed: %s", self.name, e)
        return {"status": "max_iterations_reached", "agent": self.name}

    def _missing_required_output(self, output: dict[str, Any], attempted_tools: set[str] | None = None) -> list[str]:
        """Require key preview artifacts per role before accepting done."""
        if self.manifest and self.manifest.output_schema:
            missing = self.manifest.missing_output_fields(output)
            if missing:
                return missing
        if self.name in ("legal", "legal_docs"):
            docs = output.get("documents")
            if not isinstance(docs, list) or not docs:
                return ["documents[]"]
            first = docs[0] if isinstance(docs[0], dict) else {}
            if not (first.get("path") or first.get("text")):
                return ["documents[0].path|text"]
            return []
        if self.name == "sales":
            missing: list[str] = []
            if not isinstance(output.get("leads"), list) or not output.get("leads"):
                missing.append("leads[]")
            if not isinstance(output.get("sequence"), list) or not output.get("sequence"):
                missing.append("sequence[]")
            if not isinstance(output.get("contacts_found"), int):
                missing.append("contacts_found (integer)")
            if not output.get("outreach_status"):
                missing.append("outreach_status")
            return missing
        if self.name == "marketing_content":
            missing: list[str] = []
            reel_scripts = output.get("reel_scripts")
            tiktok_packages = output.get("tiktok_packages")
            meta_ads = output.get("meta_ads")
            content_calendar_pdf = output.get("content_calendar_pdf")
            if not isinstance(reel_scripts, list) or len(reel_scripts) < 3:
                missing.append("reel_scripts[3]")
            if not isinstance(tiktok_packages, list) or len(tiktok_packages) < 2:
                missing.append("tiktok_packages[2]")
            if not isinstance(meta_ads, dict) or not all(meta_ads.get(key) for key in ("awareness", "consideration", "conversion")):
                missing.append("meta_ads.awareness|consideration|conversion")
            if not content_calendar_pdf:
                missing.append("content_calendar_pdf")
            return missing
        if self.name == "marketing_outreach":
            missing: list[str] = []
            if not isinstance(output.get("domains_searched"), list) or not output.get("domains_searched"):
                missing.append("domains_searched[]")
            if not isinstance(output.get("sequences"), list) or not output.get("sequences"):
                missing.append("sequences[]")
            if not isinstance(output.get("sequence"), list) or not output.get("sequence"):
                missing.append("sequence[]")
            leads = output.get("leads")
            contacts_found = output.get("contacts_found")
            if not isinstance(leads, list) or not leads:
                missing.append("leads[]")
            if not isinstance(contacts_found, int):
                missing.append("contacts_found")
            return missing
        if self.name == "design":
            missing: list[str] = []
            if not output.get("design_spec"):
                missing.append("design_spec")
            if not isinstance(output.get("wireframes"), list) or not output.get("wireframes"):
                missing.append("wireframes[]")
            if not any(
                output.get(key)
                for key in (
                    "logo_brief",
                    "color_palette",
                    "logo_wordmark",
                    "logo_icon",
                    "brand_direction",
                    "formatted_text",
                    "summary",
                    "spec",
                    "report",
                )
            ):
                missing.append("logo_brief|color_palette|brand_direction|formatted_text|summary|spec|report")
            return missing
        if self.name == "sales_enablement":
            missing: list[str] = []
            # Reject placeholder PDF paths — real generate_pdf returns actual file paths
            for key in ("pitch_deck_pdf", "one_pager_pdf", "case_studies_pdf", "battlecards_pdf"):
                val = output.get(key, "")
                if not val or "/path/to/" in str(val) or not str(val).endswith(".pdf"):
                    missing.append(key)
            if not isinstance(output.get("pitch_deck_outline"), list) or len(output.get("pitch_deck_outline", [])) < 12:
                missing.append("pitch_deck_outline (12 slides required)")
            if not isinstance(output.get("battlecards"), list) or len(output.get("battlecards", [])) < 3:
                missing.append("battlecards (3 required)")
            return missing
        if self.name == "marketing":
            missing: list[str] = []
            if not output.get("reel_package"):
                missing.append("reel_package")
            if not output.get("tiktok_package"):
                missing.append("tiktok_package")
            if not output.get("meta_ad"):
                missing.append("meta_ad")
            ad_images = output.get("ad_images")
            # Only require ad_images if generate_ad_image hasn't been attempted yet.
            # If it was attempted (even if it failed), allow done to proceed — the error
            # is already surfaced in the tool result and the agent shouldn't be blocked forever.
            image_attempted = attempted_tools and "generate_ad_image" in attempted_tools
            if not isinstance(ad_images, list) or not ad_images:
                if not image_attempted:
                    missing.append("ad_images[]")
            return missing
        if self.name == "marketing_paid":
            missing: list[str] = []
            if not output.get("pdf_path"):
                missing.append("pdf_path")
            if not isinstance(output.get("meta_ads"), list) or len(output.get("meta_ads", [])) < 2:
                missing.append("meta_ads[2+]")
            if output.get("total_budget_usd") is None:
                missing.append("total_budget_usd")
            if not output.get("channel_split"):
                missing.append("channel_split")
            return missing
        if self.name == "marketing_seo":
            return [] if (output.get("pdf_path") or output.get("pdf_url")) else ["pdf_path|pdf_url"]
        if self.name == "web":
            missing: list[str] = []
            if not output.get("repo_url"):
                missing.append("repo_url")
            if not (output.get("deploy_url") or output.get("url")):
                missing.append("deploy_url")
            if output.get("success") is not True:
                missing.append("success=True")
            if output.get("build_passes") is not True:
                missing.append("build_passes=True")
            return missing
        if self.name == "technical":
            missing: list[str] = []
            if not output.get("repo_url"):
                missing.append("repo_url")
            if not (output.get("deploy_url") or output.get("url")):
                missing.append("deploy_url")
            if output.get("success") is not True:
                missing.append("success=True")
            if output.get("build_passes") is not True:
                missing.append("build_passes=True")
            if not isinstance(output.get("files_in_repo"), int):
                missing.append("files_in_repo")
            return missing
        if self.name == "technical_infra":
            missing: list[str] = []
            if not output.get("pdf_path"):
                missing.append("pdf_path")
            if not output.get("hosting_choice"):
                missing.append("hosting_choice")
            if not output.get("github_actions_yaml"):
                missing.append("github_actions_yaml")
            return missing
        if self.name == "technical_data":
            missing: list[str] = []
            for key in ("er_diagram", "schema_sql", "analytics_events", "pdf_path"):
                if not output.get(key):
                    missing.append(key)
            return missing
        if self.name == "legal_entity":
            missing: list[str] = []
            if not output.get("entity_type"):
                missing.append("entity_type")
            docs = output.get("documents")
            if not isinstance(docs, list) or len(docs) < 3:
                missing.append("documents[3]")
            return missing
        if self.name == "legal_ip":
            missing: list[str] = []
            docs = output.get("documents")
            if not isinstance(docs, list) or len(docs) < 3:
                missing.append("documents[3]")
            if not output.get("recommended_filings"):
                missing.append("recommended_filings")
            return missing
        if self.name == "sales_pipeline":
            missing: list[str] = []
            if not isinstance(output.get("pipeline_stages"), list) or len(output.get("pipeline_stages", [])) < 5:
                missing.append("pipeline_stages[5+]")
            if not output.get("playbook_pdf"):
                missing.append("playbook_pdf")
            return missing
        if self.name == "finance_model":
            missing: list[str] = []
            if not output.get("pdf_path"):
                missing.append("pdf_path")
            if not output.get("key_assumptions"):
                missing.append("key_assumptions")
            return missing
        if self.name == "finance_fundraise":
            missing: list[str] = []
            for key in ("raise_amount", "instrument", "investor_list", "safe_terms_path", "pdf_path"):
                if not output.get(key):
                    missing.append(key)
            return missing
        if self.name == "ops":
            missing: list[str] = []
            for key in ("pdf_path", "payment_setup", "linear_issue", "notion_page"):
                if not output.get(key):
                    missing.append(key)
            return missing
        return []

    async def _execute_tool(self, tool_name: str, args: dict, ctx: AgentContext) -> Any:
        # Sanitize inputs: scan for prompt injection patterns, recurse into dicts/lists.
        # Sanitize outputs: redact credential-bearing keys before re-entering LLM context.
        # Allowlist enforcement is skipped here (stale in security.py) — guardrails handle it.
        try:
            from proprietary_agent.security import ToolSecurityLayer as _TSL
            _tsl: _TSL = getattr(self, "_security_layer", None) or _TSL()
            if not hasattr(self, "_security_layer"):
                self._security_layer = _tsl  # type: ignore[attr-defined]
            args = _tsl._sanitize_inputs(args)
        except Exception:
            pass
        fn = self.tools.get(tool_name)
        if fn is None:
            # Explicit aliases first (fast, exact), then fuzzy-match the hallucinated
            # name to the closest real tool for this agent so we route it instead of
            # erroring + relying on the model to recover.
            alias = _TOOL_ALIASES.get(tool_name)
            if alias:
                fn = self.tools.get(alias)
            if fn is None:
                resolved = fuzzy_resolve_tool(tool_name, self.tools.keys())
                if resolved:
                    logger.info("Tool '%s' not found — fuzzy-routed to '%s' (%s)", tool_name, resolved, self.name)
                    tool_name = resolved
                    fn = self.tools.get(resolved)
        if fn is None:
            # No reasonable match — list the real tools so the model picks a valid one.
            available = ", ".join(sorted(self.tools.keys()))
            await self._emit(ctx, "tool_unavailable", tool=tool_name, available=available[:1000])
            return {"error": f"Unknown tool '{tool_name}'. It does not exist — do NOT call it again. "
                             f"Use ONLY one of these tools: {available}."}
        if ctx.budget and not ctx.budget.consume_tool_call():
            snapshot = ctx.budget.snapshot()
            await self._emit(ctx, "agent_budget_exhausted", status="budget_exhausted",
                             reason=snapshot.exhausted_reason, budget=snapshot.__dict__)
            return {"error": f"Tool budget exhausted: {snapshot.exhausted_reason}"}
        guardrail_decision = None
        if ctx.guardrails:
            guardrail_decision = ctx.guardrails.before_call(tool_name, args)
            if guardrail_decision.action == "warn":
                await self._emit(ctx, "tool_guardrail_warning", tool=tool_name,
                                 code=guardrail_decision.code, message=guardrail_decision.message,
                                 count=guardrail_decision.count)
            elif not guardrail_decision.allows_execution:
                await self._emit(ctx, "tool_guardrail_blocked", tool=tool_name,
                                 code=guardrail_decision.code, message=guardrail_decision.message,
                                 count=guardrail_decision.count)
                return {"error": guardrail_decision.message, "guardrail": guardrail_decision.code}
        import time as _time
        saferun_action = None
        try:
            from backend.core.events import publish
            from backend.safety import build_saferun_action
            saferun_action = build_saferun_action(tool_name, args, self.name)
            if saferun_action:
                await publish(ctx.session_id, {
                    "type": "saferun_action",
                    "action": saferun_action,
                })
        except Exception as e:
            logger.warning("[%s] SafeRun planning failed for %s: %s", self.name, tool_name, e)
        if saferun_action and saferun_action.get("approval_required") and not ctx.bypass_approvals:
            gate_key = saferun_action.get("approval_gate")
            try:
                from backend.core.events import approval_decision_wait, publish
                from backend.approval_workflows import create_approval_request
                approval_request = create_approval_request(
                    ctx.session_id,
                    str(gate_key),
                    title=str(gate_key).replace("_", " ").title(),
                    reason=saferun_action.get("reason", ""),
                    action_id=saferun_action.get("id", ""),
                    tool=tool_name,
                    agent=self.name,
                    risk_level=saferun_action.get("risk_level", "medium"),
                )
                await publish(ctx.session_id, {
                    "type": "approval_request",
                    "request": approval_request,
                })
                await publish(ctx.session_id, {
                    "type": "saferun_result",
                    "action_id": saferun_action["id"],
                    "tool": tool_name,
                    "agent": self.name,
                    "status": "waiting_approval",
                    "result_preview": f"Waiting for founder approval gate: {gate_key}",
                    "approval_gate": gate_key,
                })
                decision = await approval_decision_wait(
                    ctx.session_id,
                    str(approval_request["id"]),
                    str(approval_request["action_digest"]),
                    timeout=300.0,
                )
                if not decision:
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error",
                        "result_preview": f"Timed out waiting for approval gate: {gate_key}",
                        "approval_gate": gate_key,
                    })
                    return {"error": f"SafeRun blocked {tool_name}: approval timed out for gate {gate_key}"}
                if decision.get("decision") != "approved":
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "skipped",
                        "result_preview": f"Founder skipped approval gate: {gate_key}",
                        "approval_gate": gate_key,
                    })
                    return {"error": f"SafeRun skipped {tool_name}: founder skipped approval gate {gate_key}"}
                await publish(ctx.session_id, {
                    "type": "saferun_result",
                    "action_id": saferun_action["id"],
                    "tool": tool_name,
                    "agent": self.name,
                    "status": "approved",
                    "result_preview": f"Founder approved gate: {gate_key}",
                    "approval_gate": gate_key,
                })
            except Exception as e:
                logger.warning("[%s] SafeRun approval wait failed for %s: %s", self.name, tool_name, e)
                return {"error": f"SafeRun approval check failed for {tool_name}: {e}"}
        # Inject required context fields that models sometimes omit
        # Unwrap common extra wrapper keys models accidentally include — some
        # models nest multiple levels deep, e.g.
        # {"args": {"arguments": {"args": {...real fields...}}}}, so this must
        # loop (not just unwrap once) and include "args" itself as a wrapper
        # name, since after unwrapping "arguments" once the leftover single
        # key is often literally "args" again.
        import inspect as _inspect
        try:
            _sig_params = set(_inspect.signature(fn).parameters.keys())
            _wrap_keys = {"args", "arguments", "tool_args", "parameters", "input", "kwargs"}
            for _ in range(5):
                if isinstance(args, dict) and len(args) == 1:
                    ((_only_key, _only_val),) = args.items()
                    if _only_key in _wrap_keys and isinstance(_only_val, dict):
                        args = _only_val
                        continue
                break
        except Exception:
            _sig_params = set()
        # Inject run context into ANY tool that declares these params, so the model
        # doesn't have to thread session/founder ids through every call (needed by
        # run_mvp_loop, spawn_parallel_coders, vision_browse, obsidian_log, …).
        if "session_id" in _sig_params:
            args.setdefault("session_id", ctx.session_id)
        if "founder_id" in _sig_params:
            args.setdefault("founder_id", ctx.founder_id)
        if "agent" in _sig_params:
            args.setdefault("agent", self.name)
        if "cancellation_fence" in _sig_params:
            from backend.core import cancellation
            args.setdefault("cancellation_fence", cancellation.cancellation_fence(ctx.session_id, self.name))
        try:
            # Strip any keys the function doesn't accept (if it doesn't use **kwargs)
            _has_var_kw = any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in _inspect.signature(fn).parameters.values())
            if _sig_params and not _has_var_kw:
                args = {k: v for k, v in args.items() if k in _sig_params}
        except Exception:
            pass
        args_preview = {k: (str(v)[:120] + "…" if isinstance(v, str) and len(str(v)) > 120 else v) for k, v in args.items()}
        logger.debug("[%s] → %s  args=%s", self.name, tool_name, args_preview)
        t0 = _time.monotonic()
        _tool_timeout = _LONG_RUNNING_TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TOOL_TIMEOUT_SECONDS)
        try:
            from backend.core import cancellation
            cancellation.check_fence(ctx.session_id, self.name)
            entry = self._runtime_entries.get(tool_name)
            if settings.astra_tool_registry_v2 and entry:
                result = await asyncio.wait_for(
                    runtime_tool_registry.dispatch(entry, args, {
                        "session_id": ctx.session_id,
                        "founder_id": ctx.founder_id,
                        "agent": self.name,
                    }),
                    timeout=_tool_timeout,
                )
            elif asyncio.iscoroutinefunction(fn):
                cancellation.check_fence(ctx.session_id, self.name)
                result = await asyncio.wait_for(fn(**args), timeout=_tool_timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(cancellation.run_sync_with_fence, ctx.session_id, self.name, fn, args),
                    timeout=_tool_timeout,
                )
            elapsed = _time.monotonic() - t0
            if ctx.guardrails:
                post = ctx.guardrails.after_call(
                    tool_name, args, result,
                    failed=isinstance(result, dict) and bool(result.get("error")),
                )
                if post.action == "warn":
                    await self._emit(ctx, "tool_guardrail_warning", tool=tool_name,
                                     code=post.code, message=post.message, count=post.count)
            # Redact credential-bearing keys before result enters LLM context
            if isinstance(result, dict):
                try:
                    result = self._security_layer.sanitize_output(tool_name, result)  # type: ignore[attr-defined]
                except Exception:
                    pass
            result_preview = str(result)[:200] if result is not None else "None"
            logger.debug("[%s] ← %s  %.1fs  result=%.200s", self.name, tool_name, elapsed, result_preview)
            if saferun_action:
                try:
                    from backend.core.events import publish
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error" if isinstance(result, dict) and result.get("error") else "executed",
                        "result_preview": result_preview,
                        "elapsed_seconds": round(elapsed, 2),
                    })
                except Exception as e:
                    logger.warning("[%s] SafeRun result emit failed for %s: %s", self.name, tool_name, e)
            return result
        except asyncio.TimeoutError:
            elapsed = _time.monotonic() - t0
            logger.error("[%s] ✗ %s  %.1fs  TimeoutError: timed out after %ss", self.name, tool_name, elapsed, _tool_timeout)
            if saferun_action:
                try:
                    from backend.core.events import publish
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error",
                        "result_preview": f"timed out after {_tool_timeout}s",
                        "elapsed_seconds": round(elapsed, 2),
                    })
                except Exception as emit_error:
                    logger.warning("[%s] SafeRun timeout emit failed for %s: %s", self.name, tool_name, emit_error)
            return {"error": f"Tool '{tool_name}' timed out after {_tool_timeout}s", "timed_out": True, "tool": tool_name}
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.error("[%s] ✗ %s  %.1fs  %s: %s", self.name, tool_name, elapsed, type(e).__name__, e)
            if saferun_action:
                try:
                    from backend.core.events import publish
                    await publish(ctx.session_id, {
                        "type": "saferun_result",
                        "action_id": saferun_action["id"],
                        "tool": tool_name,
                        "agent": self.name,
                        "status": "error",
                        "result_preview": str(e)[:240],
                        "elapsed_seconds": round(elapsed, 2),
                    })
                except Exception as emit_error:
                    logger.warning("[%s] SafeRun error emit failed for %s: %s", self.name, tool_name, emit_error)
            return {"error": str(e)}

    def _normalize_done_output(
        self,
        output: dict[str, Any],
        tool_results: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Enrich agent done payload with stable preview-friendly fields."""
        out = dict(output)
        # Universal fallback: the role-specific branches below only cover the
        # built-in stack agent names. Custom agents run under self.name ==
        # their custom_agent_id, which never matches any of them, so a real
        # generate_pdf call would otherwise vanish — surface it here first.
        if not out.get("pdf_path"):
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    path = result.get("path") or result.get("filename")
                    if path:
                        out["pdf_path"] = path
                        break
        if self.name == "marketing":
            images = []
            for tool_name, result in tool_results:
                if tool_name != "generate_ad_image":
                    continue
                url = result.get("url") or result.get("image_url")
                b64 = result.get("base64")
                if url or b64:
                    images.append({"url": url, "base64": b64, "prompt": result.get("prompt", "")})
            if images:
                out.setdefault("ad_images", images)
        elif self.name == "sales":
            leads = out.get("leads")
            sequences = out.get("sequences")
            crm_contacts = out.get("crm_contacts")
            if not isinstance(leads, list):
                leads = []
            if not isinstance(sequences, list):
                sequences = []
            if not isinstance(crm_contacts, list):
                crm_contacts = []
            for tool_name, result in tool_results:
                if tool_name == "find_leads" and isinstance(result.get("leads"), list):
                    leads.extend(result["leads"])
                elif tool_name == "build_outreach_sequence" and isinstance(result.get("sequence"), list):
                    sequences.append({"lead": result.get("lead", {}), "steps": result["sequence"]})
                elif tool_name == "build_crm_contact":
                    crm_contacts.append(result)
            if leads:
                out["leads"] = leads
            if sequences:
                out["sequences"] = sequences
                if "sequence" not in out and sequences[0].get("steps"):
                    out["sequence"] = sequences[0]["steps"]
            if crm_contacts:
                out["crm_contacts"] = crm_contacts
            if isinstance(out.get("leads"), list):
                out.setdefault("contacts_found", len(out["leads"]))
            if out.get("sequence") or out.get("sequences"):
                out.setdefault("outreach_status", "drafted")
        elif self.name == "design":
            if "design_spec" not in out or not out.get("design_spec"):
                for tool_name, result in tool_results:
                    if tool_name == "generate_design_spec":
                        out["design_spec"] = result
                        break
            if "color_palette" not in out or not out.get("color_palette"):
                for tool_name, result in tool_results:
                    if tool_name == "generate_color_palette":
                        out["color_palette"] = result
                        break
            wireframes = out.get("wireframes") if isinstance(out.get("wireframes"), list) else []
            for tool_name, result in tool_results:
                if tool_name == "generate_wireframe":
                    wireframes.append(result)
                if tool_name == "generate_logo_brief" and not out.get("logo_brief"):
                    out["logo_brief"] = result
                if tool_name == "generate_logo":
                    slot = "logo_wordmark" if result.get("style") == "wordmark" else "logo_icon"
                    if not out.get(slot):
                        out[slot] = result
                if tool_name == "generate_brand_board":
                    images = out.get("brand_images") if isinstance(out.get("brand_images"), list) else []
                    images.append(result)
                    out["brand_images"] = images
            if wireframes:
                out["wireframes"] = wireframes
            spec = out.get("design_spec") if isinstance(out.get("design_spec"), dict) else {}
            palette = out.get("color_palette") if isinstance(out.get("color_palette"), dict) else {}
            typography = spec.get("typography") or spec.get("fonts") or []
            summary_lines: list[str] = []
            if spec.get("brand_name"):
                summary_lines.append(f"Brand: {spec['brand_name']}")
            if spec.get("design_principles"):
                summary_lines.append(f"Positioning: {spec['design_principles']}")
            if typography:
                summary_lines.append(f"Typography: {typography}")
            if palette:
                palette_tokens = palette.get("palette") or palette.get("colors") or palette
                summary_lines.append(f"Palette: {palette_tokens}")
            if spec.get("components"):
                summary_lines.append(f"Components: {spec['components']}")
            if spec.get("layout_guidance"):
                summary_lines.append(f"Layout: {spec['layout_guidance']}")
            if spec.get("accessibility"):
                summary_lines.append(f"Accessibility: {spec['accessibility']}")
            if summary_lines:
                formatted = "\n".join(str(line) for line in summary_lines if line)
                out.setdefault("formatted_text", formatted)
                out.setdefault("summary", formatted[:1200])
                out.setdefault("spec", formatted)
                out.setdefault("report", formatted)
                out.setdefault("brand_direction", formatted)
                if palette and not out.get("palette"):
                    out["palette"] = palette
        elif self.name in ("legal", "legal_docs"):
            # Build docs from the tool results (these always carry real path/text) and
            # put them FIRST, then keep only model-emitted entries that actually have
            # path or text. Previously the model's raw (often malformed) documents array
            # seeded index 0, so _missing_required_output's documents[0] check failed
            # forever → legal re-generated everything each loop → 10min timeout.
            tool_docs: list[dict[str, Any]] = []
            current_doc: dict[str, Any] | None = None
            for tool_name, result in tool_results:
                if tool_name == "format_legal_document":
                    current_doc = {
                        "doc_type": result.get("doc_type"),
                        "title": result.get("doc_type", "document"),
                        "text": result.get("formatted_text", ""),
                    }
                elif tool_name == "generate_pdf":
                    if current_doc is None:
                        current_doc = {"doc_type": "document", "title": "document"}
                    current_doc["path"] = result.get("path") or result.get("filename")
                    tool_docs.append(current_doc)
                    current_doc = None
            if current_doc is not None and current_doc.get("text"):
                tool_docs.append(current_doc)
            model_docs = [
                d for d in (out.get("documents") or [])
                if isinstance(d, dict) and (d.get("path") or d.get("text"))
            ] if isinstance(out.get("documents"), list) else []
            docs = tool_docs + model_docs
            if docs:
                out["documents"] = docs
        elif self.name == "marketing_content":
            reel_scripts = out.get("reel_scripts") if isinstance(out.get("reel_scripts"), list) else []
            tiktok_packages = out.get("tiktok_packages") if isinstance(out.get("tiktok_packages"), list) else []
            meta_ads = out.get("meta_ads") if isinstance(out.get("meta_ads"), dict) else {}
            pdf_result = out.get("content_calendar_pdf")
            meta_slots = ["awareness", "consideration", "conversion"]
            meta_index = 0
            for tool_name, result in tool_results:
                if tool_name == "generate_reel_package":
                    reel_scripts.append(result)
                elif tool_name == "generate_tiktok_package":
                    tiktok_packages.append(result)
                elif tool_name == "generate_meta_ad" and meta_index < len(meta_slots):
                    meta_ads.setdefault(meta_slots[meta_index], result)
                    meta_index += 1
                elif tool_name == "generate_pdf" and not pdf_result:
                    pdf_result = result
            if reel_scripts:
                out["reel_scripts"] = reel_scripts
            if tiktok_packages:
                out["tiktok_packages"] = tiktok_packages
            if meta_ads:
                out["meta_ads"] = meta_ads
            if pdf_result:
                out["content_calendar_pdf"] = pdf_result.get("path") if isinstance(pdf_result, dict) else pdf_result
        elif self.name == "marketing_outreach":
            sequences = out.get("sequences") if isinstance(out.get("sequences"), list) else []
            leads = out.get("leads") if isinstance(out.get("leads"), list) else []
            domains = out.get("domains_searched") if isinstance(out.get("domains_searched"), list) else []
            for tool_name, result in tool_results:
                if tool_name == "search_and_fetch":
                    for item in result.get("results", []):
                        url = item.get("url", "")
                        if isinstance(url, str) and url:
                            domain = url.split("/")[2] if "://" in url else url
                            if domain and domain not in domains:
                                domains.append(domain)
                elif tool_name == "hunter_search_by_domains":
                    for contact in result.get("contacts", []) or result.get("results", []) or []:
                        if contact not in leads:
                            leads.append(contact)
                elif tool_name == "build_outreach_sequence" and isinstance(result.get("sequence"), list):
                    lead = result.get("lead") if isinstance(result.get("lead"), dict) else {}
                    if lead and lead not in leads:
                        leads.append(lead)
                    sequences.append({"lead": lead, "steps": result["sequence"]})
            if domains:
                out["domains_searched"] = domains
            if leads:
                out["leads"] = leads
                out.setdefault("contacts_found", len(leads))
            if sequences:
                out["sequences"] = sequences
                out.setdefault("sequence", sequences[0].get("steps", []))
            out.setdefault("emails_sent", 0)
        elif self.name == "marketing_paid":
            meta_ads = out.get("meta_ads") if isinstance(out.get("meta_ads"), list) else []
            pdf_path = out.get("pdf_path")
            for tool_name, result in tool_results:
                if tool_name == "generate_meta_ad":
                    meta_ads.append(result)
                elif tool_name == "generate_pdf" and not pdf_path:
                    pdf_path = result.get("path") or result.get("filename")
            if meta_ads:
                out["meta_ads"] = meta_ads
            if pdf_path:
                out["pdf_path"] = pdf_path
            if "channel_split" not in out and out.get("google_budget_usd") is not None and out.get("meta_budget_usd") is not None:
                out["channel_split"] = {
                    "google_usd": out.get("google_budget_usd"),
                    "meta_usd": out.get("meta_budget_usd"),
                }
        elif self.name in ("web", "technical"):
            for tool_name, result in tool_results:
                if tool_name == "github_create_repo" and result.get("repo_url") and not out.get("repo_url"):
                    out["repo_url"] = result.get("repo_url")
                elif tool_name == "run_mvp_loop":
                    out.setdefault("repo_url", result.get("repo_url"))
                    out.setdefault("deploy_url", result.get("deploy_url"))
                    out.setdefault("url", result.get("deploy_url"))
                    out.setdefault("files_in_repo", result.get("files_in_repo"))
                    out.setdefault("success", result.get("success"))
                    out.setdefault("build_passes", result.get("build_passes"))
                    if result.get("files_preview"):
                        out.setdefault("files_preview", result.get("files_preview"))
        elif self.name == "technical_infra":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
        elif self.name == "technical_data":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
        elif self.name == "legal_entity":
            filing = next((result for tool_name, result in tool_results if tool_name == "file_llc_live"), None)
            docs = out.get("documents") if isinstance(out.get("documents"), list) else []
            current_doc: dict[str, Any] | None = None
            for tool_name, result in tool_results:
                if tool_name == "format_legal_document":
                    current_doc = {
                        "doc_type": result.get("doc_type"),
                        "title": result.get("doc_type", "document"),
                        "text": result.get("formatted_text", ""),
                    }
                elif tool_name == "generate_pdf":
                    if current_doc is None:
                        current_doc = {"doc_type": "document", "title": "document"}
                    current_doc["path"] = result.get("path") or result.get("filename")
                    docs.append(current_doc)
                    current_doc = None
            if filing:
                out.setdefault("entity_type", filing.get("entity_type"))
                # The real filer (llc_filing.file_llc_live) returns confirmation_url;
                # only the safe-stub fallback (legal_entity._file_entity_agent_safe)
                # returns confirmation_number. A genuinely successful real filing
                # never surfaced its confirmation without this fallback.
                out.setdefault("filing_confirmation", filing.get("confirmation_number") or filing.get("confirmation_url"))
            if docs:
                out["documents"] = docs
        elif self.name == "legal_ip":
            docs = out.get("documents") if isinstance(out.get("documents"), list) else []
            current_doc: dict[str, Any] | None = None
            patent_summaries = []
            for tool_name, result in tool_results:
                if tool_name == "patent_search":
                    patent_summaries.append(result)
                elif tool_name == "format_legal_document":
                    current_doc = {
                        "doc_type": result.get("doc_type"),
                        "title": result.get("doc_type", "document"),
                        "text": result.get("formatted_text", ""),
                    }
                elif tool_name == "generate_pdf":
                    if current_doc is None:
                        current_doc = {"doc_type": "document", "title": "document"}
                    current_doc["path"] = result.get("path") or result.get("filename")
                    docs.append(current_doc)
                    current_doc = None
            if docs:
                out["documents"] = docs
            if patent_summaries and "recommended_filings" not in out:
                out["recommended_filings"] = ["Review patent search results and pursue highest-signal filings"]
        elif self.name == "sales_pipeline":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("playbook_pdf", result.get("path") or result.get("filename"))
        elif self.name == "marketing_seo":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
        elif self.name == "finance_model":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
            out.setdefault("key_assumptions", out.get("assumptions") or out.get("inputs") or {})
        elif self.name == "finance_fundraise":
            for tool_name, result in tool_results:
                if tool_name == "format_legal_document":
                    out.setdefault("safe_terms_path", result.get("path") or result.get("filename") or result.get("doc_type"))
                elif tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
        elif self.name == "ops":
            for tool_name, result in tool_results:
                if tool_name == "generate_pdf":
                    out.setdefault("pdf_path", result.get("path") or result.get("filename"))
                elif tool_name == "create_product_with_payment_link":
                    out.setdefault("payment_setup", result)
                elif tool_name == "composio_linear_create_issue":
                    out.setdefault("linear_issue", result)
                elif tool_name == "composio_notion_create_page":
                    out.setdefault("notion_page", result)
        return out

    async def _delegate(self, agent_name: str, task: str, ctx: AgentContext) -> Any:
        if runtime_feature_enabled("delegation_v2", ctx.founder_id):
            from backend.runtime.delegation import run_delegated_task
            return await run_delegated_task(
                parent=self,
                ctx=ctx,
                role=agent_name,
                task=task,
                max_iterations=20,
            )
        agent = self.sub_agents.get(agent_name)
        if agent is None:
            return {"error": f"Unknown sub-agent: {agent_name}"}
        sub_ctx = AgentContext(
            goal=task,
            founder_id=ctx.founder_id,
            session_id=ctx.session_id,
            shared=dict(ctx.shared),
            budget=ctx.budget.child(max_iterations=agent._max_iterations or 20) if ctx.budget else None,
            delegation_depth=ctx.delegation_depth + 1,
            parent_agent=self.name,
            parent_task_id=ctx.task_id,
        )
        return await agent.run(sub_ctx)

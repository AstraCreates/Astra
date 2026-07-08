"""Orchestrator-owned context and memory policy.

Agents can still use Company Brain tools, but the orchestrator should provide the
small, authoritative context pack up front and write durable outcomes back after a
run. This keeps memory use predictable and prevents agents from burning calls on
repeat searches.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any


RAW_RESULT_KEYS = {
    "sources", "results", "raw", "pages", "html", "content", "fetched",
    "documents", "search_results", "images", "logos", "image", "logo",
    "b64", "base64", "screenshot",
}
SUMMARY_KEYS = (
    "summary", "output_summary", "findings", "key_findings", "recommendations",
    "decisions", "next_actions", "blockers", "repo_url", "deploy_url", "url",
    "artifacts_produced", "documents", "crm_contacts", "leads",
)


def _env_int(name: str, default: int) -> int:
    try:
        import os
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f" ...[truncated {len(value) - limit:,} chars]"


def _jsonish(value: Any, limit: int = 4000) -> str:
    try:
        text = json.dumps(value, indent=2, default=str)
    except Exception:
        text = str(value)
    return _truncate(text, limit)


def _is_base64ish(text: str) -> bool:
    if len(text) < 4000:
        return False
    head = text[:120]
    if head.startswith("data:") and "base64" in head:
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", text[:500]))


def _compact_value(value: Any, limit: int = 3000) -> Any:
    if isinstance(value, str):
        if _is_base64ish(value) or value.lstrip().lower().startswith("<!doctype html") or value.lstrip().lower().startswith("<html"):
            return f"[omitted large/binary/html payload: {len(value):,} chars]"
        return _truncate(value, limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item, max(800, limit // 2)) for item in value[:8]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, nested in value.items():
            if str(key).lower() in RAW_RESULT_KEYS:
                if str(key).lower() in {"documents"}:
                    compact[key] = _compact_value(nested, 1200)
                else:
                    compact[key] = "[omitted raw payload]"
                continue
            compact[key] = _compact_value(nested, max(800, limit // 2))
        return compact
    return _truncate(str(value), limit)


def compact_agent_result(result: Any, max_chars: int = 12_000) -> dict[str, Any]:
    """Extract durable, low-token memory from an agent result."""
    if not isinstance(result, dict):
        return {"summary": _truncate(str(result), max_chars)}
    out: dict[str, Any] = {}
    for key in SUMMARY_KEYS:
        if key in result and result[key] not in (None, "", [], {}):
            out[key] = _compact_value(result[key])
    if not out:
        for key, value in result.items():
            if str(key).lower() in RAW_RESULT_KEYS or key in {"agent", "mirror_critique"}:
                continue
            if value not in (None, "", [], {}):
                out[key] = _compact_value(value)
            if len(out) >= 8:
                break
    return out or {"result": "[no durable summary fields]"}


class RunContextPolicy:
    """Per-session policy for context retrieval, writeback, and resource limits."""

    def __init__(self, session_id: str, founder_id: str, constraints: dict[str, Any] | None = None):
        constraints = constraints or {}
        policy = constraints.get("context_policy") if isinstance(constraints.get("context_policy"), dict) else {}
        self.session_id = session_id
        self.founder_id = founder_id
        self.company_id = str(constraints.get("company_id") or founder_id)
        self.max_context_chars = int(policy.get("max_context_chars") or constraints.get("max_context_chars") or _env_int("ASTRA_AGENT_CONTEXT_PACK_CHARS", 12_000))
        self.max_brain_retrievals = int(policy.get("max_brain_retrievals") or constraints.get("max_brain_retrievals") or _env_int("ASTRA_MAX_BRAIN_RETRIEVALS_PER_SESSION", 24))
        self.max_brain_writes = int(policy.get("max_brain_writes") or constraints.get("max_brain_writes") or _env_int("ASTRA_MAX_BRAIN_WRITES_PER_SESSION", 80))
        # Agents are network-bound (OpenRouter streams; GIL released in worker threads),
        # so run them all at once instead of in 4-wide waves — cuts the non-research
        # wall time. The thread pool (128) and OpenRouter handle the concurrency fine.
        self.max_concurrent_agents = int(policy.get("max_concurrent_agents") or constraints.get("max_concurrent_agents") or _env_int("ASTRA_MAX_CONCURRENT_AGENTS_PER_SESSION", 8))
        self.brain_limit = int(policy.get("brain_limit") or constraints.get("brain_limit") or 6)
        self._brain_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._brain_retrievals = 0
        self._brain_writes = 0

    @staticmethod
    def _norm_query(query: str) -> str:
        return " ".join(re.findall(r"[a-z0-9_-]+", (query or "").lower()))[:240]

    def _current_goal_pack(self, agent_name: str) -> dict[str, Any]:
        try:
            from backend.missions.company_goal import current_goal, get_company_goal
            root = get_company_goal(self.founder_id, self.company_id) or {}
            current = current_goal(self.founder_id, self.company_id) or {}
            tasks = [
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "status": task.get("status"),
                    "owner_agents": task.get("owner_agents", []),
                    "done_agents": task.get("done_agents", []),
                }
                for task in current.get("tasks") or []
                if agent_name in (task.get("owner_agents") or [])
            ]
            return {
                "north_star": root.get("north_star") or root.get("company_goal") or "",
                "current_goal_id": current.get("id", ""),
                "current_goal_title": current.get("title", ""),
                "current_goal_status": current.get("status", ""),
                "agent_goal_tasks": tasks,
                "budget": root.get("budget", {}),
            }
        except Exception:
            return {}

    def _brain_context(self, query: str) -> dict[str, Any]:
        key = (self.company_id, self._norm_query(query), self.brain_limit)
        if key in self._brain_cache:
            return {**self._brain_cache[key], "cache_hit": True}
        if self._brain_retrievals >= self.max_brain_retrievals:
            return {"ok": False, "skipped": "brain retrieval budget exhausted", "context": ""}
        self._brain_retrievals += 1
        try:
            from backend.tools.company_brain import company_brain_agent_context
            result = company_brain_agent_context(
                self.founder_id,
                query,
                self.brain_limit,
                company_id=self.company_id,
            )
        except Exception:
            try:
                from backend.tools.company_brain import company_brain_context
                result = {
                    "ok": True,
                    "context": company_brain_context(
                        self.founder_id,
                        query,
                        self.brain_limit,
                        company_id=self.company_id,
                    ),
                }
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "context": ""}
        self._brain_cache[key] = result
        return result

    def build_agent_shared(
        self,
        *,
        base_shared: dict[str, Any],
        agent_name: str,
        task: dict[str, Any],
        dep_results: dict[str, Any],
        vault_context: str = "",
    ) -> dict[str, Any]:
        query = f"{task.get('instruction') or ''}\n{base_shared.get('company_name', '')}\n{base_shared.get('company_brain_context', '')[:1200]}"
        brain = self._brain_context(query)
        # The heavy payloads (brain context, deps, vault notes, goal) live ONLY in the
        # flat shared keys below — NOT also inside run_context_pack. Both the pack and the
        # flat keys are rendered into the prompt by _render_shared_context, so embedding
        # the same data in both doubled ~5-8k tokens/call. run_context_pack has no
        # programmatic readers; it's prompt-only metadata pointing at the flat keys.
        goal_pack = self._current_goal_pack(agent_name)
        brain_context_text = _truncate(str(brain.get("context") or brain.get("formatted") or ""), 6000)
        vault_notes = _truncate(vault_context or "", 3500)
        pack = {
            "policy": {
                "source_of_truth": "Use current_company_goal, company_brain_context, prior_results and prior_vault_notes (below) as injected source-of-truth; call Company Brain tools only for missing facts.",
                "max_context_chars": self.max_context_chars,
                "brain_cache_hit": bool(brain.get("cache_hit")),
            },
            "company_brain": {
                "canonical_sources": _compact_value(brain.get("canonical_sources") or [], 3000),
                "open_proposals": _compact_value(brain.get("open_proposals") or [], 2000),
                "retrieval": brain.get("retrieval", "unknown"),
            },
            "resource_budget": {
                "brain_retrievals_used": self._brain_retrievals,
                "brain_retrievals_max": self.max_brain_retrievals,
                "brain_writes_used": self._brain_writes,
                "brain_writes_max": self.max_brain_writes,
            },
        }
        rendered = _jsonish(pack, self.max_context_chars)
        if len(rendered) > self.max_context_chars:
            pack["company_brain"]["canonical_sources"] = "[omitted: context budget exhausted]"
            pack["company_brain"]["open_proposals"] = "[omitted: context budget exhausted]"
        return {
            **base_shared,
            "run_context_pack": pack,
            "current_company_goal": goal_pack,
            "company_brain_context": brain_context_text or base_shared.get("company_brain_context", ""),
            # compact_agent_result (already used for company_brain persistence below)
            # keeps only the fields a downstream agent actually needs — summary,
            # key_findings, decisions, next_actions, artifacts_produced, etc — and
            # drops raw payloads by design. The previous _compact_value(dep_results,
            # 4000) blindly truncated the whole dict by character count, which could
            # cut off the useful summary while keeping an earlier raw field intact
            # depending on dict iteration order. No code reads prior_results
            # programmatically; it's prompt-only, rendered by _render_shared_context.
            "prior_results": {
                dep_name: compact_agent_result(dep_result)
                for dep_name, dep_result in dep_results.items()
            },
            "prior_vault_notes": vault_notes,
        }

    def persist_agent_result(
        self,
        *,
        agent_name: str,
        task: dict[str, Any],
        result: Any,
        artifact_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._brain_writes >= self.max_brain_writes or not self.founder_id:
            return {"ok": False, "skipped": "brain write budget exhausted"}
        compact = compact_agent_result(result)
        payload = {
            "agent": agent_name,
            "session_id": self.session_id,
            "task_id": task.get("id", ""),
            "task_title": task.get("stack_task_title") or task.get("instruction", "")[:180],
            "result": compact,
            "artifact_verification": _compact_value(artifact_verification or {}, 3000),
            "recorded_at_unix": time.time(),
        }
        try:
            from backend.tools.company_brain import add_company_brain_record
            self._brain_writes += 1
            return add_company_brain_record(
                founder_id=self.founder_id,
                source="astra_agent",
                title=f"{agent_name} output - {task.get('id', self.session_id)}",
                content=_jsonish(payload, 14_000),
                kind="agent_output",
                canonical=False,
                stale_risk="medium",
                metadata={
                    "session_id": self.session_id,
                    "company_id": self.company_id,
                    "agent": agent_name,
                    "task_id": task.get("id", ""),
                },
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
